// Persistent kiosk settings in NVS (encrypted at rest in the `kiosk-secure` build profile).
#pragma once

#include <string>
#include <vector>
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

namespace dt {

struct KioskConfig {
    std::string schoolName;
    std::string roomNumber;
    std::string roomName;
    std::string roomId;
    std::string timezone;  // IANA, e.g. America/Toronto
    std::string posixTz;   // e.g. EST5EDT,M3.2.0,M11.1.0
    std::vector<std::string> destinations;
    bool lockdown = false;
};

class SettingsStore {
public:
    static SettingsStore &get();
    void load();

    std::string deviceUid();  // generated once from the hardware RNG
    std::string locale();
    void setLocale(const std::string &l);
    std::string wifiSsid();
    std::string wifiPass();
    void setWifi(const std::string &ssid, const std::string &pass);
    std::string hostUrl();
    void setHostUrl(const std::string &url);

    bool paired();
    std::string token();
    void savePairing(const std::string &token, const KioskConfig &cfg);
    KioskConfig config();
    void saveConfig(const KioskConfig &cfg);
    void clearPairing();
    void factoryReset();  // erases everything, including Wi-Fi and the device identity

private:
    SettingsStore();
    std::string getStr(const char *key, const std::string &def = "");
    void setStr(const char *key, const std::string &v);
    SemaphoreHandle_t lock_;
    unsigned handle_ = 0;
};

std::string joinDestinations(const std::vector<std::string> &d);
std::vector<std::string> splitDestinations(const std::string &s);

}  // namespace dt
