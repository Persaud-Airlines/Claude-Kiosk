#include "time_sync.hpp"

#include <cstdlib>
#include <sys/time.h>
#include "config.h"
#include "esp_log.h"
#include "esp_netif_sntp.h"

namespace dt {
namespace {
const char *TAG = "time";
volatile bool s_synced = false;
bool s_started = false;

void on_sync(struct timeval *tv)
{
    s_synced = true;
    ESP_LOGI(TAG, "clock synchronized");
}

bool plausible()
{
    return time(nullptr) > 1735689600;  // 2025-01-01: anything earlier means "never synced"
}
}  // namespace

void TimeSync::start()
{
    if (s_started) return;
    s_started = true;
    esp_sntp_config_t cfg = ESP_NETIF_SNTP_DEFAULT_CONFIG_MULTIPLE(
        3, ESP_SNTP_SERVER_LIST(DT_NTP_PRIMARY, DT_NTP_FALLBACK1, DT_NTP_FALLBACK2));
    cfg.sync_cb = on_sync;
    cfg.smooth_sync = false;
    esp_netif_sntp_init(&cfg);
}

bool TimeSync::synced() { return s_synced || plausible(); }

void TimeSync::setPosixTz(const std::string &posix)
{
    setenv("TZ", posix.empty() ? "UTC0" : posix.c_str(), 1);
    tzset();
}

std::string TimeSync::localClock()
{
    if (!synced()) return "--:--:--";
    time_t now = time(nullptr);
    struct tm t;
    localtime_r(&now, &t);
    char buf[16];
    strftime(buf, sizeof buf, "%I:%M:%S %p", &t);
    return buf[0] == '0' ? std::string(buf + 1) : std::string(buf);
}

std::string TimeSync::utcClock()
{
    if (!synced()) return "--:--:--";
    time_t now = time(nullptr);
    struct tm t;
    gmtime_r(&now, &t);
    char buf[16];
    strftime(buf, sizeof buf, "%H:%M:%S", &t);
    return buf;
}

std::string TimeSync::isoUtcNow()
{
    if (!synced()) return "";
    struct timeval tv;
    gettimeofday(&tv, nullptr);
    struct tm t;
    gmtime_r(&tv.tv_sec, &t);
    char buf[40];
    size_t n = strftime(buf, sizeof buf, "%Y-%m-%dT%H:%M:%S", &t);
    snprintf(buf + n, sizeof buf - n, ".%03ldZ", (long)(tv.tv_usec / 1000));
    return buf;
}

}  // namespace dt
