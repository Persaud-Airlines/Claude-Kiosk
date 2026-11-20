#include "settings_store.hpp"

#include <cstring>
#include "config.h"
#include "esp_log.h"
#include "esp_random.h"
#include "nvs.h"
#include "nvs_flash.h"

namespace dt {
namespace {
const char *TAG = "settings";
const char *NS = "kiosk";
const std::vector<std::string> kDefaultDest = {"Washroom", "Office", "Library", "Guidance", "Water", "Other"};

struct Guard {
    explicit Guard(SemaphoreHandle_t l) : l_(l) { xSemaphoreTakeRecursive(l_, portMAX_DELAY); }
    ~Guard() { xSemaphoreGiveRecursive(l_); }
    SemaphoreHandle_t l_;
};
}  // namespace

std::string joinDestinations(const std::vector<std::string> &d)
{
    std::string out;
    for (size_t i = 0; i < d.size(); ++i) {
        if (i) out += '\x1F';  // unit separator: destinations may contain commas
        out += d[i];
    }
    return out;
}

std::vector<std::string> splitDestinations(const std::string &s)
{
    std::vector<std::string> out;
    size_t start = 0;
    while (start <= s.size() && !s.empty()) {
        size_t pos = s.find('\x1F', start);
        out.push_back(s.substr(start, pos == std::string::npos ? std::string::npos : pos - start));
        if (pos == std::string::npos) break;
        start = pos + 1;
    }
    return out.empty() ? kDefaultDest : out;
}

SettingsStore &SettingsStore::get()
{
    static SettingsStore inst;
    return inst;
}

SettingsStore::SettingsStore() { lock_ = xSemaphoreCreateRecursiveMutex(); }

void SettingsStore::load()
{
    Guard g(lock_);
    nvs_handle_t h;
    ESP_ERROR_CHECK(nvs_open(NS, NVS_READWRITE, &h));
    handle_ = h;
    if (getStr("uid").empty()) {
        uint8_t rnd[8];
        esp_fill_random(rnd, sizeof rnd);  // hardware RNG (RF subsystem active => true random)
        char uid[24];
        snprintf(uid, sizeof uid, "DTK-%02X%02X%02X%02X%02X%02X%02X%02X", rnd[0], rnd[1], rnd[2], rnd[3], rnd[4],
                 rnd[5], rnd[6], rnd[7]);
        setStr("uid", uid);
        ESP_LOGI(TAG, "generated device uid %s", uid);
    }
}

std::string SettingsStore::getStr(const char *key, const std::string &def)
{
    Guard g(lock_);
    size_t len = 0;
    if (nvs_get_str(handle_, key, nullptr, &len) != ESP_OK || len == 0) return def;
    std::string v(len, '\0');
    if (nvs_get_str(handle_, key, v.data(), &len) != ESP_OK) return def;
    v.resize(len - 1);
    return v;
}

void SettingsStore::setStr(const char *key, const std::string &v)
{
    Guard g(lock_);
    nvs_set_str(handle_, key, v.c_str());
    nvs_commit(handle_);
}

std::string SettingsStore::deviceUid() { return getStr("uid"); }
std::string SettingsStore::locale() { return getStr("locale", ""); }
void SettingsStore::setLocale(const std::string &l) { setStr("locale", l); }
std::string SettingsStore::wifiSsid() { return getStr("ssid"); }
std::string SettingsStore::wifiPass() { return getStr("pass"); }
void SettingsStore::setWifi(const std::string &ssid, const std::string &pass)
{
    Guard g(lock_);
    setStr("ssid", ssid);
    setStr("pass", pass);
}
std::string SettingsStore::hostUrl() { return getStr("host", CONFIG_DT_DEFAULT_HOST_URL); }
void SettingsStore::setHostUrl(const std::string &url)
{
    std::string u = url;
    while (!u.empty() && (u.back() == '/' || u.back() == ' ')) u.pop_back();
    setStr("host", u);
}

bool SettingsStore::paired() { return !getStr("token").empty(); }
std::string SettingsStore::token() { return getStr("token"); }

void SettingsStore::savePairing(const std::string &token, const KioskConfig &cfg)
{
    Guard g(lock_);
    setStr("token", token);
    saveConfig(cfg);
}

KioskConfig SettingsStore::config()
{
    Guard g(lock_);
    KioskConfig c;
    c.schoolName = getStr("school");
    c.roomNumber = getStr("room");
    c.roomName = getStr("roomname");
    c.roomId = getStr("roomid");
    c.timezone = getStr("tz", "America/Toronto");
    c.posixTz = getStr("ptz", "EST5EDT,M3.2.0,M11.1.0");
    c.destinations = splitDestinations(getStr("dest"));
    uint8_t ld = 0;
    nvs_get_u8(handle_, "lockdown", &ld);
    c.lockdown = ld != 0;
    return c;
}

void SettingsStore::saveConfig(const KioskConfig &c)
{
    Guard g(lock_);
    KioskConfig old = config();
    // Avoid needless flash wear: heartbeats arrive every 30 s with mostly unchanged values.
    if (old.schoolName != c.schoolName) setStr("school", c.schoolName);
    if (old.roomNumber != c.roomNumber) setStr("room", c.roomNumber);
    if (old.roomName != c.roomName) setStr("roomname", c.roomName);
    if (old.roomId != c.roomId && !c.roomId.empty()) setStr("roomid", c.roomId);
    if (old.timezone != c.timezone) setStr("tz", c.timezone);
    if (old.posixTz != c.posixTz) setStr("ptz", c.posixTz);
    if (joinDestinations(old.destinations) != joinDestinations(c.destinations)) setStr("dest", joinDestinations(c.destinations));
    if (old.lockdown != c.lockdown) {
        nvs_set_u8(handle_, "lockdown", c.lockdown ? 1 : 0);
        nvs_commit(handle_);
    }
}

void SettingsStore::clearPairing()
{
    Guard g(lock_);
    for (const char *k : {"token", "school", "room", "roomname", "roomid", "dest", "lockdown"}) nvs_erase_key(handle_, k);
    nvs_commit(handle_);
}

void SettingsStore::factoryReset()
{
    Guard g(lock_);
    nvs_erase_all(handle_);
    nvs_commit(handle_);
    nvs_handle_t q;
    if (nvs_open("queue", NVS_READWRITE, &q) == ESP_OK) {
        nvs_erase_all(q);
        nvs_commit(q);
        nvs_close(q);
    }
}

}  // namespace dt
