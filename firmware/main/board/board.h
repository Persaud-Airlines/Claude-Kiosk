// Waveshare ESP32-S3-Touch-LCD-7 board support: I2C bus, CH422G expander, RGB panel, GT911 touch.
#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"
#include "esp_lcd_panel_ops.h"

#ifdef __cplusplus
extern "C" {
#endif

esp_err_t board_init(void);
esp_lcd_panel_handle_t board_panel(void);
/** Returns true while a finger is down; coordinates are in display space (0..799, 0..479). */
bool board_touch_read(uint16_t *x, uint16_t *y);
void board_backlight(bool on);
void board_usb_select(bool route_to_usb);

#ifdef __cplusplus
}
#endif
