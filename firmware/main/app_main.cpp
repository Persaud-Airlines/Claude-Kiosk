// DE-TECH-TIVE TECHNOLOGIES Inc — Classroom kiosk (Slave node) entry point.
//
// Task layout (ESP32-S3, dual core):
//   core 1: lvgl      — LVGL timer handler (all UI work, state machine)
//   core 0: net       — Wi-Fi/host jobs, pairing poll, heartbeat, offline-queue flush
//           scan      — uploads card frames (2–3 fps) to /api/v1/kiosk/scan-card while scanning
//           preview   — MJPEG -> RGB565 decode for the live viewport
//           usb_lib / uvc_mgr — USB host + UVC streaming
#include "app_bus.hpp"
#include "board.h"
#include "camera_provider.hpp"
#include "config.h"
#include "esp_heap_caps.h"
#include "esp_system.h"
#include "esp_log.h"
#include "kiosk_app.hpp"
#include "lvgl_port.h"
#include "nvs_flash.h"
#include "offline_queue.hpp"
#include "settings_store.hpp"
#include "wifi_manager.hpp"
#include "workers.hpp"

static const char *TAG = "main";

namespace dt {
void platform_restart() { esp_restart(); }
}  // namespace dt

extern "C" void app_main(void)
{
    ESP_LOGI(TAG, "DE-TECH-TIVE kiosk firmware v%s", DT_FIRMWARE_VERSION);

    // NVS (encrypted automatically when CONFIG_NVS_ENCRYPTION is enabled in the secure profile)
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_LOGW(TAG, "NVS layout changed; erasing");
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);
    dt::SettingsStore::get().load();
    dt::OfflineQueue::get().load();
    dt::bus_init();

    // Display first so the splash appears while the radio starts.
    ESP_ERROR_CHECK(board_init());
    board_usb_select(true);
    ESP_ERROR_CHECK(lvgl_port_init());

    dt::ICameraProvider *cam = dt::createCameraProvider();
    if (cam->begin() != ESP_OK) ESP_LOGE(TAG, "camera provider '%s' failed to start", cam->name());
    dt::PreviewDecoder::get().start(cam);

    if (lvgl_port_lock(0)) {
        dt::KioskApp::get().start(cam);
        lvgl_port_unlock();
    }

    dt::WifiManager::get().init();
    dt::workers_start(cam);
    ESP_LOGI(TAG, "boot complete; free heap %u, PSRAM %u", (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL),
             (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
}
