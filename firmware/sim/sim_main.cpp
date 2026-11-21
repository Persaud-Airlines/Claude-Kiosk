// Desktop simulator for the kiosk UI.
//
// Compiles the real firmware UI (main/ui/*.cpp, fonts, LVGL 8.3) on Linux/macOS with the ESP-IDF
// platform layer replaced by in-process fakes, then drives the touchscreen through a scripted
// scenario and writes 800x480 screenshots (PPM) of every state. A fake "worker" answers jobs the
// same way the real net worker does, so the state machine runs end-to-end.
//
//   cmake -S firmware/sim -B build-sim && cmake --build build-sim -j && ./build-sim/kiosk_sim out/
#include <chrono>
#include <iterator>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <deque>
#include <fstream>
#include <map>
#include <mutex>
#include <string>
#include <vector>

#include "app_bus.hpp"
#include "camera_provider.hpp"
#include "i18n.hpp"
#include "kiosk_app.hpp"
#include "lvgl.h"
#include "settings_store.hpp"
#include "sim_tick.h"
#include "time_sync.hpp"
#include "wifi_manager.hpp"
#include "workers.hpp"

// Portable time-zone and calendar helpers (POSIX setenv/localtime_r do not exist on MSVC).
static uint32_t g_tick = 0;
#ifdef _WIN32
static void set_tz(const char *v) { _putenv_s("TZ", v); _tzset(); }
static struct tm local_tm(time_t t) { struct tm r; localtime_s(&r, &t); return r; }
static struct tm utc_tm(time_t t) { struct tm r; gmtime_s(&r, &t); return r; }
#else
static void set_tz(const char *v) { setenv("TZ", v, 1); tzset(); }
static struct tm local_tm(time_t t) { struct tm r; localtime_r(&t, &r); return r; }
static struct tm utc_tm(time_t t) { struct tm r; gmtime_r(&t, &r); return r; }
#endif
extern "C" uint32_t sim_tick_ms(void) { return g_tick; }

