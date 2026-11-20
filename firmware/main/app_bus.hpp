// Message passing between the LVGL (UI) thread and the background workers.
// Workers never touch LVGL objects; they post UiMsg objects that the UI drains on its own thread.
#pragma once

#include <string>
#include <vector>
#include "settings_store.hpp"
#include "wifi_manager.hpp"

namespace dt {

enum class Msg {
    WifiScanDone, WifiConnected, WifiFailed, HostOk, HostFail,
    PairCode, PairDone, PairError,
    ConfigUpdated, Revoked, NetStatus,
    ScanDetected, ScanMiss,
    EventDone, EventQueued, EventRejected,
    PinOk, PinBad, PinOffline,
};

struct UiMsg {
    Msg type;
    std::string a, b, c, d;
    int i = 0;
    float f = 0;
    std::vector<ApInfo> aps;
    KioskConfig cfg;
};

enum class Job {
    ScanWifi, ConnectWifi, CheckHost, StartPairing, StopPairing,
    SubmitEvent, VerifyPin, RePair, FactoryReset,
};

struct JobMsg {
    Job type;
    std::string a, b, c, d, e;  // job-specific string args
    bool flag = false;
};

enum class NetHealth { NoWifi, HostDown, Online };

void bus_init();
void post_ui(UiMsg *m);    // takes ownership
UiMsg *pop_ui();           // caller deletes
void post_job(JobMsg *j);  // takes ownership

/** Shared, lock-free status snapshot (written by workers, read by UI). */
struct NetSnapshot {
    volatile NetHealth health = NetHealth::NoWifi;
    volatile int queueDepth = 0;
    volatile bool cameraConnected = false;
};
NetSnapshot &net_snapshot();

}  // namespace dt
