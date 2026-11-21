#include "kiosk_app.hpp"

#include <algorithm>
#include <cstdio>
#include <cstring>
#include <strings.h>
#include "config.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "i18n.hpp"
#include "icons.h"
#include "theme.hpp"
#include "time_sync.hpp"
#include "wifi_manager.hpp"
#include "workers.hpp"

namespace dt {
using namespace theme;
namespace {
const char *TAG = "ui";
constexpr lv_coord_t KB_H = 240;  // on-screen keyboard height (4 rows)

lv_color_t C(uint32_t hex) { return lv_color_hex(hex); }

lv_obj_t *box(lv_obj_t *parent, lv_coord_t x, lv_coord_t y, lv_coord_t w, lv_coord_t h, uint32_t bg, lv_coord_t radius = 0)
{
    lv_obj_t *o = lv_obj_create(parent);
    lv_obj_remove_style_all(o);
    lv_obj_set_pos(o, x, y);
    lv_obj_set_size(o, w, h);
    lv_obj_set_style_bg_color(o, C(bg), 0);
    lv_obj_set_style_bg_opa(o, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(o, radius, 0);
    lv_obj_clear_flag(o, LV_OBJ_FLAG_SCROLLABLE);
    return o;
}

lv_obj_t *label(lv_obj_t *parent, const char *text, const lv_font_t *font, uint32_t color = TEXT)
{
    lv_obj_t *l = lv_label_create(parent);
    lv_label_set_text(l, text);
    lv_obj_set_style_text_font(l, font, 0);
    lv_obj_set_style_text_color(l, C(color), 0);
    return l;
}

lv_obj_t *wrapLabel(lv_obj_t *parent, const char *text, const lv_font_t *font, lv_coord_t width, uint32_t color = TEXT,
                    lv_text_align_t align = LV_TEXT_ALIGN_LEFT)
{
    lv_obj_t *l = label(parent, text, font, color);
    lv_label_set_long_mode(l, LV_LABEL_LONG_WRAP);
    lv_obj_set_width(l, width);
    lv_obj_set_style_text_align(l, align, 0);
    return l;
}

/** Solid, high-contrast touch button with centered text (and optional icon above it). */
lv_obj_t *button(lv_obj_t *parent, lv_coord_t x, lv_coord_t y, lv_coord_t w, lv_coord_t h, uint32_t bg,
                 const char *text, const lv_font_t *font, uint32_t fg = TEXT, const char *icon = nullptr,
                 const lv_font_t *iconFont = nullptr)
{
    lv_obj_t *b = lv_btn_create(parent);
    lv_obj_set_pos(b, x, y);
    lv_obj_set_size(b, w, h);
    lv_obj_set_style_bg_color(b, C(bg), 0);
    lv_obj_set_style_bg_opa(b, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(b, 16, 0);
    lv_obj_set_style_shadow_width(b, 0, 0);
    lv_obj_set_style_bg_color(b, lv_color_darken(C(bg), LV_OPA_20), LV_STATE_PRESSED);
    lv_obj_set_style_transform_width(b, -4, LV_STATE_PRESSED);
    lv_obj_set_style_transform_height(b, -4, LV_STATE_PRESSED);
    lv_obj_set_style_bg_opa(b, LV_OPA_40, LV_STATE_DISABLED);
    lv_obj_set_flex_flow(b, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(b, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_row(b, 10, 0);
    if (icon) label(b, icon, iconFont, fg);
    if (text) {
        lv_obj_t *l = label(b, text, font, fg);
        lv_obj_set_style_text_align(l, LV_TEXT_ALIGN_CENTER, 0);
    }
    return b;
}

void onClick(lv_obj_t *obj, lv_event_cb_t cb, void *ud = nullptr) { lv_obj_add_event_cb(obj, cb, LV_EVENT_CLICKED, ud); }

const char *destinationIcon(const std::string &d)
{
    struct M { const char *name, *icon; };
    static const M map[] = {{"washroom", ICON_RESTROOM}, {"restroom", ICON_RESTROOM}, {"bathroom", ICON_RESTROOM},
                            {"office", ICON_BUILDING},   {"library", ICON_BOOK},      {"guidance", ICON_COMPASS},
                            {"water", ICON_DROPLET},     {"other", ICON_ELLIPSIS}};
    for (const auto &m : map)
        if (strcasecmp(m.name, d.c_str()) == 0) return m.icon;
    return ICON_PIN;
}

/** DE-TECH-TIVE emblem: navy shield, cyan outline, magnifying lens — drawn as vectors on an LVGL canvas. */
lv_obj_t *createEmblem(lv_obj_t *parent)
{
    constexpr lv_coord_t W = 140, H = 160;
    static uint8_t *buf = nullptr;
    if (!buf) buf = static_cast<uint8_t *>(heap_caps_malloc(LV_CANVAS_BUF_SIZE_TRUE_COLOR_ALPHA(W, H), MALLOC_CAP_SPIRAM));
    lv_obj_t *cv = lv_canvas_create(parent);
    lv_canvas_set_buffer(cv, buf, W, H, LV_IMG_CF_TRUE_COLOR_ALPHA);
    lv_canvas_fill_bg(cv, C(0x000000), LV_OPA_TRANSP);

    static const lv_point_t shield[] = {{70, 4}, {134, 24}, {134, 80}, {126, 110}, {104, 136}, {70, 156},
                                        {36, 136}, {14, 110}, {6, 80}, {6, 24}};
    lv_draw_rect_dsc_t fill;
    lv_draw_rect_dsc_init(&fill);
    fill.bg_color = C(0x14213D);
    fill.bg_opa = LV_OPA_COVER;
    lv_canvas_draw_polygon(cv, shield, sizeof(shield) / sizeof(shield[0]), &fill);

    lv_draw_line_dsc_t line;
    lv_draw_line_dsc_init(&line);
    line.color = C(ACCENT);
    line.width = 4;
    line.round_start = line.round_end = 1;
    lv_point_t outline[11];
    memcpy(outline, shield, sizeof(shield));
    outline[10] = shield[0];
    lv_canvas_draw_line(cv, outline, 11, &line);

    lv_draw_arc_dsc_t arc;
    lv_draw_arc_dsc_init(&arc);
    arc.color = C(ACCENT);
    arc.width = 7;
    lv_canvas_draw_arc(cv, 64, 70, 26, 0, 360, &arc);

    line.width = 11;
    static const lv_point_t handle[] = {{84, 90}, {108, 114}};
    lv_canvas_draw_line(cv, handle, 2, &line);
    return cv;
}

uint32_t ms() { return lv_tick_get(); }
}  // namespace

KioskApp &KioskApp::get()
{
    static KioskApp app;
    return app;
}

// =========================================================================== lifecycle
void KioskApp::start(ICameraProvider *cam)
{
    cam_ = cam;
    setLangCode(SettingsStore::get().locale());
    cfg_ = SettingsStore::get().config();
    TimeSync::setPosixTz(cfg_.posixTz);

    root_ = lv_scr_act();
    lv_obj_set_style_bg_color(root_, C(BG), 0);
    lv_obj_set_style_bg_opa(root_, LV_OPA_COVER, 0);
    lv_obj_clear_flag(root_, LV_OBJ_FLAG_SCROLLABLE);
    buildTopBar();
    content_ = box(root_, 0, UI_TOPBAR_H, LCD_H_RES, UI_WORK_H, BG);

    lv_timer_create(&KioskApp::onTick, 250, this);
    lv_timer_create(&KioskApp::onMessages, 40, this);
    go(KioskState::BOOT_SPLASH);
}

void KioskApp::go(KioskState s)
{
    pendingState_ = s;
    if (!asyncQueued_) {
        asyncQueued_ = true;
        lv_async_call(&KioskApp::applyPending, this);
    }
}

void KioskApp::goWizard(WizardStep step)
{
    pendingWiz_ = step;
    go(KioskState::SETUP_WIZARD);
}

void KioskApp::leaveState(KioskState old)
{
    if (stateTimer_) {
        lv_timer_del(stateTimer_);
        stateTimer_ = nullptr;
    }
    if (old == KioskState::CAMERA_SCAN && pendingState_ != KioskState::CAMERA_SCAN) stopScanning();
    if (old == KioskState::SETUP_WIZARD && wiz_ == WizardStep::PAIRING &&
        !(pendingState_ == KioskState::SETUP_WIZARD && pendingWiz_ == WizardStep::PAIRING)) {
        post_job(new JobMsg{Job::StopPairing});
    }
}

void KioskApp::applyPending(void *arg)
{
    auto *self = static_cast<KioskApp *>(arg);
    self->asyncQueued_ = false;
    KioskState next = self->pendingState_;
    self->leaveState(self->state_);
    self->state_ = next;
    lv_obj_clean(self->content_);
    self->wifiList_ = self->wifiStatus_ = self->wifiNext_ = nullptr;
    self->pairQr_ = self->pairCodeLbl_ = self->pairStatus_ = self->pairExpiry_ = nullptr;
    self->previewImg_ = self->scanStatus_ = self->manualBtn_ = self->confirmBtnRow_ = nullptr;
    self->ta1_ = self->ta2_ = self->kb_ = nullptr;
    ESP_LOGI(TAG, "state -> %d", (int)next);

    switch (next) {
    case KioskState::BOOT_SPLASH: self->buildSplash(); break;
    case KioskState::SETUP_WIZARD:
        self->wiz_ = self->pendingWiz_;
        self->setFullscreen(true);
        switch (self->wiz_) {
        case WizardStep::WELCOME: self->buildWelcome(); break;
        case WizardStep::LANGUAGE: self->buildLanguage(); break;
        case WizardStep::WIFI: self->buildWifi(); break;
        case WizardStep::WIFI_PASSWORD: self->buildWifiPassword(); break;
        case WizardStep::WIFI_HIDDEN: self->buildWifiHidden(); break;
        case WizardStep::WIFI_ADVANCED: self->buildWifiAdvanced(); break;
        case WizardStep::PAIRING: self->buildPairing(); break;
        }
        break;
    case KioskState::HOME: self->buildHome(); break;
    case KioskState::SIGNOUT_SELECT: self->buildSignoutSelect(); break;
    case KioskState::CAMERA_SCAN: self->buildCameraScan(); break;
    case KioskState::CONFIRM_IDENTITY: self->buildConfirm(); break;
    case KioskState::SUCCESS_FEEDBACK: self->buildSuccess(); break;
    case KioskState::MANUAL_ENTRY: self->buildManualEntry(); break;
    }
}

void KioskApp::enterHomeOrWizard()
{
    if (SettingsStore::get().paired()) go(KioskState::HOME);
    else if (SettingsStore::get().locale().empty()) goWizard(WizardStep::WELCOME);
    else goWizard(WizardStep::WIFI);
}

void KioskApp::setFullscreen(bool full)
{
    if (full) {
        lv_obj_add_flag(topbar_, LV_OBJ_FLAG_HIDDEN);
        lv_obj_set_pos(content_, 0, 0);
        lv_obj_set_size(content_, LCD_H_RES, LCD_V_RES);
    } else {
        lv_obj_clear_flag(topbar_, LV_OBJ_FLAG_HIDDEN);
        lv_obj_set_pos(content_, 0, UI_TOPBAR_H);
        lv_obj_set_size(content_, LCD_H_RES, UI_WORK_H);
        refreshTopBar();
    }
}

lv_obj_t *KioskApp::backButton(lv_obj_t *parent, lv_event_cb_t cb)
{
    lv_obj_t *b = button(parent, 16, 12, 170, 52, SURFACE_HI, nullptr, nullptr);
    lv_obj_set_flex_flow(b, LV_FLEX_FLOW_ROW);
    lv_obj_set_style_pad_column(b, 12, 0);
    label(b, ICON_BACK, &dt_icons_32);  // icon glyph from the icon font, text from the UI font
    label(b, tr(S::Back), &dt_font_bold_28);
    onClick(b, cb);
    return b;
}

// =========================================================================== top bar
void KioskApp::buildTopBar()
{
    topbar_ = box(root_, 0, 0, LCD_H_RES, UI_TOPBAR_H, TOPBAR);
    // Left: [School Name] • Room [#] — the room number is its own label so it is never truncated.
    lv_obj_t *left = lv_obj_create(topbar_);
    lv_obj_remove_style_all(left);
    lv_obj_set_size(left, 520, UI_TOPBAR_H);
    lv_obj_align(left, LV_ALIGN_LEFT_MID, 16, 0);
    lv_obj_set_flex_flow(left, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(left, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_column(left, 10, 0);
    lv_obj_clear_flag(left, LV_OBJ_FLAG_SCROLLABLE | LV_OBJ_FLAG_CLICKABLE);
    tbSchool_ = label(left, "", &dt_font_24);
    lv_label_set_long_mode(tbSchool_, LV_LABEL_LONG_DOT);
    tbLockdown_ = label(left, tr(S::Lockdown), &dt_font_20);
    lv_obj_add_flag(tbLockdown_, LV_OBJ_FLAG_HIDDEN);
    tbRoom_ = label(left, "", &dt_font_bold_28, ACCENT);

    tbDot_ = box(topbar_, 0, 0, 14, 14, STATUS_BAD, LV_RADIUS_CIRCLE);
    lv_obj_align(tbDot_, LV_ALIGN_RIGHT_MID, -232, 0);

    tbLocal_ = label(topbar_, "LOCAL --:--:--", &dt_font_20);
    lv_obj_align(tbLocal_, LV_ALIGN_TOP_RIGHT, -16, 5);
    tbUtc_ = label(topbar_, "UTC --:--:--", &dt_font_16, TEXT_DIM);
    lv_obj_align(tbUtc_, LV_ALIGN_BOTTOM_RIGHT, -16, -5);

    // Hidden 5-second long-press zone over the clocks opens the admin diagnostics modal.
    tbHotspot_ = lv_obj_create(topbar_);
    lv_obj_remove_style_all(tbHotspot_);
    lv_obj_set_size(tbHotspot_, 230, UI_TOPBAR_H);
    lv_obj_align(tbHotspot_, LV_ALIGN_RIGHT_MID, 0, 0);
    lv_obj_add_flag(tbHotspot_, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_event_cb(
        tbHotspot_,
        [](lv_event_t *e) {
            auto &app = KioskApp::get();
            lv_event_code_t code = lv_event_get_code(e);
            if (code == LV_EVENT_PRESSED) {
                app.pressStartMs_ = ms();
                app.diagFired_ = false;
            } else if (code == LV_EVENT_PRESSING && !app.diagFired_ &&
                       lv_tick_elaps(app.pressStartMs_) >= DT_DIAG_LONG_PRESS_MS) {
                app.diagFired_ = true;
                app.showDiagnostics();
            }
        },
        LV_EVENT_ALL, nullptr);
}

void KioskApp::refreshTopBar()
{
    std::string school = (cfg_.schoolName.empty() ? std::string("DE-TECH-TIVE") : cfg_.schoolName) + "  \xE2\x80\xA2";
    std::string room = std::string(tr(S::Room)) + " " + cfg_.roomNumber;
    lv_label_set_text(tbSchool_, school.c_str());
    lv_label_set_text(tbRoom_, room.c_str());
    lv_label_set_text(tbLockdown_, tr(S::Lockdown));
    // School name shrinks (with "…") to whatever the room label leaves free.
    bool ld = cfg_.lockdown;
    lv_obj_update_layout(tbRoom_);
    lv_coord_t free_w = 520 - lv_obj_get_width(tbRoom_) - 10;
    for (lv_obj_t *l : {tbSchool_, tbLockdown_}) {
        lv_label_set_long_mode(l, LV_LABEL_LONG_DOT);
        lv_obj_set_width(l, LV_SIZE_CONTENT);
        lv_obj_update_layout(l);
        if (lv_obj_get_width(l) > free_w) lv_obj_set_width(l, free_w);
    }
    lv_obj_set_style_bg_color(topbar_, C(ld ? RED : TOPBAR), 0);
    lv_obj_set_style_text_color(tbRoom_, C(ld ? TEXT : ACCENT), 0);
    if (ld) {
        lv_obj_clear_flag(tbLockdown_, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(tbSchool_, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_add_flag(tbLockdown_, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(tbSchool_, LV_OBJ_FLAG_HIDDEN);
    }
    NetSnapshot &n = net_snapshot();
    uint32_t dot = n.health == NetHealth::NoWifi ? STATUS_BAD
                   : n.health == NetHealth::HostDown || n.queueDepth > 0 ? STATUS_WARN
                                                                       : STATUS_OK;
    lv_obj_set_style_bg_color(tbDot_, C(dot), 0);
}

void KioskApp::onTick(lv_timer_t *t)
{
    auto *self = static_cast<KioskApp *>(t->user_data);
    std::string local = std::string("LOCAL ") + TimeSync::localClock();
    std::string utc = std::string("UTC ") + TimeSync::utcClock();
    if (local != self->lastLocal_) {
        self->lastLocal_ = local;
        lv_label_set_text(self->tbLocal_, local.c_str());
    }
    if (utc != self->lastUtc_) {
        self->lastUtc_ = utc;
        lv_label_set_text(self->tbUtc_, utc.c_str());
    }
    if (self->state_ == KioskState::CAMERA_SCAN && self->manualBtn_ &&
        (lv_tick_elaps(self->scanStartedMs_) > DT_MANUAL_ENTRY_HINT_MS || self->scanHostDown_)) {
        lv_obj_clear_flag(self->manualBtn_, LV_OBJ_FLAG_HIDDEN);
    }
    if (self->state_ == KioskState::CAMERA_SCAN && self->scanStatus_ && !self->cam_->connected()) {
        lv_label_set_text(self->scanStatus_, tr(S::CameraMissing));
        lv_obj_set_style_text_color(self->scanStatus_, C(STATUS_WARN), 0);
    }
    if (self->pairExpiry_ && self->pairExpiresAtMs_) {
        int32_t left = (int32_t)(self->pairExpiresAtMs_ - ms()) / 1000;
        if (left < 0) left = 0;
        char buf[64];
        snprintf(buf, sizeof buf, "%s %d:%02d", tr(S::PairExpiresIn), (int)(left / 60), (int)(left % 60));
        lv_label_set_text(self->pairExpiry_, buf);
    }
}

// =========================================================================== messages
void KioskApp::onMessages(lv_timer_t *t)
{
    auto *self = static_cast<KioskApp *>(t->user_data);
    for (int i = 0; i < 8; ++i) {
        UiMsg *m = pop_ui();
        if (!m) break;
        self->handle(*m);
        delete m;
    }
}

void KioskApp::handle(UiMsg &m)
{
    bool onWizard = state_ == KioskState::SETUP_WIZARD;
    switch (m.type) {
    case Msg::WifiScanDone:
        aps_ = m.aps;
        if (onWizard && wiz_ == WizardStep::WIFI) renderWifiList();
        break;
    case Msg::WifiConnected:
        wifiOk_ = true;
        ipText_ = m.a;
        connectedSsid_ = m.b;
        if (onWizard && (wiz_ == WizardStep::WIFI_PASSWORD || wiz_ == WizardStep::WIFI_HIDDEN)) goWizard(WizardStep::WIFI);
        else if (onWizard && wiz_ == WizardStep::WIFI) buildWifi();
        break;
    case Msg::WifiFailed:
        wifiOk_ = false;
        if (onWizard && wifiStatus_) updateWifiStatus(tr(S::WifiFailed), STATUS_BAD, false);
        else if (onWizard && pairStatus_) lv_label_set_text(pairStatus_, tr(S::WifiFailed));
        else if (onWizard) toast(tr(S::WifiFailed), RED);
        break;
    case Msg::HostOk:
    case Msg::HostFail: {
        hostOk_ = m.type == Msg::HostOk;
        if (onWizard && wiz_ == WizardStep::WIFI && wifiStatus_) {
            std::string s = std::string(tr(S::WifiConnectedTo)) + " " + connectedSsid_ + "  \xE2\x80\xA2  " + ipText_ + "\n" +
                            (hostOk_ ? tr(S::ServerOk) : tr(S::ServerUnreachable));
            updateWifiStatus(s, hostOk_ ? STATUS_OK : STATUS_WARN, hostOk_);
        }
        break;
    }
    case Msg::PairCode:
        pairCode_ = m.a;
        pairUrl_ = m.b;
        pairExpiresAtMs_ = ms() + (uint32_t)m.i * 1000;
        pairError_ = false;
        if (onWizard && wiz_ == WizardStep::PAIRING && pairCodeLbl_) {
            lv_label_set_text(pairCodeLbl_, pairCode_.c_str());
            lv_qrcode_update(pairQr_, pairUrl_.c_str(), pairUrl_.size());
            lv_label_set_text(pairStatus_, tr(S::PairWaiting));
        }
        break;
    case Msg::PairError:
        pairError_ = true;
        if (pairStatus_) lv_label_set_text(pairStatus_, tr(S::PairError));
        break;
    case Msg::PairDone:
        cfg_ = m.cfg;
        pairCode_.clear();
        pairExpiresAtMs_ = 0;
        go(KioskState::HOME);
        break;
    case Msg::ConfigUpdated: {
        bool destChanged = joinDestinations(cfg_.destinations) != joinDestinations(m.cfg.destinations);
        cfg_ = m.cfg;
        if (!onWizard && state_ != KioskState::BOOT_SPLASH) refreshTopBar();
        if (destChanged && state_ == KioskState::SIGNOUT_SELECT) go(KioskState::SIGNOUT_SELECT);
        break;
    }
    case Msg::NetStatus:
        if (!onWizard && state_ != KioskState::BOOT_SPLASH) refreshTopBar();
        break;
    case Msg::Revoked:
        cfg_ = KioskConfig();
        closeModal();
        toast(tr(S::DeviceRevoked), RED);
        goWizard(WizardStep::PAIRING);
        break;
    case Msg::ScanDetected:
        if (state_ != KioskState::CAMERA_SCAN) break;
        firstName_ = m.a;
        lastName_ = m.b;
        sessionId_ = m.c;
        manualEntry_ = false;
        go(KioskState::CONFIRM_IDENTITY);
        break;
    case Msg::ScanMiss:
        if (state_ != KioskState::CAMERA_SCAN || !scanStatus_) break;
        scanHostDown_ = m.i == -1;
        if (scanHostDown_) {
            lv_label_set_text(scanStatus_, tr(S::ServerOfflineScan));
            lv_obj_set_style_text_color(scanStatus_, C(STATUS_WARN), 0);
        } else {
            lv_label_set_text(scanStatus_, m.a == "image_too_blurry" ? tr(S::HoldStill) : tr(S::Scanning));
            lv_obj_set_style_text_color(scanStatus_, C(TEXT_DIM), 0);
        }
        break;
    case Msg::EventDone:
        submitting_ = false;
        savedOffline_ = false;
        successTime_ = m.a.empty() ? TimeSync::localClock() : m.a;
        go(KioskState::SUCCESS_FEEDBACK);
        break;
    case Msg::EventQueued:
        submitting_ = false;
        savedOffline_ = true;
        successTime_ = m.a;
        go(KioskState::SUCCESS_FEEDBACK);
        break;
    case Msg::EventRejected:
        submitting_ = false;
        toast(tr(S::ErrorTryAgain), RED);
        go(KioskState::HOME);
        break;
    case Msg::PinOk:
        if (pinForReset_) {
            post_job(new JobMsg{Job::FactoryReset});  // erases NVS and restarts
        } else {
            post_job(new JobMsg{Job::RePair});
            cfg_ = KioskConfig();
            closeModal();
            goWizard(WizardStep::PAIRING);
        }
        break;
    case Msg::PinBad:
        if (pinMsg_) lv_label_set_text(pinMsg_, tr(S::PinWrong));
        if (pinTa_) lv_textarea_set_text(pinTa_, "");
        break;
    case Msg::PinOffline:
        if (pinMsg_) lv_label_set_text(pinMsg_, tr(S::PinOffline));
        break;
    }
}

// =========================================================================== splash
void KioskApp::buildSplash()
{
    setFullscreen(true);
    lv_obj_t *em = createEmblem(content_);
    lv_obj_align(em, LV_ALIGN_TOP_MID, 0, 36);

    lv_obj_t *t1 = label(content_, "DE-TECH-TIVE", &dt_font_bold_56);
    lv_obj_align(t1, LV_ALIGN_TOP_MID, 0, 206);
    lv_obj_t *t2 = label(content_, "TECHNOLOGIES Inc", &dt_font_bold_28, ACCENT);
    lv_obj_set_style_text_letter_space(t2, 6, 0);
    lv_obj_align(t2, LV_ALIGN_TOP_MID, 0, 272);
    lv_obj_t *t3 = label(content_, tr(S::Subtitle), &dt_font_20, TEXT_DIM);
    lv_obj_align(t3, LV_ALIGN_TOP_MID, 0, 318);

    lv_obj_t *bar = lv_bar_create(content_);
    lv_obj_set_size(bar, 420, 10);
    lv_obj_align(bar, LV_ALIGN_TOP_MID, 0, 372);
    lv_obj_set_style_bg_color(bar, C(SURFACE_HI), LV_PART_MAIN);
    lv_obj_set_style_bg_color(bar, C(ACCENT), LV_PART_INDICATOR);
    lv_bar_set_range(bar, 0, 100);
    lv_anim_t a;
    lv_anim_init(&a);
    lv_anim_set_var(&a, bar);
    lv_anim_set_values(&a, 0, 100);
    lv_anim_set_time(&a, DT_SPLASH_MS - 200);
    lv_anim_set_path_cb(&a, lv_anim_path_ease_in_out);
    lv_anim_set_exec_cb(&a, [](void *obj, int32_t v) { lv_bar_set_value(static_cast<lv_obj_t *>(obj), v, LV_ANIM_OFF); });
    lv_anim_start(&a);

    lv_obj_t *init = label(content_, tr(S::Initializing), &dt_font_16, TEXT_DIM);
    lv_obj_align(init, LV_ALIGN_TOP_MID, -150, 394);
    lv_obj_t *ver = label(content_, "v" DT_FIRMWARE_VERSION, &dt_font_16, TEXT_DIM);
    lv_obj_align(ver, LV_ALIGN_TOP_MID, 180, 394);

    stateTimer_ = lv_timer_create(
        [](lv_timer_t *t) {
            auto *self = static_cast<KioskApp *>(t->user_data);
            self->stateTimer_ = nullptr;
            lv_timer_del(t);
            self->enterHomeOrWizard();
        },
        DT_SPLASH_MS, this);
}

// =========================================================================== wizard
void KioskApp::buildWelcome()
{
    lv_obj_t *em = createEmblem(content_);
    lv_obj_align(em, LV_ALIGN_TOP_MID, 0, 24);
    lv_obj_t *t = wrapLabel(content_, tr(S::WelcomeTitle), &dt_font_bold_40, 720, TEXT, LV_TEXT_ALIGN_CENTER);
    lv_obj_align(t, LV_ALIGN_TOP_MID, 0, 196);
    lv_obj_t *b = wrapLabel(content_, tr(S::WelcomeBody), &dt_font_20, 640, TEXT_DIM, LV_TEXT_ALIGN_CENTER);
    lv_obj_align(b, LV_ALIGN_TOP_MID, 0, 300);
    lv_obj_t *go = button(content_, 0, 0, 360, 72, PRIMARY, tr(S::GetStarted), &dt_font_bold_28);
    lv_obj_align(go, LV_ALIGN_BOTTOM_MID, 0, -20);
    onClick(go, [](lv_event_t *) { KioskApp::get().goWizard(WizardStep::LANGUAGE); });
}

void KioskApp::buildLanguage()
{
    lv_obj_t *t = label(content_, tr(S::ChooseLanguage), &dt_font_bold_40);
    lv_obj_align(t, LV_ALIGN_TOP_MID, 0, 40);
    struct L { const char *code, *abbr, *name; };
    static const L langs[] = {{"en", "EN", "English"}, {"fr", "FR", "Français"}, {"es", "ES", "Español"}};
    for (int i = 0; i < 3; ++i) {
        lv_obj_t *card = button(content_, 40 + i * 248, 140, 224, 240, SURFACE, langs[i].abbr, &dt_font_bold_56);
        lv_obj_set_style_border_width(card, 3, 0);
        lv_obj_set_style_border_color(card, C(SURFACE_HI), 0);
        label(card, langs[i].name, &dt_font_bold_28, TEXT_DIM);
        onClick(
            card,
            [](lv_event_t *e) {
                const L *l = static_cast<const L *>(lv_event_get_user_data(e));
                SettingsStore::get().setLocale(l->code);
                setLangCode(l->code);
                KioskApp::get().goWizard(WizardStep::WIFI);
            },
            (void *)&langs[i]);
    }
}

void KioskApp::updateWifiStatus(const std::string &text, uint32_t color, bool nextEnabled)
{
    if (!wifiStatus_) return;
    lv_label_set_text(wifiStatus_, text.c_str());
    lv_obj_set_style_text_color(wifiStatus_, C(color), 0);
    if (wifiNext_) {
        if (nextEnabled) lv_obj_clear_state(wifiNext_, LV_STATE_DISABLED);
        else lv_obj_add_state(wifiNext_, LV_STATE_DISABLED);
    }
}

void KioskApp::buildWifi()
{
    lv_obj_clean(content_);
    wifiList_ = wifiStatus_ = wifiNext_ = nullptr;
    lv_obj_t *t = label(content_, tr(S::WifiTitle), &dt_font_bold_40);
    lv_obj_set_pos(t, 24, 16);

    lv_obj_t *gear = button(content_, 716, 12, 64, 56, SURFACE_HI, nullptr, nullptr, TEXT, ICON_GEAR, &dt_icons_32);
    onClick(gear, [](lv_event_t *) { KioskApp::get().goWizard(WizardStep::WIFI_ADVANCED); });
    lv_obj_t *rescan = button(content_, 520, 12, 184, 56, SURFACE_HI, nullptr, nullptr);
    lv_obj_set_flex_flow(rescan, LV_FLEX_FLOW_ROW);
    lv_obj_set_style_pad_column(rescan, 10, 0);
    label(rescan, ICON_RETAKE, &dt_icons_32);
    label(rescan, tr(S::WifiRescan), &dt_font_24);
    onClick(rescan, [](lv_event_t *) {
        auto &app = KioskApp::get();
        app.aps_.clear();
        app.renderWifiList();
        post_job(new JobMsg{Job::ScanWifi});
    });

    wifiList_ = lv_obj_create(content_);
    lv_obj_set_pos(wifiList_, 24, 80);
    lv_obj_set_size(wifiList_, 752, 292);
    lv_obj_set_style_bg_color(wifiList_, C(SURFACE), 0);
    lv_obj_set_style_border_width(wifiList_, 0, 0);
    lv_obj_set_style_radius(wifiList_, 14, 0);
    lv_obj_set_style_pad_all(wifiList_, 8, 0);
    lv_obj_set_style_pad_row(wifiList_, 6, 0);
    lv_obj_set_flex_flow(wifiList_, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_scroll_dir(wifiList_, LV_DIR_VER);

    wifiStatus_ = wrapLabel(content_, "", &dt_font_20, 540, TEXT_DIM);
    lv_obj_set_pos(wifiStatus_, 24, 384);
    wifiNext_ = button(content_, 592, 392, 184, 72, PRIMARY, tr(S::Next), &dt_font_bold_28);
    lv_obj_add_state(wifiNext_, LV_STATE_DISABLED);
    onClick(wifiNext_, [](lv_event_t *) { KioskApp::get().goWizard(WizardStep::PAIRING); });

    renderWifiList();
    if (WifiManager::get().connected()) {
        wifiOk_ = true;
        connectedSsid_ = WifiManager::get().ssid();
        ipText_ = WifiManager::get().ip();
        std::string s = std::string(tr(S::WifiConnectedTo)) + " " + connectedSsid_ + "  \xE2\x80\xA2  " + ipText_ + "  \xE2\x80\xA2  " +
                        std::to_string(WifiManager::get().rssi()) + " dBm\n" + tr(S::CheckingServer);
        updateWifiStatus(s, STATUS_OK, false);
        post_job(new JobMsg{Job::CheckHost});
    }
    if (aps_.empty()) post_job(new JobMsg{Job::ScanWifi});
}

void KioskApp::renderWifiList()
{
    if (!wifiList_) return;
    lv_obj_clean(wifiList_);
    if (aps_.empty()) {
        lv_obj_t *l = label(wifiList_, tr(S::WifiScanning), &dt_font_24, TEXT_DIM);
        lv_obj_set_style_pad_all(l, 12, 0);
    }
    for (size_t i = 0; i < aps_.size(); ++i) {
        const ApInfo &ap = aps_[i];
        lv_obj_t *row = lv_btn_create(wifiList_);
        lv_obj_set_size(row, lv_pct(100), 60);
        lv_obj_set_style_bg_color(row, C(SURFACE_HI), 0);
        lv_obj_set_style_shadow_width(row, 0, 0);
        lv_obj_set_style_radius(row, 10, 0);
        lv_obj_set_flex_flow(row, LV_FLEX_FLOW_ROW);
        lv_obj_set_flex_align(row, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
        lv_obj_set_style_pad_column(row, 16, 0);
        int bars = rssiBars(ap.rssi);
        label(row, ICON_WIFI, &dt_icons_32, bars >= 3 ? STATUS_OK : bars == 2 ? STATUS_WARN : STATUS_BAD);
        lv_obj_t *name = label(row, ap.ssid.c_str(), &dt_font_24);
        lv_label_set_long_mode(name, LV_LABEL_LONG_DOT);
        lv_obj_set_flex_grow(name, 1);
        char sig[24];
        snprintf(sig, sizeof sig, "%s %d dBm", bars >= 4 ? "||||" : bars == 3 ? "|||." : bars == 2 ? "||.." : "|...", ap.rssi);
        label(row, sig, &dt_font_16, TEXT_DIM);
        if (ap.secured) label(row, ICON_LOCK, &dt_icons_32, TEXT_DIM);
        onClick(
            row,
            [](lv_event_t *e) {
                auto &app = KioskApp::get();
                size_t idx = (size_t)(intptr_t)lv_event_get_user_data(e);
                if (idx >= app.aps_.size()) return;
                app.pendingSsid_ = app.aps_[idx].ssid;
                if (app.aps_[idx].secured) app.goWizard(WizardStep::WIFI_PASSWORD);
                else {
                    post_job(new JobMsg{Job::ConnectWifi, app.pendingSsid_, ""});
                    app.updateWifiStatus(tr(S::WifiConnecting), TEXT_DIM, false);
                }
            },
            (void *)(intptr_t)i);
    }
    lv_obj_t *hidden = lv_btn_create(wifiList_);
    lv_obj_set_size(hidden, lv_pct(100), 56);
    lv_obj_set_style_bg_color(hidden, C(SURFACE), 0);
    lv_obj_set_style_shadow_width(hidden, 0, 0);
    label(hidden, tr(S::WifiHidden), &dt_font_24, ACCENT);
    onClick(hidden, [](lv_event_t *) { KioskApp::get().goWizard(WizardStep::WIFI_HIDDEN); });
}

static void attachKeyboard(lv_obj_t *kb, lv_obj_t *ta)
{
    lv_keyboard_set_textarea(kb, ta);
    lv_obj_add_event_cb(
        ta, [](lv_event_t *e) { lv_keyboard_set_textarea(static_cast<lv_obj_t *>(lv_event_get_user_data(e)), lv_event_get_target(e)); },
        LV_EVENT_FOCUSED, kb);
}

static lv_obj_t *textArea(lv_obj_t *parent, lv_coord_t x, lv_coord_t y, lv_coord_t w, const char *placeholder, bool password)
{
    lv_obj_t *ta = lv_textarea_create(parent);
    lv_obj_set_pos(ta, x, y);
    lv_obj_set_size(ta, w, 60);
    lv_textarea_set_one_line(ta, true);
    lv_textarea_set_password_mode(ta, password);
    lv_textarea_set_placeholder_text(ta, placeholder);
    lv_textarea_set_max_length(ta, 96);
    lv_obj_set_style_text_font(ta, &dt_font_24, 0);
    lv_obj_set_style_bg_color(ta, C(SURFACE), 0);
    lv_obj_set_style_text_color(ta, C(TEXT), 0);
    lv_obj_set_style_border_color(ta, C(ACCENT), LV_STATE_FOCUSED);
    return ta;
}

// Keyboards are pinned to the bottom edge with a fixed height so all four rows stay on screen.
static lv_obj_t *keyboard(lv_obj_t *parent, lv_coord_t /*unused*/)
{
    lv_obj_t *kb = lv_keyboard_create(parent);
    lv_obj_set_size(kb, LCD_H_RES, KB_H);
    lv_obj_align(kb, LV_ALIGN_BOTTOM_MID, 0, 0);
    lv_obj_set_style_text_font(kb, &lv_font_montserrat_24, LV_PART_ITEMS);  // keyboard uses LV_SYMBOL_* glyphs
    return kb;
}

void KioskApp::buildWifiPassword()
{
    backButton(content_, [](lv_event_t *) { KioskApp::get().goWizard(WizardStep::WIFI); });
    std::string title = std::string(tr(S::WifiPasswordFor)) + " \"" + pendingSsid_ + "\"";
    lv_obj_t *t = label(content_, title.c_str(), &dt_font_bold_28);
    lv_label_set_long_mode(t, LV_LABEL_LONG_DOT);
    lv_obj_set_width(t, 580);
    lv_obj_set_pos(t, 204, 24);
    ta1_ = textArea(content_, 16, 80, 560, tr(S::WifiPassword), true);
    lv_obj_t *show = button(content_, 588, 80, 60, 60, SURFACE_HI, nullptr, nullptr, TEXT, LV_SYMBOL_EYE_OPEN, &lv_font_montserrat_24);
    onClick(show, [](lv_event_t *) {
        auto &a = KioskApp::get();
        lv_textarea_set_password_mode(a.ta1_, !lv_textarea_get_password_mode(a.ta1_));
    });
    lv_obj_t *connect = button(content_, 660, 80, 124, 60, PRIMARY, tr(S::WifiConnect), &dt_font_20);
    wifiStatus_ = label(content_, "", &dt_font_20, TEXT_DIM);
    lv_obj_set_pos(wifiStatus_, 16, 150);
    kb_ = keyboard(content_, 184);
    attachKeyboard(kb_, ta1_);
    auto doConnect = [](lv_event_t *) {
        auto &a = KioskApp::get();
        std::string pass = lv_textarea_get_text(a.ta1_);
        lv_label_set_text(a.wifiStatus_, tr(S::WifiConnecting));
        lv_obj_set_style_text_color(a.wifiStatus_, C(TEXT_DIM), 0);
        post_job(new JobMsg{Job::ConnectWifi, a.pendingSsid_, pass});
    };
    onClick(connect, doConnect);
    lv_obj_add_event_cb(kb_, doConnect, LV_EVENT_READY, nullptr);
}

void KioskApp::buildWifiHidden()
{
    backButton(content_, [](lv_event_t *) { KioskApp::get().goWizard(WizardStep::WIFI); });
    lv_obj_t *t = label(content_, tr(S::WifiHidden), &dt_font_bold_28);
    lv_obj_set_pos(t, 204, 24);
    ta1_ = textArea(content_, 16, 80, 330, tr(S::WifiSsid), false);
    ta2_ = textArea(content_, 356, 80, 300, tr(S::WifiPassword), true);
    lv_obj_t *connect = button(content_, 666, 80, 118, 60, PRIMARY, tr(S::WifiConnect), &dt_font_20);
    wifiStatus_ = label(content_, "", &dt_font_20, TEXT_DIM);
    lv_obj_set_pos(wifiStatus_, 16, 150);
    kb_ = keyboard(content_, 184);
    attachKeyboard(kb_, ta1_);
    lv_obj_add_event_cb(ta2_, [](lv_event_t *e) { lv_keyboard_set_textarea(KioskApp::get().kb_, lv_event_get_target(e)); }, LV_EVENT_FOCUSED, nullptr);
    auto doConnect = [](lv_event_t *) {
        auto &a = KioskApp::get();
        a.pendingSsid_ = lv_textarea_get_text(a.ta1_);
        if (a.pendingSsid_.empty()) return;
        lv_label_set_text(a.wifiStatus_, tr(S::WifiConnecting));
        post_job(new JobMsg{Job::ConnectWifi, a.pendingSsid_, lv_textarea_get_text(a.ta2_)});
    };
    onClick(connect, doConnect);
    lv_obj_add_event_cb(kb_, doConnect, LV_EVENT_READY, nullptr);
}

void KioskApp::buildWifiAdvanced()
{
    backButton(content_, [](lv_event_t *) { KioskApp::get().goWizard(WizardStep::WIFI); });
    lv_obj_t *t = label(content_, tr(S::Advanced), &dt_font_bold_28);
    lv_obj_set_pos(t, 204, 24);
    lv_obj_t *l = label(content_, tr(S::HostUrl), &dt_font_16, TEXT_DIM);
    lv_obj_set_pos(l, 16, 76);
    ta1_ = textArea(content_, 16, 100, 600, "https://", false);
    lv_textarea_set_text(ta1_, SettingsStore::get().hostUrl().c_str());
    lv_textarea_set_max_length(ta1_, 200);
    lv_obj_t *save = button(content_, 628, 100, 156, 60, PRIMARY, tr(S::Save), &dt_font_20);
    kb_ = keyboard(content_, 184);
    attachKeyboard(kb_, ta1_);
    auto doSave = [](lv_event_t *) {
        auto &a = KioskApp::get();
        std::string url = lv_textarea_get_text(a.ta1_);
        if (url.rfind("http://", 0) != 0 && url.rfind("https://", 0) != 0) url = "https://" + url;
        SettingsStore::get().setHostUrl(url);
        a.goWizard(WizardStep::WIFI);  // WIFI screen re-checks the server when connected
    };
    onClick(save, doSave);
    lv_obj_add_event_cb(kb_, doSave, LV_EVENT_READY, nullptr);
}

void KioskApp::buildPairing()
{
    lv_obj_t *t = label(content_, tr(S::PairTitle), &dt_font_bold_40);
    lv_obj_set_pos(t, 32, 20);
    lv_obj_t *qrFrame = box(content_, 32, 90, 296, 296, 0xFFFFFF, 16);
    pairQr_ = lv_qrcode_create(qrFrame, 264, C(0x000000), C(0xFFFFFF));
    lv_obj_center(pairQr_);

    lv_obj_t *body = wrapLabel(content_, tr(S::PairBody), &dt_font_20, 420, TEXT_DIM);
    lv_obj_set_pos(body, 356, 92);
    pairCodeLbl_ = label(content_, pairCode_.empty() ? "- - - -" : pairCode_.c_str(), &dt_font_code_64);
    lv_obj_set_pos(pairCodeLbl_, 352, 200);
    pairStatus_ = wrapLabel(content_, pairError_ ? tr(S::PairError) : tr(S::PairWaiting), &dt_font_24, 420, ACCENT);
    lv_obj_set_pos(pairStatus_, 356, 300);
    pairExpiry_ = label(content_, "", &dt_font_16, TEXT_DIM);
    lv_obj_set_pos(pairExpiry_, 356, 352);

    lv_obj_t *spinner = lv_spinner_create(content_, 1000, 60);
    lv_obj_set_size(spinner, 36, 36);
    lv_obj_set_pos(spinner, 740, 300);
    lv_obj_set_style_arc_color(spinner, C(ACCENT), LV_PART_INDICATOR);

    lv_obj_t *back = button(content_, 32, 404, 220, 60, SURFACE_HI, nullptr, nullptr);
    lv_obj_set_flex_flow(back, LV_FLEX_FLOW_ROW);
    lv_obj_set_style_pad_column(back, 10, 0);
    label(back, ICON_WIFI, &dt_icons_32);
    label(back, tr(S::WifiTitle), &dt_font_20);
    onClick(back, [](lv_event_t *) { KioskApp::get().goWizard(WizardStep::WIFI); });

    if (!pairCode_.empty() && !pairUrl_.empty()) lv_qrcode_update(pairQr_, pairUrl_.c_str(), pairUrl_.size());
    post_job(new JobMsg{Job::StartPairing});
}

// =========================================================================== operational screens
void KioskApp::buildHome()
{
    setFullscreen(false);
    lv_obj_t *out = button(content_, UI_PAD, UI_PAD, 376, 392, SIGN_OUT, tr(S::SignOut), &dt_font_bold_56, TEXT,
                           ICON_SIGN_OUT, &dt_icons_120);
    lv_obj_t *in = button(content_, UI_PAD * 2 + 376, UI_PAD, 376, 392, SIGN_IN, tr(S::SignIn), &dt_font_bold_56, TEXT,
                          ICON_SIGN_IN, &dt_icons_120);
    lv_obj_set_style_radius(out, 24, 0);
    lv_obj_set_style_radius(in, 24, 0);
    if (cfg_.lockdown) {
        lv_obj_set_style_border_width(in, 8, 0);
        lv_obj_set_style_border_color(in, C(0xFFFFFF), 0);
    }
    onClick(out, [](lv_event_t *) {
        auto &a = KioskApp::get();
        a.mode_ = ScanMode::SIGN_OUT;
        a.go(KioskState::SIGNOUT_SELECT);
    });
    onClick(in, [](lv_event_t *) {
        auto &a = KioskApp::get();
        a.mode_ = ScanMode::SIGN_IN;
        a.destination_.clear();
        a.go(KioskState::CAMERA_SCAN);
    });
}

void KioskApp::buildSignoutSelect()
{
    setFullscreen(false);
    backButton(content_, [](lv_event_t *) { KioskApp::get().go(KioskState::HOME); });
    lv_obj_t *t = label(content_, tr(S::WhereGoing), &dt_font_bold_40);
    lv_obj_align(t, LV_ALIGN_TOP_MID, 90, 14);
    const auto &dest = cfg_.destinations;
    const lv_coord_t w = 245, h = 150;
    for (size_t i = 0; i < dest.size() && i < 6; ++i) {
        lv_coord_t x = UI_PAD + (lv_coord_t)(i % 3) * (w + UI_PAD);
        lv_coord_t y = 84 + (lv_coord_t)(i / 3) * (h + UI_PAD);
        std::string shown = trDestination(dest[i]);
        lv_obj_t *card = button(content_, x, y, w, h, SURFACE, shown.c_str(), &dt_font_bold_28, TEXT,
                                destinationIcon(dest[i]), &dt_icons_56);
        lv_obj_set_style_border_width(card, 3, 0);
        lv_obj_set_style_border_color(card, C(SIGN_OUT), 0);
        lv_obj_t *icon = lv_obj_get_child(card, 0);
        lv_obj_set_style_text_color(icon, C(SIGN_OUT), 0);
        onClick(
            card,
            [](lv_event_t *e) {
                auto &a = KioskApp::get();
                size_t idx = (size_t)(intptr_t)lv_event_get_user_data(e);
                if (idx >= a.cfg_.destinations.size()) return;
                a.destination_ = a.cfg_.destinations[idx];  // send the school's configured name, not the translation
                a.go(KioskState::CAMERA_SCAN);
            },
            (void *)(intptr_t)i);
    }
}

void KioskApp::stopScanning()
{
    scanner_set_active(false);
    PreviewDecoder::get().setActive(false);
    if (previewTimer_) {
        lv_timer_del(previewTimer_);
        previewTimer_ = nullptr;
    }
}

void KioskApp::buildCameraScan()
{
    setFullscreen(false);
    backButton(content_, [](lv_event_t *) {
        auto &a = KioskApp::get();
        a.go(a.mode_ == ScanMode::SIGN_OUT ? KioskState::SIGNOUT_SELECT : KioskState::HOME);
    });
    std::string modeText = mode_ == ScanMode::SIGN_OUT
                               ? std::string(tr(S::SigningOutTo)) + "  " LV_SYMBOL_RIGHT "  " + trDestination(destination_)
                               : std::string(tr(S::SigningInTo)) + "  " LV_SYMBOL_RIGHT "  " + tr(S::Room) + " " + cfg_.roomNumber;
    lv_obj_t *m = label(content_, modeText.c_str(), &dt_font_bold_28, mode_ == ScanMode::SIGN_OUT ? SIGN_OUT : 0x34D399);
    lv_obj_align(m, LV_ALIGN_TOP_RIGHT, -UI_PAD, 22);

    lv_obj_t *banner = wrapLabel(content_, tr(S::PresentCard), &dt_font_24, 600, TEXT, LV_TEXT_ALIGN_CENTER);
    lv_obj_align(banner, LV_ALIGN_TOP_MID, 0, 74);

    lv_obj_t *vp = box(content_, (LCD_H_RES - UI_PREVIEW_W) / 2, 110, UI_PREVIEW_W, UI_PREVIEW_H, 0x000000, 12);
    lv_obj_set_style_clip_corner(vp, true, 0);
    previewImg_ = lv_img_create(vp);
    lv_obj_center(previewImg_);
    previewW_ = previewH_ = 0;

    // Alignment overlay: thin guide rectangle + bright cyan/green corner brackets
    lv_obj_t *guide = lv_obj_create(vp);
    lv_obj_remove_style_all(guide);
    lv_obj_set_size(guide, UI_PREVIEW_W - 48, UI_PREVIEW_H - 40);
    lv_obj_center(guide);
    lv_obj_set_style_border_width(guide, 2, 0);
    lv_obj_set_style_border_color(guide, C(ACCENT), 0);
    lv_obj_set_style_border_opa(guide, LV_OPA_50, 0);
    lv_obj_set_style_radius(guide, 10, 0);
    const lv_coord_t L = 46, Tk = 7, gx = 24, gy = 20, gw = UI_PREVIEW_W - 48, gh = UI_PREVIEW_H - 40;
    struct Bar { lv_coord_t x, y, w, h; };
    const Bar bars[8] = {
        {gx, gy, L, Tk},                     {gx, gy, Tk, L},                       // top-left
        {gx + gw - L, gy, L, Tk},            {gx + gw - Tk, gy, Tk, L},             // top-right
        {gx, gy + gh - Tk, L, Tk},           {gx, gy + gh - L, Tk, L},              // bottom-left
        {gx + gw - L, gy + gh - Tk, L, Tk},  {gx + gw - Tk, gy + gh - L, Tk, L},    // bottom-right
    };
    for (int i = 0; i < 8; ++i) box(vp, bars[i].x, bars[i].y, bars[i].w, bars[i].h, (i / 2) % 3 == 0 ? ACCENT : 0x4ADE80, 3);

    lv_obj_t *hintIcon = label(content_, ICON_ID_CARD, &dt_icons_56, ACCENT);
    lv_obj_set_pos(hintIcon, 52, 170);
    lv_obj_t *hint = wrapLabel(content_, tr(S::HoldStill), &dt_font_16, 150, TEXT_DIM, LV_TEXT_ALIGN_CENTER);
    lv_obj_set_pos(hint, 15, 240);

    scanStatus_ = wrapLabel(content_, cam_->connected() ? tr(S::Scanning) : tr(S::CameraMissing), &dt_font_20,
                            UI_PREVIEW_W, cam_->connected() ? TEXT_DIM : STATUS_WARN, LV_TEXT_ALIGN_CENTER);
    lv_obj_align(scanStatus_, LV_ALIGN_TOP_MID, 0, 388);

    manualBtn_ = button(content_, 636, 290, 148, 96, SURFACE_HI, tr(S::TypeName), &dt_font_20, TEXT, ICON_KEYBOARD, &dt_icons_32);
    lv_obj_add_flag(manualBtn_, LV_OBJ_FLAG_HIDDEN);
    onClick(manualBtn_, [](lv_event_t *) { KioskApp::get().go(KioskState::MANUAL_ENTRY); });

    scanStartedMs_ = ms();
    scanHostDown_ = net_snapshot().health != NetHealth::Online;
    PreviewDecoder::get().setActive(true);
    scanner_set_active(true);
    previewTimer_ = lv_timer_create(&KioskApp::onPreview, 50, this);
}

void KioskApp::onPreview(lv_timer_t *t)
{
    auto *self = static_cast<KioskApp *>(t->user_data);
    if (!self->previewImg_) return;
    const lv_img_dsc_t *f = PreviewDecoder::get().takeFrame();
    if (!f) return;
    lv_img_set_src(self->previewImg_, f);
    if (f->header.w != self->previewW_ || f->header.h != self->previewH_) {
        self->previewW_ = f->header.w;
        self->previewH_ = f->header.h;
        // "cover" scaling so the card fills the viewport
        uint32_t zx = (uint32_t)UI_PREVIEW_W * 256 / f->header.w;
        uint32_t zy = (uint32_t)UI_PREVIEW_H * 256 / f->header.h;
        lv_img_set_zoom(self->previewImg_, (uint16_t)std::max(zx, zy));
        lv_obj_center(self->previewImg_);
    }
}

void KioskApp::buildManualEntry()
{
    setFullscreen(false);
    backButton(content_, [](lv_event_t *) { KioskApp::get().go(KioskState::CAMERA_SCAN); });
    lv_obj_t *t = label(content_, tr(S::TypeName), &dt_font_bold_28);
    lv_obj_align(t, LV_ALIGN_TOP_MID, 0, 22);
    lv_obj_t *cont = button(content_, 600, 12, 184, 52, GREEN, tr(S::Continue), &dt_font_20);
    ta1_ = textArea(content_, UI_PAD, 76, 376, tr(S::FirstName), false);
    ta2_ = textArea(content_, UI_PAD * 2 + 376, 76, 376, tr(S::LastName), false);
    for (lv_obj_t *ta : {ta1_, ta2_}) {
        lv_textarea_set_max_length(ta, 40);
        lv_textarea_set_accepted_chars(ta, nullptr);
    }
    kb_ = lv_keyboard_create(content_);
    lv_obj_set_size(kb_, LCD_H_RES, KB_H);
    lv_obj_align(kb_, LV_ALIGN_BOTTOM_MID, 0, 0);
    lv_obj_set_style_text_font(kb_, &lv_font_montserrat_24, LV_PART_ITEMS);
    lv_keyboard_set_mode(kb_, LV_KEYBOARD_MODE_TEXT_UPPER);
    attachKeyboard(kb_, ta1_);
    lv_obj_add_event_cb(ta2_, [](lv_event_t *e) { lv_keyboard_set_textarea(KioskApp::get().kb_, lv_event_get_target(e)); }, LV_EVENT_FOCUSED, nullptr);
    auto next = [](lv_event_t *) {
        auto &a = KioskApp::get();
        std::string f = lv_textarea_get_text(a.ta1_), l = lv_textarea_get_text(a.ta2_);
        auto trim = [](std::string s) {
            s.erase(0, s.find_first_not_of(' '));
            s.erase(s.find_last_not_of(' ') + 1);
            return s;
        };
        f = trim(f);
        l = trim(l);
        if (f.empty()) {
            lv_obj_add_state(a.ta1_, LV_STATE_FOCUSED);
            return;
        }
        if (l.empty()) {
            lv_keyboard_set_textarea(a.kb_, a.ta2_);
            return;
        }
        a.firstName_ = f;
        a.lastName_ = l;
        a.sessionId_.clear();
        a.manualEntry_ = true;
        a.go(KioskState::CONFIRM_IDENTITY);
    };
    onClick(cont, next);
    lv_obj_add_event_cb(kb_, next, LV_EVENT_READY, nullptr);
}

void KioskApp::buildConfirm()
{
    setFullscreen(false);
    submitting_ = false;
    std::string header = mode_ == ScanMode::SIGN_OUT
                             ? std::string(tr(S::SigningOutTo)) + "  " LV_SYMBOL_RIGHT "  " + trDestination(destination_)
                             : std::string(tr(S::SigningInTo)) + "  " LV_SYMBOL_RIGHT "  " + tr(S::Room) + " " + cfg_.roomNumber;
    lv_obj_t *h = label(content_, header.c_str(), &dt_font_bold_28, mode_ == ScanMode::SIGN_OUT ? SIGN_OUT : 0x34D399);
    lv_obj_align(h, LV_ALIGN_TOP_MID, 0, 16);

    lv_obj_t *thumbBox = box(content_, 24, 70, 240, 180, SURFACE, 12);
    lv_obj_set_style_clip_corner(thumbBox, true, 0);
    const lv_img_dsc_t *snap = manualEntry_ ? nullptr : PreviewDecoder::get().snapshot();
    if (snap) {
        lv_obj_t *img = lv_img_create(thumbBox);
        lv_img_set_src(img, snap);
        uint32_t zx = 240u * 256 / snap->header.w, zy = 180u * 256 / snap->header.h;
        lv_img_set_zoom(img, (uint16_t)std::max(zx, zy));
        lv_obj_center(img);
    } else {
        lv_obj_t *badge = label(thumbBox, manualEntry_ ? ICON_KEYBOARD : ICON_ID_CARD, &dt_icons_56, ACCENT);
        lv_obj_center(badge);
    }

    lv_obj_t *q = label(content_, tr(S::IsThisYourName), &dt_font_24, TEXT_DIM);
    lv_obj_set_pos(q, 292, 76);
    std::string name = firstName_ + " " + lastName_;
    lv_obj_t *n = wrapLabel(content_, name.c_str(), &dt_font_bold_56, 490);
    lv_obj_set_pos(n, 290, 112);

    confirmBtnRow_ = box(content_, 0, 290, LCD_H_RES, 120, BG);
    lv_obj_set_style_bg_opa(confirmBtnRow_, LV_OPA_TRANSP, 0);
    lv_obj_t *cancel = button(confirmBtnRow_, 16, 8, 240, 104, RED, tr(S::Cancel), &dt_font_bold_28, TEXT, ICON_XMARK, &dt_icons_32);
    lv_obj_t *retake = button(confirmBtnRow_, 280, 8, 240, 104, YELLOW, tr(S::Retake), &dt_font_bold_28, DARK_TEXT, ICON_RETAKE, &dt_icons_32);
    lv_obj_t *confirm = button(confirmBtnRow_, 544, 8, 240, 104, GREEN, tr(S::Confirm), &dt_font_bold_28, TEXT, ICON_CHECK, &dt_icons_32);
    onClick(cancel, [](lv_event_t *) {
        auto &a = KioskApp::get();
        if (!a.submitting_) a.go(KioskState::HOME);
    });
    onClick(retake, [](lv_event_t *) {
        auto &a = KioskApp::get();
        if (!a.submitting_) a.go(KioskState::CAMERA_SCAN);
    });
    onClick(confirm, [](lv_event_t *e) {
        auto &a = KioskApp::get();
        if (a.submitting_) return;
        a.submitting_ = true;
        lv_obj_t *row = a.confirmBtnRow_;
        for (uint32_t i = 0; i < lv_obj_get_child_cnt(row); ++i) lv_obj_add_state(lv_obj_get_child(row, i), LV_STATE_DISABLED);
        lv_obj_t *lbl = lv_obj_get_child(lv_event_get_target(e), 1);
        if (lbl) lv_label_set_text(lbl, tr(S::Saving));
        auto *job = new JobMsg{Job::SubmitEvent};
        job->a = a.mode_ == ScanMode::SIGN_OUT ? "SIGN_OUT" : "SIGN_IN";
        job->b = a.destination_;
        job->c = a.firstName_;
        job->d = a.lastName_;
        job->e = a.sessionId_;
        job->flag = a.manualEntry_;
        post_job(job);
    });
}

void KioskApp::buildSuccess()
{
    setFullscreen(false);
    lv_obj_t *card = box(content_, 60, 30, 680, 364, SURFACE, 24);
    lv_obj_t *icon = label(card, ICON_CHECK_CIRCLE, &dt_icons_120, STATUS_OK);
    lv_obj_align(icon, LV_ALIGN_TOP_MID, 0, 24);
    lv_obj_t *title = label(card, mode_ == ScanMode::SIGN_OUT ? tr(S::SignedOutOk) : tr(S::SignedInOk), &dt_font_bold_40);
    lv_obj_align(title, LV_ALIGN_TOP_MID, 0, 168);
    std::string where = mode_ == ScanMode::SIGN_OUT ? trDestination(destination_) : std::string(tr(S::Room)) + " " + cfg_.roomNumber;
    std::string sub = firstName_ + " " + lastName_ + " \xE2\x80\x94 " + where + " " + tr(S::At) + " " + successTime_;
    lv_obj_t *s = wrapLabel(card, sub.c_str(), &dt_font_24, 620, TEXT_DIM, LV_TEXT_ALIGN_CENTER);
    lv_obj_align(s, LV_ALIGN_TOP_MID, 0, 230);
    if (savedOffline_) {
        lv_obj_t *o = wrapLabel(card, tr(S::SavedOffline), &dt_font_20, 620, STATUS_WARN, LV_TEXT_ALIGN_CENTER);
        lv_obj_align(o, LV_ALIGN_TOP_MID, 0, 300);
    }
    lv_obj_add_flag(card, LV_OBJ_FLAG_CLICKABLE);  // tap anywhere to return immediately
    onClick(card, [](lv_event_t *) { KioskApp::get().go(KioskState::HOME); });
    stateTimer_ = lv_timer_create(
        [](lv_timer_t *t) {
            auto *self = static_cast<KioskApp *>(t->user_data);
            self->stateTimer_ = nullptr;
            lv_timer_del(t);
            self->go(KioskState::HOME);
        },
        DT_SUCCESS_RESET_MS, this);
}

// =========================================================================== modals
void KioskApp::closeModal()
{
    if (modal_) {
        lv_obj_del_async(modal_);
        modal_ = nullptr;
        pinTa_ = pinMsg_ = nullptr;
    }
}

void KioskApp::showDiagnostics()
{
    closeModal();
    modal_ = box(lv_layer_top(), 0, 0, LCD_H_RES, LCD_V_RES, 0x000000);
    lv_obj_set_style_bg_opa(modal_, LV_OPA_70, 0);
    lv_obj_add_flag(modal_, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_t *p = box(modal_, 100, 30, 600, 420, SURFACE, 18);
    lv_obj_t *t = label(p, tr(S::DiagTitle), &dt_font_bold_28);
    lv_obj_set_pos(t, 24, 18);

    auto &w = WifiManager::get();
    NetSnapshot &n = net_snapshot();
    char rssi[48], queue[16];
    snprintf(rssi, sizeof rssi, "%s (%d dBm)", w.ssid().c_str(), w.rssi());
    snprintf(queue, sizeof queue, "%d", n.queueDepth);
    std::string cam = std::string(cam_->name()) + " \xE2\x80\x94 " + (cam_->connected() ? tr(S::Online) : tr(S::Offline));
    std::string host = SettingsStore::get().hostUrl() + " \xE2\x80\x94 " + (n.health == NetHealth::Online ? tr(S::Online) : tr(S::Offline));
    std::string room = cfg_.schoolName + " / " + tr(S::Room) + " " + cfg_.roomNumber;
    struct Row { const char *k; std::string v; };
    const Row rows[] = {
        {tr(S::DiagUid), SettingsStore::get().deviceUid()}, {tr(S::DiagIp), w.ip()}, {tr(S::DiagRssi), rssi},
        {tr(S::DiagFw), "v" DT_FIRMWARE_VERSION}, {tr(S::DiagQueue), queue}, {tr(S::DiagHost), host},
        {tr(S::DiagCamera), cam}, {tr(S::Room), room},
    };
    lv_coord_t y = 64;
    for (const auto &r : rows) {
        lv_obj_t *k = label(p, r.k, &dt_font_16, TEXT_DIM);
        lv_obj_set_pos(k, 24, y);
        lv_obj_t *v = label(p, r.v.c_str(), &dt_font_16);
        lv_label_set_long_mode(v, LV_LABEL_LONG_DOT);
        lv_obj_set_width(v, 380);
        lv_obj_set_pos(v, 196, y);
        y += 32;
    }
    lv_obj_t *re = button(p, 24, 340, 176, 60, STATUS_WARN, tr(S::RePair), &dt_font_20, DARK_TEXT);
    lv_obj_t *fr = button(p, 212, 340, 200, 60, RED, tr(S::FactoryReset), &dt_font_20);
    lv_obj_t *cl = button(p, 424, 340, 152, 60, SURFACE_HI, tr(S::Close), &dt_font_20);
    onClick(re, [](lv_event_t *) { KioskApp::get().showPinPad(false); });
    onClick(fr, [](lv_event_t *) { KioskApp::get().showPinPad(true); });
    onClick(cl, [](lv_event_t *) { KioskApp::get().closeModal(); });
}

void KioskApp::showPinPad(bool factoryReset)
{
    pinForReset_ = factoryReset;
    if (!SettingsStore::get().paired()) {  // nothing to protect yet
        post_ui(new UiMsg{Msg::PinOk});
        return;
    }
    closeModal();
    modal_ = box(lv_layer_top(), 0, 0, LCD_H_RES, LCD_V_RES, 0x000000);
    lv_obj_set_style_bg_opa(modal_, LV_OPA_80, 0);
    lv_obj_add_flag(modal_, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_t *t = label(modal_, tr(S::EnterPin), &dt_font_bold_28);
    lv_obj_align(t, LV_ALIGN_TOP_MID, 0, 18);
    pinTa_ = lv_textarea_create(modal_);
    lv_obj_set_size(pinTa_, 300, 60);
    lv_obj_align(pinTa_, LV_ALIGN_TOP_MID, 0, 64);
    lv_textarea_set_one_line(pinTa_, true);
    lv_textarea_set_password_mode(pinTa_, true);
    lv_textarea_set_accepted_chars(pinTa_, "0123456789");
    lv_textarea_set_max_length(pinTa_, 8);
    lv_obj_set_style_text_font(pinTa_, &dt_font_bold_28, 0);
    lv_obj_set_style_text_align(pinTa_, LV_TEXT_ALIGN_CENTER, 0);
    pinMsg_ = label(modal_, "", &dt_font_20, STATUS_BAD);
    lv_obj_align(pinMsg_, LV_ALIGN_TOP_MID, 0, 132);
    lv_obj_t *kb = lv_keyboard_create(modal_);
    lv_keyboard_set_mode(kb, LV_KEYBOARD_MODE_NUMBER);
    lv_obj_set_size(kb, 520, 300);
    lv_obj_align(kb, LV_ALIGN_BOTTOM_MID, 0, -8);
    lv_obj_set_style_text_font(kb, &lv_font_montserrat_28, LV_PART_ITEMS);
    lv_keyboard_set_textarea(kb, pinTa_);
    lv_obj_add_event_cb(kb, [](lv_event_t *) {
        auto &a = KioskApp::get();
        std::string pin = lv_textarea_get_text(a.pinTa_);
        if (pin.size() < 4) return;
        lv_label_set_text(a.pinMsg_, "…");
        post_job(new JobMsg{Job::VerifyPin, pin});
    }, LV_EVENT_READY, nullptr);
    lv_obj_add_event_cb(kb, [](lv_event_t *) { KioskApp::get().closeModal(); }, LV_EVENT_CANCEL, nullptr);
}

void KioskApp::toast(const char *text, uint32_t color)
{
    if (toast_) lv_obj_del(toast_);
    if (toastTimer_) lv_timer_del(toastTimer_);
    toast_ = box(lv_layer_top(), 0, 0, 680, 64, color, 14);
    lv_obj_align(toast_, LV_ALIGN_BOTTOM_MID, 0, -16);
    lv_obj_t *l = wrapLabel(toast_, text, &dt_font_20, 640, TEXT, LV_TEXT_ALIGN_CENTER);
    lv_obj_center(l);
    toastTimer_ = lv_timer_create(
        [](lv_timer_t *t) {
            auto *self = static_cast<KioskApp *>(t->user_data);
            if (self->toast_) lv_obj_del(self->toast_);
            self->toast_ = nullptr;
            self->toastTimer_ = nullptr;
            lv_timer_del(t);
        },
        4000, this);
}

}  // namespace dt
