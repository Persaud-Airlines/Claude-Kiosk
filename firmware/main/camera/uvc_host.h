// Thin C glue around espressif/usb_host_uvc (MJPEG streaming from a USB webcam).
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef void (*uvc_frame_cb_t)(const uint8_t *jpeg, size_t len, void *ctx);

esp_err_t uvc_glue_start(uvc_frame_cb_t on_frame, void *ctx, uint16_t width, uint16_t height, uint8_t fps);
void uvc_glue_set_streaming(bool on);
bool uvc_glue_connected(void);

#ifdef __cplusplus
}
#endif