namespace dt {
// ------------------------------------------------------------------ SettingsStore (in memory)
static std::map<std::string, std::string> g_kv;
static KioskConfig g_cfg;
SettingsStore &SettingsStore::get()
{
    static SettingsStore s;
    return s;
}
SettingsStore::SettingsStore() {}
void SettingsStore::load() { g_kv["uid"] = "DTK-3F9A12C07B44E519"; }
std::string SettingsStore::getStr(const char *k, const std::string &d) { return g_kv.count(k) ? g_kv[k] : d; }
void SettingsStore::setStr(const char *k, const std::string &v) { g_kv[k] = v; }
std::string SettingsStore::deviceUid() { return getStr("uid"); }
std::string SettingsStore::locale() { return getStr("locale"); }
void SettingsStore::setLocale(const std::string &l) { setStr("locale", l); }
std::string SettingsStore::wifiSsid() { return getStr("ssid"); }
std::string SettingsStore::wifiPass() { return getStr("pass"); }
void SettingsStore::setWifi(const std::string &s, const std::string &p) { setStr("ssid", s), setStr("pass", p); }
std::string SettingsStore::hostUrl() { return getStr("host", "https://portal.lakeview.example.com"); }
void SettingsStore::setHostUrl(const std::string &u) { setStr("host", u); }
bool SettingsStore::paired() { return !getStr("token").empty(); }
std::string SettingsStore::token() { return getStr("token"); }
void SettingsStore::savePairing(const std::string &t, const KioskConfig &c) { setStr("token", t), g_cfg = c; }
KioskConfig SettingsStore::config() { return g_cfg; }
void SettingsStore::saveConfig(const KioskConfig &c) { g_cfg = c; }
void SettingsStore::clearPairing() { g_kv.erase("token"); }
void SettingsStore::factoryReset() { g_kv.clear(); }
std::string joinDestinations(const std::vector<std::string> &d)
{
    std::string o;
    for (auto &x : d) o += x + "\x1F";
    return o;
}
std::vector<std::string> splitDestinations(const std::string &) { return {}; }

// ---------------------------------------------------------------------------- Wi-Fi / time
static bool g_wifi = false;
WifiManager &WifiManager::get()
{
    static WifiManager w;
    return w;
}
void WifiManager::init() {}
std::vector<ApInfo> WifiManager::scan() { return {}; }
bool WifiManager::connect(const std::string &, const std::string &, int) { return true; }
void WifiManager::connectAsync(const std::string &, const std::string &) {}
bool WifiManager::connected() const { return g_wifi; }
std::string WifiManager::ip() const { return g_wifi ? "10.20.4.37" : "0.0.0.0"; }
int WifiManager::rssi() const { return -58; }
std::string WifiManager::ssid() const { return g_wifi ? "Lakeview-Staff" : ""; }
int rssiBars(int r) { return r >= -55 ? 4 : r >= -65 ? 3 : r >= -75 ? 2 : r >= -85 ? 1 : 0; }

static const time_t kSimEpoch = 1795189262;  // 2026-11-20 15:01:02 UTC (fixed for reproducible screenshots)
static time_t simNow() { return kSimEpoch + g_tick / 1000; }
void TimeSync::start() {}
bool TimeSync::synced() { return true; }
void TimeSync::setPosixTz(const std::string &p) { set_tz(p.empty() ? "UTC0" : p.c_str()); }
std::string TimeSync::localClock()
{
    time_t n = simNow();
    struct tm t = local_tm(n);
    char b[16];
    strftime(b, sizeof b, "%I:%M:%S %p", &t);
    return b[0] == '0' ? b + 1 : b;
}
std::string TimeSync::utcClock()
{
    time_t n = simNow();
    struct tm t = utc_tm(n);
    char b[16];
    strftime(b, sizeof b, "%H:%M:%S", &t);
    return b;
}
std::string TimeSync::isoUtcNow() { return "2026-11-20T15:01:02.000Z"; }

// ------------------------------------------------------------------------------ camera
FrameSlot::FrameSlot(size_t) : lock_(nullptr), buf_(nullptr), cap_(0) {}
FrameSlot::~FrameSlot() {}
void FrameSlot::put(const uint8_t *, size_t) {}
size_t FrameSlot::copyIfNewer(uint8_t *, size_t, uint32_t *) { return 0; }
size_t FrameSlot::copyLatest(uint8_t *, size_t, uint32_t *) { return 0; }
void FrameSlot::clear() {}
class SimCamera : public ICameraProvider {
public:
    esp_err_t begin() override { return ESP_OK; }
    void setStreaming(bool) override {}
    bool connected() const override { return true; }
    const char *name() const override { return "Mock frame injector"; }
};
ICameraProvider *createCameraProvider() { return new SimCamera(); }

static std::vector<uint8_t> g_frame;
static lv_img_dsc_t g_frame_dsc;
static bool g_preview_active = false;
static uint32_t g_frame_served_at = 0;
PreviewDecoder &PreviewDecoder::get()
{
    static PreviewDecoder p;
    return p;
}
void PreviewDecoder::start(ICameraProvider *cam) { cam_ = cam; }
void PreviewDecoder::setActive(bool on) { g_preview_active = on; }
const lv_img_dsc_t *PreviewDecoder::takeFrame()
{
    if (!g_preview_active || g_frame.empty() || g_tick - g_frame_served_at < 100) return nullptr;
    g_frame_served_at = g_tick;
    return &g_frame_dsc;
}
const lv_img_dsc_t *PreviewDecoder::snapshot() { return g_frame.empty() ? nullptr : &g_frame_dsc; }
void scanner_set_active(bool) {}
void workers_start(ICameraProvider *) {}

// --------------------------------------------------------- bus + fake worker (in-process)
static std::deque<UiMsg *> g_ui;
static std::deque<JobMsg *> g_jobs;
static NetSnapshot g_snap;
void bus_init() {}
void post_ui(UiMsg *m) { g_ui.push_back(m); }
UiMsg *pop_ui()
{
    if (g_ui.empty()) return nullptr;
    UiMsg *m = g_ui.front();
    g_ui.pop_front();
    return m;
}
void post_job(JobMsg *j) { g_jobs.push_back(j); }
NetSnapshot &net_snapshot() { return g_snap; }

KioskConfig demoConfig(bool lockdown)
{
    KioskConfig c;
    c.schoolName = "Lakeview Secondary School";
    c.roomNumber = "204";
    c.roomName = "Grade 12 Physics";
    c.roomId = "6c1d3c7e-2f43-4b0f-9d7a-1b2c3d4e5f60";
    c.timezone = "America/Toronto";
    c.posixTz = "EST5EDT,M3.2.0,M11.1.0";
    c.destinations = {"Washroom", "Office", "Library", "Guidance", "Water", "Other"};
    c.lockdown = lockdown;
    return c;
}

static void runFakeWorker()
{
    while (!g_jobs.empty()) {
        JobMsg *j = g_jobs.front();
        g_jobs.pop_front();
        auto *m = new UiMsg();
        switch (j->type) {
        case Job::ScanWifi:
            m->type = Msg::WifiScanDone;
            m->aps = {{"Lakeview-Staff", -48, true}, {"Lakeview-Kiosks", -57, true}, {"Lakeview-Guest", -66, false},
                      {"Portable-7 Printer", -79, true}, {"Board-IoT", -84, true}};
            break;
        case Job::ConnectWifi:
            g_wifi = true;
            m->type = Msg::WifiConnected;
            m->a = "10.20.4.37";
            m->b = j->a;
            m->i = -48;
            break;
        case Job::CheckHost: m->type = Msg::HostOk; break;
        case Job::StartPairing:
            m->type = Msg::PairCode;
            m->a = "A7KD-93XQ";
            m->b = "https://portal.lakeview.example.com/pair?code=A7KD-93XQ&uid=DTK-3F9A12C07B44E519";
            m->i = 900;
            break;
        case Job::SubmitEvent:
            m->type = Msg::EventDone;
            m->a = TimeSync::localClock();
            break;
        case Job::VerifyPin: m->type = Msg::PinOk; break;
        default:
            delete m;
            m = nullptr;
        }
        if (m) post_ui(m);
        delete j;
    }
}
}  // namespace dt

