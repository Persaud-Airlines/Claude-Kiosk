#include "host_client.hpp"

#include <cstring>
#include "config.h"
#include "cJSON.h"
#include "esp_crt_bundle.h"
#include "esp_http_client.h"
#include "esp_log.h"

extern const char host_ca_pem_start[] asm("_binary_host_ca_pem_start");

namespace dt {
namespace {
const char *TAG = "host";
constexpr size_t kMaxBody = 64 * 1024;

esp_err_t on_http_event(esp_http_client_event_t *evt)
{
    if (evt->event_id == HTTP_EVENT_ON_DATA && evt->user_data) {
        auto *out = static_cast<std::string *>(evt->user_data);
        if (out->size() + evt->data_len <= kMaxBody) out->append(static_cast<const char *>(evt->data), evt->data_len);
    }
    return ESP_OK;
}

std::string str(cJSON *o, const char *k)
{
    cJSON *v = cJSON_GetObjectItemCaseSensitive(o, k);
    return cJSON_IsString(v) && v->valuestring ? v->valuestring : "";
}

bool has_custom_ca() { return strncmp(host_ca_pem_start, "-----BEGIN", 10) == 0; }
}  // namespace

bool parseConfig(const char *json, KioskConfig &out, std::string *token)
{
    cJSON *root = cJSON_Parse(json);
    if (!root) return false;
    out.schoolName = str(root, "school_name");
    out.roomNumber = str(root, "room_number");
    out.roomName = str(root, "room_name");
    std::string rid = str(root, "classroom_id");
    if (!rid.empty()) out.roomId = rid;
    out.timezone = str(root, "timezone");
    out.posixTz = str(root, "posix_tz");
    cJSON *ld = cJSON_GetObjectItem(root, "lockdown_active");
    out.lockdown = cJSON_IsTrue(ld);
    cJSON *dest = cJSON_GetObjectItem(root, "destinations");
    if (cJSON_IsArray(dest)) {
        out.destinations.clear();
        cJSON *d;
        cJSON_ArrayForEach(d, dest)
        {
            if (cJSON_IsString(d) && out.destinations.size() < 6) out.destinations.emplace_back(d->valuestring);
        }
    }
    if (token) *token = str(root, "device_api_token");
    cJSON_Delete(root);
    return !out.roomNumber.empty();
}

HttpResult HostClient::request(const char *method, const std::string &path, const std::string &body,
                               const char *contentType, bool auth, const uint8_t *raw, size_t rawLen, int timeoutMs,
                               const std::string &xName, const std::string &xValue)
{
    HttpResult res;
    std::string base = baseUrl_.empty() ? SettingsStore::get().hostUrl() : baseUrl_;
    std::string url = base + path;
    bool https = url.rfind("https://", 0) == 0;

    esp_http_client_config_t cfg = {};
    cfg.url = url.c_str();
    cfg.timeout_ms = timeoutMs ? timeoutMs : DT_HTTP_TIMEOUT_MS;
    cfg.event_handler = on_http_event;
    cfg.user_data = &res.body;
    cfg.buffer_size = 2048;
    cfg.buffer_size_tx = 2048;
    cfg.keep_alive_enable = false;
    if (https) {
        if (has_custom_ca()) cfg.cert_pem = host_ca_pem_start;  // private on-prem CA
        else cfg.crt_bundle_attach = esp_crt_bundle_attach;     // public CA (Cloudflare Tunnel etc.)
    }
    esp_http_client_handle_t c = esp_http_client_init(&cfg);
    if (!c) return res;

    if (!strcmp(method, "POST")) esp_http_client_set_method(c, HTTP_METHOD_POST);
    else esp_http_client_set_method(c, HTTP_METHOD_GET);
    esp_http_client_set_header(c, "Accept", "application/json");
    esp_http_client_set_header(c, "User-Agent", "DE-TECH-TIVE-Kiosk/" DT_FIRMWARE_VERSION);
    std::string token, uid = SettingsStore::get().deviceUid();
    if (auth) {
        token = SettingsStore::get().token();
        esp_http_client_set_header(c, "X-Device-Token", token.c_str());
        esp_http_client_set_header(c, "X-Device-UID", uid.c_str());
    }
    if (!xName.empty()) esp_http_client_set_header(c, xName.c_str(), xValue.c_str());
    if (raw) {
        esp_http_client_set_header(c, "Content-Type", contentType);
        esp_http_client_set_post_field(c, reinterpret_cast<const char *>(raw), (int)rawLen);
    } else if (!body.empty()) {
        esp_http_client_set_header(c, "Content-Type", contentType);
        esp_http_client_set_post_field(c, body.c_str(), (int)body.size());
    }
    esp_err_t err = esp_http_client_perform(c);
    if (err == ESP_OK) res.status = esp_http_client_get_status_code(c);
    else ESP_LOGW(TAG, "%s %s failed: %s", method, path.c_str(), esp_err_to_name(err));
    esp_http_client_cleanup(c);
    return res;
}

bool HostClient::health(const std::string &baseUrl)
{
    baseUrl_ = baseUrl;
    HttpResult r = request("GET", "/api/health", "", "application/json", false, nullptr, 0, 6000);
    baseUrl_.clear();
    return r.ok() && r.body.find("\"ok\"") != std::string::npos;
}

PairInit HostClient::pairInit()
{
    PairInit p;
    cJSON *b = cJSON_CreateObject();
    cJSON_AddStringToObject(b, "device_uid", SettingsStore::get().deviceUid().c_str());
    cJSON_AddStringToObject(b, "firmware_version", DT_FIRMWARE_VERSION);
    std::string loc = SettingsStore::get().locale();
    if (!loc.empty()) cJSON_AddStringToObject(b, "locale", loc.c_str());
    char *s = cJSON_PrintUnformatted(b);
    HttpResult r = request("POST", "/api/v1/kiosk/pair/init", s, "application/json", false);
    cJSON_free(s);
    cJSON_Delete(b);
    if (!r.ok()) return p;
    cJSON *root = cJSON_Parse(r.body.c_str());
    if (!root) return p;
    p.code = str(root, "pairing_code");
    p.secret = str(root, "pairing_secret");
    p.url = str(root, "pairing_url");
    cJSON *e = cJSON_GetObjectItem(root, "expires_in_seconds");
    if (cJSON_IsNumber(e)) p.expiresIn = e->valueint;
    p.ok = !p.code.empty() && !p.secret.empty();
    cJSON_Delete(root);
    return p;
}

PairStatus HostClient::pairStatus(const std::string &secret)
{
    PairStatus ps;
    HttpResult r = request("GET", "/api/v1/kiosk/pair/status/" + SettingsStore::get().deviceUid(), "",
                           "application/json", false, nullptr, 0, 0, "X-Pairing-Secret", secret);
    if (!r.ok()) {
        ps.status = r.status == 401 ? "expired" : "error";
        return ps;
    }
    cJSON *root = cJSON_Parse(r.body.c_str());
    if (!root) {
        ps.status = "error";
        return ps;
    }
    ps.status = str(root, "status");
    cJSON_Delete(root);
    if (ps.status == "paired") parseConfig(r.body.c_str(), ps.cfg, &ps.token);
    return ps;
}

int HostClient::heartbeat(KioskConfig &cfg, int rssi, const std::string &ip, size_t queueDepth)
{
    cJSON *b = cJSON_CreateObject();
    cJSON_AddStringToObject(b, "firmware_version", DT_FIRMWARE_VERSION);
    cJSON_AddStringToObject(b, "ip_address", ip.c_str());
    if (rssi > -127 && rssi < 0) cJSON_AddNumberToObject(b, "wifi_rssi", rssi);
    cJSON_AddNumberToObject(b, "offline_queue_depth", (double)queueDepth);
    char *s = cJSON_PrintUnformatted(b);
    HttpResult r = request("POST", "/api/v1/kiosk/heartbeat", s);
    cJSON_free(s);
    cJSON_Delete(b);
    if (r.ok()) {
        KioskConfig fresh = cfg;
        if (parseConfig(r.body.c_str(), fresh)) cfg = fresh;
    }
    return r.status;
}

ScanResult HostClient::scanCard(const uint8_t *jpeg, size_t len)
{
    ScanResult s;
    HttpResult r = request("POST", "/api/v1/kiosk/scan-card", "", "image/jpeg", true, jpeg, len, DT_SCAN_TIMEOUT_MS);
    s.status = r.status;
    if (!r.ok()) return s;
    cJSON *root = cJSON_Parse(r.body.c_str());
    if (!root) return s;
    s.ok = true;
    s.detected = cJSON_IsTrue(cJSON_GetObjectItem(root, "detected"));
    s.firstName = str(root, "first_name");
    s.lastName = str(root, "last_name");
    s.sessionId = str(root, "scan_session_id");
    s.reason = str(root, "reason");
    cJSON *c = cJSON_GetObjectItem(root, "confidence");
    if (cJSON_IsNumber(c)) s.confidence = (float)c->valuedouble;
    cJSON_Delete(root);
    return s;
}

HttpResult HostClient::postEvent(const std::string &json) { return request("POST", "/api/v1/kiosk/events", json); }
HttpResult HostClient::postBatch(const std::string &json) { return request("POST", "/api/v1/kiosk/events/batch", json, "application/json", true, nullptr, 0, 20000); }

int HostClient::verifyPin(const std::string &pin)
{
    std::string body = "{\"pin\":\"" + pin + "\"}";  // pin is digits only (validated by the keypad)
    return request("POST", "/api/v1/kiosk/verify-pin", body).status;
}

int HostClient::unpair() { return request("POST", "/api/v1/kiosk/unpair").status; }

}  // namespace dt
