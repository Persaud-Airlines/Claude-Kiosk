#include "wifi_manager.hpp"

#include <algorithm>
#include <cstring>
#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"

namespace dt {
namespace {
const char *TAG = "wifi";
EventGroupHandle_t s_ev;
constexpr EventBits_t GOT_IP = BIT0, FAILED = BIT1;
esp_netif_t *s_netif;
volatile bool s_want_connected = false;
volatile bool s_scanning = false;
char s_ip[16] = "0.0.0.0";

void on_event(void *, esp_event_base_t base, int32_t id, void *data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        xEventGroupClearBits(s_ev, GOT_IP);
        xEventGroupSetBits(s_ev, FAILED);
        strcpy(s_ip, "0.0.0.0");
        if (s_want_connected && !s_scanning) esp_wifi_connect();  // auto-reconnect (the classroom AP may reboot)
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        auto *e = static_cast<ip_event_got_ip_t *>(data);
        snprintf(s_ip, sizeof s_ip, IPSTR, IP2STR(&e->ip_info.ip));
        ESP_LOGI(TAG, "got ip %s", s_ip);
        xEventGroupClearBits(s_ev, FAILED);
        xEventGroupSetBits(s_ev, GOT_IP);
    }
}
}  // namespace

WifiManager &WifiManager::get()
{
    static WifiManager w;
    return w;
}

int rssiBars(int rssi)
{
    if (rssi >= -55) return 4;
    if (rssi >= -65) return 3;
    if (rssi >= -75) return 2;
    if (rssi >= -85) return 1;
    return 0;
}

void WifiManager::init()
{
    s_ev = xEventGroupCreate();
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    s_netif = esp_netif_create_default_wifi_sta();
    esp_netif_set_hostname(s_netif, "detechtive-kiosk");
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));  // credentials live in our own NVS namespace
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, on_event, nullptr));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, on_event, nullptr));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_start());
    esp_wifi_set_ps(WIFI_PS_NONE);  // lowest latency for a mains-powered kiosk
}

std::vector<ApInfo> WifiManager::scan()
{
    std::vector<ApInfo> out;
    s_scanning = true;
    wifi_scan_config_t sc = {};
    sc.show_hidden = false;
    if (esp_wifi_scan_start(&sc, true) != ESP_OK) {
        s_scanning = false;
        return out;
    }
    uint16_t n = 0;
    esp_wifi_scan_get_ap_num(&n);
    n = std::min<uint16_t>(n, 40);
    std::vector<wifi_ap_record_t> recs(n);
    esp_wifi_scan_get_ap_records(&n, recs.data());
    s_scanning = false;
    for (uint16_t i = 0; i < n; ++i) {
        std::string ssid(reinterpret_cast<const char *>(recs[i].ssid));
        if (ssid.empty()) continue;
        auto it = std::find_if(out.begin(), out.end(), [&](const ApInfo &a) { return a.ssid == ssid; });
        if (it != out.end()) {
            it->rssi = std::max(it->rssi, (int)recs[i].rssi);
            continue;
        }
        out.push_back({ssid, recs[i].rssi, recs[i].authmode != WIFI_AUTH_OPEN});
    }
    std::sort(out.begin(), out.end(), [](const ApInfo &a, const ApInfo &b) { return a.rssi > b.rssi; });
    return out;
}

void WifiManager::connectAsync(const std::string &ssid, const std::string &pass)
{
    wifi_config_t wc = {};
    strncpy(reinterpret_cast<char *>(wc.sta.ssid), ssid.c_str(), sizeof(wc.sta.ssid) - 1);
    strncpy(reinterpret_cast<char *>(wc.sta.password), pass.c_str(), sizeof(wc.sta.password) - 1);
    wc.sta.threshold.authmode = pass.empty() ? WIFI_AUTH_OPEN : WIFI_AUTH_WPA2_PSK;
    wc.sta.pmf_cfg.capable = true;
    wc.sta.scan_method = WIFI_ALL_CHANNEL_SCAN;
    wc.sta.sort_method = WIFI_CONNECT_AP_BY_SIGNAL;
    s_want_connected = false;
    esp_wifi_disconnect();
    xEventGroupClearBits(s_ev, GOT_IP | FAILED);
    esp_wifi_set_config(WIFI_IF_STA, &wc);
    s_want_connected = true;
    esp_wifi_connect();
}

bool WifiManager::connect(const std::string &ssid, const std::string &pass, int timeout_ms)
{
    connectAsync(ssid, pass);
    EventBits_t b = xEventGroupWaitBits(s_ev, GOT_IP, pdFALSE, pdFALSE, pdMS_TO_TICKS(timeout_ms));
    if (!(b & GOT_IP)) {
        s_want_connected = false;
        esp_wifi_disconnect();
        return false;
    }
    return true;
}

bool WifiManager::connected() const { return s_ev && (xEventGroupGetBits(s_ev) & GOT_IP); }
std::string WifiManager::ip() const { return s_ip; }

int WifiManager::rssi() const
{
    wifi_ap_record_t ap;
    return esp_wifi_sta_get_ap_info(&ap) == ESP_OK ? ap.rssi : -127;
}

std::string WifiManager::ssid() const
{
    wifi_ap_record_t ap;
    return esp_wifi_sta_get_ap_info(&ap) == ESP_OK ? std::string(reinterpret_cast<const char *>(ap.ssid)) : "";
}

}  // namespace dt