// ------------------------------------------------------------------ display + scripted touch
static const int W = 800, H = 480;
static std::vector<lv_color_t> g_fb(W * H);
static lv_coord_t g_tx = 0, g_ty = 0;
static bool g_pressed = false;

static void flush_cb(lv_disp_drv_t *drv, const lv_area_t *a, lv_color_t *map)
{
    for (int y = a->y1; y <= a->y2; ++y)
        memcpy(&g_fb[y * W + a->x1], map + (y - a->y1) * (a->x2 - a->x1 + 1), (a->x2 - a->x1 + 1) * sizeof(lv_color_t));
    lv_disp_flush_ready(drv);
}

static void touch_cb(lv_indev_drv_t *, lv_indev_data_t *d)
{
    d->point.x = g_tx;
    d->point.y = g_ty;
    d->state = g_pressed ? LV_INDEV_STATE_PRESSED : LV_INDEV_STATE_RELEASED;
}

static void run(uint32_t ms)
{
    for (uint32_t t = 0; t < ms; t += 5) {
        g_tick += 5;
        dt::runFakeWorker();
        lv_timer_handler();
    }
}

static void tap(int x, int y, uint32_t hold = 120)
{
    g_tx = x, g_ty = y, g_pressed = true;
    run(hold);
    g_pressed = false;
    run(150);
}

static std::string g_out = ".";
static void shot(const char *name)
{
    run(120);
    lv_refr_now(nullptr);
    std::string path = g_out + "/" + name + ".ppm";
    std::ofstream f(path, std::ios::binary);
    f << "P6\n" << W << " " << H << "\n255\n";
    for (const auto &c : g_fb) {
        uint16_t v = c.full;
        uint8_t r = ((v >> 11) & 0x1F) * 255 / 31, g = ((v >> 5) & 0x3F) * 255 / 63, b = (v & 0x1F) * 255 / 31;
        f.put(r), f.put(g), f.put(b);
    }
    printf("wrote %s\n", path.c_str());
}

