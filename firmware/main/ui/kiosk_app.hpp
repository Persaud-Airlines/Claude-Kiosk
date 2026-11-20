// Deterministic kiosk state machine + all LVGL screens (800x480 landscape).
#pragma once

#include <string>
#include <vector>
#include "app_bus.hpp"
#include "camera_provider.hpp"
#include "lvgl.h"
#include "settings_store.hpp"

namespace dt {

enum class KioskState {
    BOOT_SPLASH,
    SETUP_WIZARD,
    HOME,
    SIGNOUT_SELECT,
    CAMERA_SCAN,
    CONFIRM_IDENTITY,
    SUCCESS_FEEDBACK,
    MANUAL_ENTRY,  // fallback when the card reader / host is unreachable
};

enum class WizardStep { WELCOME, LANGUAGE, WIFI, WIFI_PASSWORD, WIFI_HIDDEN, WIFI_ADVANCED, PAIRING };

enum class ScanMode { SIGN_OUT, SIGN_IN };

class KioskApp {
public:
    static KioskApp &get();
    /** Must be called with the LVGL lock held. */
    void start(ICameraProvider *cam);

private:
    KioskApp() = default;

    // ---- state machine
    void go(KioskState s);
    void goWizard(WizardStep step);
    void enterHomeOrWizard();

    // ---- screens
    void buildSplash();
    void buildWelcome();
    void buildLanguage();
    void buildWifi();
    void buildWifiPassword();
    void buildWifiHidden();
    void buildWifiAdvanced();
    void buildPairing();
    void buildHome();
    void buildSignoutSelect();
    void buildCameraScan();
    void buildConfirm();
    void buildSuccess();
    void buildManualEntry();
    void buildTopBar();
    void refreshTopBar();
    void showDiagnostics();
    void showPinPad(bool factoryReset);
    void closeModal();
    void toast(const char *text, uint32_t color);

    // ---- helpers
    void setFullscreen(bool full);
    lv_obj_t *backButton(lv_obj_t *parent, lv_event_cb_t cb);
    void renderWifiList();
    void updateWifiStatus(const std::string &text, uint32_t color, bool nextEnabled);
    void stopScanning();

    // ---- deferred navigation (never delete the widget whose callback is running)
    static void applyPending(void *arg);
    KioskState pendingState_ = KioskState::BOOT_SPLASH;
    WizardStep pendingWiz_ = WizardStep::WELCOME;
    bool asyncQueued_ = false;
    void leaveState(KioskState old);

    // ---- timers / messages
    static void onTick(lv_timer_t *t);
    static void onMessages(lv_timer_t *t);
    static void onPreview(lv_timer_t *t);
    void handle(UiMsg &m);

    ICameraProvider *cam_ = nullptr;
    KioskState state_ = KioskState::BOOT_SPLASH;
    WizardStep wiz_ = WizardStep::WELCOME;
    KioskConfig cfg_;

    // flow data
    ScanMode mode_ = ScanMode::SIGN_IN;
    std::string destination_;
    std::string firstName_, lastName_, sessionId_;
    bool manualEntry_ = false;
    bool submitting_ = false;
    bool savedOffline_ = false;
    std::string successTime_;
    uint32_t scanStartedMs_ = 0;
    bool scanHostDown_ = false;

    // wizard data
    std::vector<ApInfo> aps_;
    std::string pendingSsid_;
    bool wifiOk_ = false, hostOk_ = false;
    std::string pairCode_, pairUrl_;
    uint32_t pairExpiresAtMs_ = 0;
    bool pairError_ = false;

    // persistent objects
    lv_obj_t *root_ = nullptr;
    lv_obj_t *topbar_ = nullptr, *tbSchool_ = nullptr, *tbLocal_ = nullptr, *tbUtc_ = nullptr, *tbDot_ = nullptr,
             *tbLockdown_ = nullptr, *tbHotspot_ = nullptr, *tbRoom_ = nullptr;
    lv_obj_t *content_ = nullptr;
    lv_obj_t *modal_ = nullptr;
    lv_obj_t *toast_ = nullptr;
    lv_timer_t *toastTimer_ = nullptr;
    lv_timer_t *stateTimer_ = nullptr;  // splash / success auto-advance
    lv_timer_t *previewTimer_ = nullptr;
    uint16_t previewW_ = 0, previewH_ = 0;
    std::string connectedSsid_, ipText_;

    // per-screen objects (owned by content_, nulled on rebuild)
    lv_obj_t *wifiList_ = nullptr, *wifiStatus_ = nullptr, *wifiNext_ = nullptr;
    lv_obj_t *pairQr_ = nullptr, *pairCodeLbl_ = nullptr, *pairStatus_ = nullptr, *pairExpiry_ = nullptr;
    lv_obj_t *previewImg_ = nullptr, *scanStatus_ = nullptr, *manualBtn_ = nullptr;
    lv_obj_t *confirmBtnRow_ = nullptr, *pinTa_ = nullptr, *pinMsg_ = nullptr;
    lv_obj_t *ta1_ = nullptr, *ta2_ = nullptr, *kb_ = nullptr;
    bool pinForReset_ = false;
    uint32_t pressStartMs_ = 0;
    bool diagFired_ = false;
    std::string lastLocal_, lastUtc_;
};

}  // namespace dt
