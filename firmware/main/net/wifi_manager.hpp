#pragma once

#include <string>
#include <vector>

namespace dt {

struct ApInfo {
    std::string ssid;
    int rssi = 0;
    bool secured = false;
};

class WifiManager {
public:
    static WifiManager &get();
    void init();
    /** Blocking scan (~2-3 s). Strongest first, de-duplicated by SSID, hidden SSIDs omitted. */
    std::vector<ApInfo> scan();
    /** Connect and wait for an IP address. Credentials are stored only by the caller on success. */
    bool connect(const std::string &ssid, const std::string &pass, int timeout_ms = 15000);
    void connectAsync(const std::string &ssid, const std::string &pass);
    bool connected() const;
    std::string ip() const;
    int rssi() const;
    std::string ssid() const;

private:
    WifiManager() = default;
};

/** 0..4 signal bars from RSSI. */
int rssiBars(int rssi);

}  // namespace dt