int main(int argc, char **argv)
{
    if (argc > 1) g_out = argv[1];
    if (argc > 2) {  // optional raw RGB565 320x240 preview frame (generated from main/assets/mock_card.jpg)
        std::ifstream f(argv[2], std::ios::binary);
        dt::g_frame.assign(std::istreambuf_iterator<char>(f), {});
        if (dt::g_frame.size() == 320 * 240 * 2) {
            dt::g_frame_dsc.header.cf = LV_IMG_CF_TRUE_COLOR;
            dt::g_frame_dsc.header.w = 320;
            dt::g_frame_dsc.header.h = 240;
            dt::g_frame_dsc.data_size = dt::g_frame.size();
            dt::g_frame_dsc.data = dt::g_frame.data();
        } else {
            dt::g_frame.clear();
        }
    }
    lv_init();
    static lv_disp_draw_buf_t buf;
    static std::vector<lv_color_t> b1(W * 120);
    lv_disp_draw_buf_init(&buf, b1.data(), nullptr, W * 120);
    static lv_disp_drv_t disp;
    lv_disp_drv_init(&disp);
    disp.hor_res = W;
    disp.ver_res = H;
    disp.flush_cb = flush_cb;
    disp.draw_buf = &buf;
    lv_disp_drv_register(&disp);
    static lv_indev_drv_t indev;
    lv_indev_drv_init(&indev);
    indev.type = LV_INDEV_TYPE_POINTER;
    indev.read_cb = touch_cb;
    lv_indev_drv_register(&indev);

    dt::SettingsStore::get().load();
    dt::ICameraProvider *cam = dt::createCameraProvider();
    dt::PreviewDecoder::get().start(cam);
    dt::KioskApp::get().start(cam);

    using dt::Msg;
    using dt::UiMsg;
    run(1500);
    shot("01_boot_splash");
    run(2300);
    shot("02_wizard_welcome");
    tap(400, 424);                // GET STARTED
    shot("03_wizard_language");
    tap(400, 260);                // Français (shows translated wizard)
    run(200);
    shot("04_wizard_wifi_fr");
    dt::setLangCode("en");
    dt::SettingsStore::get().setLocale("en");
    tap(400, 80 + 8 + 30);        // first network row -> password screen
    shot("05_wizard_wifi_password");
    tap(722, 110);                // CONNECT
    run(400);
    shot("06_wizard_wifi_connected");
    tap(684, 428);                // NEXT
    run(300);
    shot("07_wizard_pairing");

    auto *paired = new UiMsg();
    paired->type = Msg::PairDone;
    paired->cfg = dt::demoConfig(false);
    dt::SettingsStore::get().savePairing("dtk_sim", paired->cfg);
    dt::TimeSync::setPosixTz(paired->cfg.posixTz);
    dt::net_snapshot().health = dt::NetHealth::Online;
    dt::post_ui(paired);
    run(300);
    shot("08_home");
    tap(204, 56 + 16 + 196);      // SIGN OUT
    shot("09_signout_destinations");
    tap(138, 56 + 84 + 75);       // Washroom
    run(400);
    shot("10_camera_scan");
    auto *det = new UiMsg();
    det->type = Msg::ScanDetected;
    det->a = "Jordan";
    det->b = "Taylor";
    det->c = "0f6c2a8e-1d5b-4c3e-9a77-5e2b8d1c4f90";
    det->f = 0.96f;
    dt::post_ui(det);
    run(300);
    shot("11_confirm_identity");
    tap(664, 56 + 290 + 60);      // CONFIRM
    run(300);
    shot("12_success_feedback");
    run(3200);                    // auto-return to HOME after 3.0 s

    auto *ld = new UiMsg();
    ld->type = Msg::ConfigUpdated;
    ld->cfg = dt::demoConfig(true);
    dt::post_ui(ld);
    run(300);
    shot("13_home_lockdown");
    tap(596, 268);                // SIGN IN
    run(8600);                    // manual-entry fallback appears after 8 s
    shot("14_sign_in_scan_manual_hint");
    tap(710, 56 + 290 + 48);      // Type my name
    run(300);
    shot("15_manual_entry");
    tap(100, 40);                 // BACK
    tap(100, 40);                 // BACK -> HOME
    run(200);
    g_tx = 700, g_ty = 28, g_pressed = true;  // 5 s hidden long-press on the clocks
    run(5300);
    g_pressed = false;
    run(200);
    shot("16_diagnostics");
    return 0;
}
