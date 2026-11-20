// HTTPS client for the Master/Host API. Every authenticated call carries X-Device-Token + X-Device-UID.
#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>
#include "settings_store.hpp"

namespace dt {

struct HttpResult {
    int status = 0;  // 0 = transport failure (DNS / TLS / timeout / no Wi-Fi)
    std::string body;
    bool transportOk() const { return status > 0; }
    bool ok() const { return status >= 200 && status < 300; }
};

struct PairInit {
    bool ok = false;
    std::string code, secret, url;
    int expiresIn = 900;
};

struct PairStatus {
    std::string status;  // pending | paired | expired | revoked | error
    std::string token;
    KioskConfig cfg;
};

struct ScanResult {
    bool ok = false;        // transport + HTTP success
    bool detected = false;  // a name was read with enough confidence
    std::string firstName, lastName, sessionId, reason;
    float confidence = 0;
    int status = 0;
};

class HostClient {
public:
    HostClient() = default;
    HttpResult request(const char *method, const std::string &path, const std::string &body = "",
                       const char *contentType = "application/json", bool auth = true,
                       const uint8_t *raw = nullptr, size_t rawLen = 0, int timeoutMs = 0,
                       const std::string &extraHeaderName = "", const std::string &extraHeaderValue = "");

    bool health(const std::string &baseUrl);
    PairInit pairInit();
    PairStatus pairStatus(const std::string &secret);
    /** Returns HTTP status; on 200 fills cfg. 401 => token revoked. */
    int heartbeat(KioskConfig &cfg, int rssi, const std::string &ip, size_t queueDepth);
    ScanResult scanCard(const uint8_t *jpeg, size_t len);
    HttpResult postEvent(const std::string &json);
    HttpResult postBatch(const std::string &json);
    int verifyPin(const std::string &pin);
    int unpair();

private:
    std::string baseUrl_;
};

bool parseConfig(const char *json, KioskConfig &out, std::string *token = nullptr);

}  // namespace dt
