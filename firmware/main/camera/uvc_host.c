#include "uvc_host.h"

#include "sdkconfig.h"
#if CONFIG_DT_CAMERA_UVC

#include <string.h>
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/task.h"
#include "usb/usb_host.h"
#include "usb/uvc_host.h"

static const char *TAG = "uvc";

#define EVT_WANT_STREAM BIT0
#define EVT_DISCONNECTED BIT1

static EventGroupHandle_t s_events;
static uvc_frame_cb_t s_on_frame;
static void *s_ctx;
static volatile bool s_connected;
static uvc_host_stream_hdl_t s_stream;
static uint16_t s_w, s_h;
static uint8_t s_fps;

static void usb_lib_task(void *arg)
{
    while (true) {
        uint32_t flags = 0;
        usb_host_lib_handle_events(portMAX_DELAY, &flags);
        if (flags & USB_HOST_LIB_EVENT_FLAGS_NO_CLIENTS) usb_host_device_free_all();
    }
}

static bool frame_cb(const uvc_host_frame_t *frame, void *user_ctx)
{
    // MJPEG frames are complete JPEG images; hand a copy to the FrameSlot and release the buffer.
    if (frame->data_len > 4 && frame->data[0] == 0xFF && frame->data[1] == 0xD8 && s_on_frame) {
        s_on_frame(frame->data, frame->data_len, s_ctx);
    }
    return true;
}

static void stream_event_cb(const uvc_host_stream_event_data_t *event, void *user_ctx)
{
    switch (event->type) {
    case UVC_HOST_TRANSFER_ERROR:
        ESP_LOGW(TAG, "USB transfer error");
        break;
    case UVC_HOST_DEVICE_DISCONNECTED:
        ESP_LOGW(TAG, "webcam disconnected");
        s_connected = false;
        xEventGroupSetBits(s_events, EVT_DISCONNECTED);
        break;
    case UVC_HOST_FRAME_BUFFER_OVERFLOW:
        ESP_LOGD(TAG, "frame larger than buffer; dropped");
        break;
    case UVC_HOST_FRAME_BUFFER_UNDERFLOW:
        ESP_LOGD(TAG, "frame buffer underflow");
        break;
    default:
        break;
    }
}

static esp_err_t open_stream(void)
{
    const uvc_host_stream_config_t cfg = {
        .event_cb = stream_event_cb,
        .frame_cb = frame_cb,
        .user_ctx = NULL,
        .usb = {
            .vid = UVC_HOST_ANY_VID,
            .pid = UVC_HOST_ANY_PID,
            .uvc_stream_index = 0,
        },
        .vs_format = {
            .h_res = s_w,
            .v_res = s_h,
            .fps = s_fps,
            .format = UVC_VS_FORMAT_MJPEG,
        },
        .advanced = {
            .number_of_frame_buffers = 3,
            .frame_size = 0,  // derived from the camera's dwMaxVideoFrameSize
            .frame_heap_caps = MALLOC_CAP_SPIRAM,
            .number_of_urbs = 3,
            .urb_size = 10 * 1024,
        },
    };
    return uvc_host_stream_open(&cfg, pdMS_TO_TICKS(3000), &s_stream);
}

static void manager_task(void *arg)
{
    bool streaming = false;
    while (true) {
        if (!s_connected) {
            if (open_stream() == ESP_OK) {
                s_connected = true;
                streaming = false;
                xEventGroupClearBits(s_events, EVT_DISCONNECTED);
                ESP_LOGI(TAG, "webcam opened (%ux%u MJPEG @%u fps)", s_w, s_h, s_fps);
            } else {
                vTaskDelay(pdMS_TO_TICKS(2000));  // no camera yet: retry (hot-plug friendly)
                continue;
            }
        }
        EventBits_t bits = xEventGroupGetBits(s_events);
        if (bits & EVT_DISCONNECTED) {
            if (s_stream) uvc_host_stream_close(s_stream);
            s_stream = NULL;
            s_connected = false;
            streaming = false;
            continue;
        }
        bool want = bits & EVT_WANT_STREAM;
        if (want && !streaming) {
            streaming = uvc_host_stream_start(s_stream) == ESP_OK;
            if (!streaming) ESP_LOGW(TAG, "stream start failed");
        } else if (!want && streaming) {
            uvc_host_stream_stop(s_stream);
            streaming = false;
        }
        vTaskDelay(pdMS_TO_TICKS(100));
    }
}

esp_err_t uvc_glue_start(uvc_frame_cb_t on_frame, void *ctx, uint16_t width, uint16_t height, uint8_t fps)
{
    s_on_frame = on_frame;
    s_ctx = ctx;
    s_w = width;
    s_h = height;
    s_fps = fps;
    s_events = xEventGroupCreate();

    const usb_host_config_t host_cfg = {.skip_phy_setup = false, .intr_flags = ESP_INTR_FLAG_LEVEL1};
    esp_err_t err = usb_host_install(&host_cfg);
    if (err != ESP_OK) return err;
    xTaskCreatePinnedToCore(usb_lib_task, "usb_lib", 4096, NULL, 10, NULL, 0);

    const uvc_host_driver_config_t drv_cfg = {
        .driver_task_stack_size = 6 * 1024,
        .driver_task_priority = 9,
        .xCoreID = 0,
        .create_background_task = true,
    };
    err = uvc_host_install(&drv_cfg);
    if (err != ESP_OK) return err;
    xTaskCreatePinnedToCore(manager_task, "uvc_mgr", 4096, NULL, 5, NULL, 0);
    return ESP_OK;
}

void uvc_glue_set_streaming(bool on)
{
    if (!s_events) return;
    if (on) xEventGroupSetBits(s_events, EVT_WANT_STREAM);
    else xEventGroupClearBits(s_events, EVT_WANT_STREAM);
}

bool uvc_glue_connected(void) { return s_connected; }

#else  // !CONFIG_DT_CAMERA_UVC

esp_err_t uvc_glue_start(uvc_frame_cb_t on_frame, void *ctx, uint16_t w, uint16_t h, uint8_t fps) { return ESP_ERR_NOT_SUPPORTED; }
void uvc_glue_set_streaming(bool on) {}
bool uvc_glue_connected(void) { return false; }

#endif
