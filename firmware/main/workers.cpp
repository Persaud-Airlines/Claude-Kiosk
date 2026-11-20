#include "workers.hpp"

#include <cstring>
#include "app_bus.hpp"
#include "cJSON.h"
#include "config.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_random.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "host_client.hpp"
#include "jpeg_decoder.h"
#include "offline_queue.hpp"
#include "settings_store.hpp"
#include "time_sync.hpp"
#include "wifi_manager.hpp"

namespace dt {
QueueHandle_t jobs_queue();

namespace {
const char *TAG = "worker";
ICameraProvider *s_cam;
volatile bool s_scan_active = false;
volatile bool s_pairing = false;

int64_t now_ms() { return esp_timer_get_time() / 1000; }

UiMsg *msg(Msg t)
{
    auto *m = new UiMsg();
    m->type = t;
    return m;
}

std::string random_hex(size_t bytes)
{
    std::string out;
    static const char *hex = "0123456789abcdef";
    for (size_t i = 0; i < bytes; ++i) {
        uint8_t b = esp_random() & 0xFF;
        out += hex[b >> 4];
        out += hex[b & 0xF];
    }
    return out;
}

void apply_config(const KioskConfig &cfg)
{
    SettingsStore::get().saveConfig(cfg);
    TimeSync::setPosixTz(cfg.posixTz);
    auto *m = msg(Msg::ConfigUpdated);
    m->cfg = cfg;
    post_ui(m);
}

void handle_revoked()
{
    ESP_LOGW(TAG, "device token rejected (401): returning to pairing");
    SettingsStore::get().clearPairing();
    post_ui(msg(Msg::Revoked));
}

// ------------------------------------------------------------------------- event submit
std::string build_event_json(const JobMsg &j, bool offline)
{
    // a=event_type b=destination c=first d=last e=scan_session_id flag=manual
    KioskConfig cfg = SettingsStore::get().config();
    cJSON *o = cJSON_CreateObject();
    cJSON_AddStringToObject(o, "event_type", j.a.c_str());
    if (j.a == "SIGN_OUT") cJSON_AddStringToObject(o, "destination", j.b.c_str());
    cJSON_AddStringToObject(o, "first_name", j.c.c_str());
    cJSON_AddStringToObject(o, "last_name", j.d.c_str());
    if (!j.e.empty()) cJSON_AddStringToObject(o, "scan_session_id", j.e.c_str());
    std::string ts = TimeSync::isoUtcNow();
    if (!ts.empty()) cJSON_AddStringToObject(o, "client_timestamp_utc", ts.c_str());
    cJSON_AddStringToObject(o, "client_event_id", random_hex(12).c_str());
    cJSON_AddStringToObject(o, "entry_method", j.flag ? "MANUAL" : "CARD_OCR");
    cJSON_AddStringToObject(o, "device_uid", SettingsStore::get().deviceUid().c_str());
    if (!cfg.roomId.empty()) cJSON_AddStringToObject(o, "room_id", cfg.roomId.c_str());
    cJSON_AddBoolToObject(o, "was_offline_queued", offline);
    char *s = cJSON_PrintUnformatted(o);
    std::string out(s);
    cJSON_free(s);
    cJSON_Delete(o);
    return out;
}

std::string mark_offline(const std::string &json)
{
    cJSON *o = cJSON_Parse(json.c_str());
    if (!o) return json;
    cJSON_ReplaceItemInObject(o, "was_offline_queued", cJSON_CreateBool(true));
    char *s = cJSON_PrintUnformatted(o);
    std::string out(s);
    cJSON_free(s);
    cJSON_Delete(o);
    return out;
}

void submit_event(HostClient &host, const JobMsg &j)
{
    std::string body = build_event_json(j, false);
    HttpResult r = WifiManager::get().connected() ? host.postEvent(body) : HttpResult{};
    if (r.ok()) {
        auto *m = msg(Msg::EventDone);
        cJSON *root = cJSON_Parse(r.body.c_str());
        if (root) {
            cJSON *lt = cJSON_GetObjectItem(root, "local_time");
            if (cJSON_IsString(lt)) m->a = lt->valuestring;
            cJSON_Delete(root);
        }
        post_ui(m);
        return;
    }
    if (r.status == 401) {
        // Keep the student's record: queue it so it is replayed if the kiosk is re-paired to the same school.
        OfflineQueue::get().push(mark_offline(body));
        handle_revoked();
        return;
    }
    if (r.status >= 400 && r.status < 500) {
        auto *m = msg(Msg::EventRejected);
        m->i = r.status;
        post_ui(m);
        return;
    }
    // Transport failure or 5xx: persist with the original timestamp and replay later (crisis-safe).
    OfflineQueue::get().push(mark_offline(body));
    net_snapshot().queueDepth = (int)OfflineQueue::get().size();
    auto *m = msg(Msg::EventQueued);
    m->a = TimeSync::localClock();
    post_ui(m);
}

bool flush_queue(HostClient &host)
{
    auto items = OfflineQueue::get().peek(20);
    if (items.empty()) return true;
    cJSON *root = cJSON_CreateObject();
    cJSON *arr = cJSON_AddArrayToObject(root, "events");
    for (auto &it : items) {
        cJSON *e = cJSON_Parse(it.second.c_str());
        if (e) cJSON_AddItemToArray(arr, e);
        else OfflineQueue::get().remove(it.first);  // corrupt entry
    }
    char *s = cJSON_PrintUnformatted(root);
    std::string body(s);
    cJSON_free(s);
    cJSON_Delete(root);
    HttpResult r = host.postBatch(body);
    if (r.status == 401) {
        handle_revoked();
        return false;
    }
    if (!r.ok()) return false;
    cJSON *res = cJSON_Parse(r.body.c_str());
    if (!cJSON_IsArray(res)) {
        cJSON_Delete(res);
        return false;
    }
    int idx = 0;
    cJSON *it;
    cJSON_ArrayForEach(it, res)
    {
        if (idx >= (int)items.size()) break;
        bool accepted = cJSON_IsTrue(cJSON_GetObjectItem(it, "accepted"));
        if (!accepted) {
            cJSON *err = cJSON_GetObjectItem(it, "error");
            ESP_LOGW(TAG, "queued event rejected by server (%s); dropping", cJSON_IsString(err) ? err->valuestring : "?");
        }
        OfflineQueue::get().remove(items[idx].first);  // accepted, duplicate or permanently rejected
        ++idx;
    }
    cJSON_Delete(res);
    ESP_LOGI(TAG, "flushed %d offline event(s)", idx);
    return true;
}

// --------------------------------------------------------------------------- net worker
void net_task(void *)
{
    HostClient host;
    std::string pairSecret;
    int64_t pairExpiresAt = 0, nextPairPoll = 0, nextHeartbeat = 0, nextFlush = 0;
    bool hostUp = false;

    auto publish_health = [&]() {
        NetSnapshot &s = net_snapshot();
        s.queueDepth = (int)OfflineQueue::get().size();
        s.health = !WifiManager::get().connected() ? NetHealth::NoWifi : hostUp ? NetHealth::Online : NetHealth::HostDown;
        post_ui(msg(Msg::NetStatus));
    };

    auto start_pairing = [&]() {
        PairInit p = host.pairInit();
        if (!p.ok) {
            post_ui(msg(Msg::PairError));
            nextPairPoll = now_ms() + 5000;
            pairSecret.clear();
            return;
        }
        pairSecret = p.secret;
        pairExpiresAt = now_ms() + (int64_t)p.expiresIn * 1000;
        nextPairPoll = now_ms() + DT_PAIR_POLL_MS;
        auto *m = msg(Msg::PairCode);
        m->a = p.code;
        m->b = p.url;
        m->i = p.expiresIn;
        post_ui(m);
    };

    // Auto-connect with stored credentials
    std::string ssid = SettingsStore::get().wifiSsid();
    if (!ssid.empty()) WifiManager::get().connectAsync(ssid, SettingsStore::get().wifiPass());

    while (true) {
        JobMsg *job = nullptr;
        if (xQueueReceive(jobs_queue(), &job, pdMS_TO_TICKS(250)) == pdTRUE && job) {
            switch (job->type) {
            case Job::ScanWifi: {
                auto *m = msg(Msg::WifiScanDone);
                m->aps = WifiManager::get().scan();
                post_ui(m);
                break;
            }
            case Job::ConnectWifi: {
                if (WifiManager::get().connect(job->a, job->b)) {
                    SettingsStore::get().setWifi(job->a, job->b);
                    TimeSync::start();
                    auto *m = msg(Msg::WifiConnected);
                    m->a = WifiManager::get().ip();
                    m->b = job->a;
                    m->i = WifiManager::get().rssi();
                    post_ui(m);
                } else {
                    post_ui(msg(Msg::WifiFailed));
                }
                break;
            }
            case Job::CheckHost: {
                std::string url = job->a.empty() ? SettingsStore::get().hostUrl() : job->a;
                hostUp = host.health(url);
                if (hostUp && !job->a.empty()) SettingsStore::get().setHostUrl(job->a);
                post_ui(msg(hostUp ? Msg::HostOk : Msg::HostFail));
                publish_health();
                break;
            }
            case Job::StartPairing:
                s_pairing = true;
                start_pairing();
                break;
            case Job::StopPairing:
                s_pairing = false;
                break;
            case Job::SubmitEvent:
                submit_event(host, *job);
                publish_health();
                break;
            case Job::VerifyPin: {
                if (!WifiManager::get().connected()) {
                    post_ui(msg(Msg::PinOffline));
                    break;
                }
                int st = host.verifyPin(job->a);
                post_ui(msg(st == 200 ? Msg::PinOk : st == 0 ? Msg::PinOffline : Msg::PinBad));
                break;
            }
            case Job::RePair:
                host.unpair();  // best effort; server also tolerates a brand-new pair/init
                SettingsStore::get().clearPairing();
                break;
            case Job::FactoryReset:
                host.unpair();
                SettingsStore::get().factoryReset();
                vTaskDelay(pdMS_TO_TICKS(300));
                esp_restart();
                break;
            }
            delete job;
        }

        int64_t t = now_ms();
        bool wifi = WifiManager::get().connected();
        if (wifi) TimeSync::start();

        if (s_pairing && wifi && t >= nextPairPoll) {
            if (pairSecret.empty() || t >= pairExpiresAt) {
                start_pairing();  // code expired: fetch a fresh one automatically
            } else {
                nextPairPoll = t + DT_PAIR_POLL_MS;
                PairStatus ps = host.pairStatus(pairSecret);
                if (ps.status == "paired" && !ps.token.empty()) {
                    s_pairing = false;
                    SettingsStore::get().savePairing(ps.token, ps.cfg);
                    TimeSync::setPosixTz(ps.cfg.posixTz);
                    hostUp = true;
                    auto *m = msg(Msg::PairDone);
                    m->cfg = ps.cfg;
                    post_ui(m);
                    nextHeartbeat = 0;
                    nextFlush = t + 2000;
                } else if (ps.status == "expired" || ps.status == "revoked") {
                    pairSecret.clear();
                } else if (ps.status == "error") {
                    post_ui(msg(Msg::PairError));
                }
            }
        }

        if (SettingsStore::get().paired() && wifi && t >= nextHeartbeat) {
            nextHeartbeat = t + DT_HEARTBEAT_MS;
            KioskConfig cfg = SettingsStore::get().config();
            int st = host.heartbeat(cfg, WifiManager::get().rssi(), WifiManager::get().ip(), OfflineQueue::get().size());
            hostUp = st == 200;
            if (st == 200) apply_config(cfg);
            else if (st == 401) handle_revoked();
            if (!hostUp) nextHeartbeat = t + 10000;  // retry sooner while the host is down
            publish_health();
        } else if (!wifi && hostUp) {
            hostUp = false;
            publish_health();
        }

        if (SettingsStore::get().paired() && wifi && hostUp && t >= nextFlush) {
            nextFlush = t + DT_QUEUE_FLUSH_MS;
            if (OfflineQueue::get().size() > 0) {
                if (!flush_queue(host)) hostUp = false;
                publish_health();
            }
        }
    }
}

// ------------------------------------------------------------------------- card scanner
void scan_task(void *)
{
    HostClient host;
    const size_t cap = 256 * 1024;
    auto *jpeg = static_cast<uint8_t *>(heap_caps_malloc(cap, MALLOC_CAP_SPIRAM));
    uint32_t seq = 0;
    const int64_t minInterval = 1000 / (CONFIG_DT_SCAN_MAX_FPS > 0 ? CONFIG_DT_SCAN_MAX_FPS : 3);
    int64_t last = 0;
    while (true) {
        if (!s_scan_active || !jpeg) {
            vTaskDelay(pdMS_TO_TICKS(100));
            continue;
        }
        int64_t t = now_ms();
        if (t - last < minInterval) {
            vTaskDelay(pdMS_TO_TICKS(minInterval - (t - last)));
            continue;
        }
        size_t n = s_cam->frames().copyIfNewer(jpeg, cap, &seq);
        if (!n) {
            vTaskDelay(pdMS_TO_TICKS(40));
            continue;
        }
        last = now_ms();
        if (!WifiManager::get().connected()) {
            auto *m = msg(Msg::ScanMiss);
            m->i = -1;
            post_ui(m);
            vTaskDelay(pdMS_TO_TICKS(1000));
            continue;
        }
        ScanResult r = host.scanCard(jpeg, n);
        if (!s_scan_active) continue;  // user left the screen while the request was in flight
        if (r.status == 401) {
            s_scan_active = false;
            handle_revoked();
            continue;
        }
        if (r.ok && r.detected) {
            s_scan_active = false;  // freeze: one detection per scan session
            auto *m = msg(Msg::ScanDetected);
            m->a = r.firstName;
            m->b = r.lastName;
            m->c = r.sessionId;
            m->f = r.confidence;
            post_ui(m);
        } else {
            auto *m = msg(Msg::ScanMiss);
            m->i = r.status == 0 ? -1 : 0;  // -1 => host unreachable
            m->a = r.reason;
            post_ui(m);
        }
    }
}

// -------------------------------------------------------------------- preview decoding
constexpr int kMaxW = 640, kMaxH = 480;
uint8_t *s_buf[2];
lv_img_dsc_t s_dsc[2];
uint8_t *s_snap_buf;
lv_img_dsc_t s_snap_dsc;
int s_front = -1;               // buffer currently handed to LVGL
volatile int s_ready = -1;      // freshly decoded buffer waiting for the UI
volatile bool s_consumed = true;
SemaphoreHandle_t s_prev_lock;
}  // namespace

void scanner_set_active(bool on) { s_scan_active = on; }

PreviewDecoder &PreviewDecoder::get()
{
    static PreviewDecoder p;
    return p;
}

void PreviewDecoder::start(ICameraProvider *cam)
{
    cam_ = cam;
    s_prev_lock = xSemaphoreCreateMutex();
    for (int i = 0; i < 2; ++i) s_buf[i] = static_cast<uint8_t *>(heap_caps_malloc(kMaxW * kMaxH * 2, MALLOC_CAP_SPIRAM));
    s_snap_buf = static_cast<uint8_t *>(heap_caps_malloc(kMaxW * kMaxH * 2, MALLOC_CAP_SPIRAM));
    xTaskCreatePinnedToCore(&PreviewDecoder::task, "preview", 6144, this, 3, nullptr, 0);
}

void PreviewDecoder::setActive(bool on)
{
    active_ = on;
    cam_->setStreaming(on);
}

void PreviewDecoder::task(void *arg)
{
    auto *self = static_cast<PreviewDecoder *>(arg);
    const size_t cap = 256 * 1024;
    auto *jpeg = static_cast<uint8_t *>(heap_caps_malloc(cap, MALLOC_CAP_SPIRAM));
    uint32_t seq = 0;
    while (true) {
        if (!self->active_ || !s_consumed || !jpeg || !s_buf[0] || !s_buf[1]) {
            vTaskDelay(pdMS_TO_TICKS(20));
            continue;
        }
        size_t n = self->cam_->frames().copyIfNewer(jpeg, cap, &seq);
        if (!n) {
            vTaskDelay(pdMS_TO_TICKS(15));
            continue;
        }
        int back = (s_front == 0) ? 1 : 0;
        esp_jpeg_image_cfg_t cfg = {};
        cfg.indata = jpeg;
        cfg.indata_size = n;
        cfg.outbuf = s_buf[back];
        cfg.outbuf_size = kMaxW * kMaxH * 2;
        cfg.out_format = JPEG_IMAGE_FORMAT_RGB565;
        cfg.out_scale = CONFIG_DT_UVC_WIDTH > 800 ? JPEG_IMAGE_SCALE_1_4 : JPEG_IMAGE_SCALE_1_2;
        cfg.flags.swap_color_bytes = 0;  // LVGL native RGB565 (LV_COLOR_16_SWAP = 0)
        esp_jpeg_image_output_t out = {};
        if (esp_jpeg_decode(&cfg, &out) != ESP_OK || out.width == 0) {
            vTaskDelay(pdMS_TO_TICKS(30));
            continue;
        }
        lv_img_dsc_t &d = s_dsc[back];
        memset(&d, 0, sizeof d);
        d.header.cf = LV_IMG_CF_TRUE_COLOR;
        d.header.w = out.width;
        d.header.h = out.height;
        d.data_size = out.width * out.height * 2;
        d.data = s_buf[back];
        xSemaphoreTake(s_prev_lock, portMAX_DELAY);
        s_ready = back;
        s_consumed = false;
        xSemaphoreGive(s_prev_lock);
    }
}

const lv_img_dsc_t *PreviewDecoder::takeFrame()
{
    const lv_img_dsc_t *r = nullptr;
    xSemaphoreTake(s_prev_lock, portMAX_DELAY);
    if (!s_consumed && s_ready >= 0) {
        s_front = s_ready;
        s_ready = -1;
        s_consumed = true;
        r = &s_dsc[s_front];
    }
    xSemaphoreGive(s_prev_lock);
    return r;
}

const lv_img_dsc_t *PreviewDecoder::snapshot()
{
    if (s_front < 0 || !s_snap_buf) return nullptr;
    const lv_img_dsc_t &src = s_dsc[s_front];
    memcpy(s_snap_buf, src.data, src.data_size);
    s_snap_dsc = src;
    s_snap_dsc.data = s_snap_buf;
    return &s_snap_dsc;
}

void workers_start(ICameraProvider *cam)
{
    s_cam = cam;
    xTaskCreatePinnedToCore(net_task, "net", 12 * 1024, nullptr, 5, nullptr, 0);
    xTaskCreatePinnedToCore(scan_task, "scan", 8 * 1024, nullptr, 4, nullptr, 0);
}

}  // namespace dt
