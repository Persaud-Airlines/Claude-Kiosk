// DE-TECH-TIVE TECHNOLOGIES Inc — kiosk compile-time configuration.
// Pin map: Waveshare ESP32-S3-Touch-LCD-7 (schematic rev. 1.x).
#pragma once

#include "sdkconfig.h"

#define DT_FIRMWARE_VERSION "1.0.0"
#define DT_SPLASH_MS 3500
#define DT_SUCCESS_RESET_MS 3000
#define DT_PAIR_POLL_MS 2000
#define DT_HEARTBEAT_MS 30000
#define DT_QUEUE_FLUSH_MS 10000
#define DT_HTTP_TIMEOUT_MS 8000
#define DT_SCAN_TIMEOUT_MS 9000
#define DT_MANUAL_ENTRY_HINT_MS 8000
#define DT_DIAG_LONG_PRESS_MS 5000

// ---------------------------------------------------------------- display (RGB565 parallel)
#define LCD_H_RES 800
#define LCD_V_RES 480
#define LCD_PIXEL_CLOCK_HZ (16 * 1000 * 1000)
#define LCD_HSYNC_PULSE 4
#define LCD_HSYNC_BACK 8
#define LCD_HSYNC_FRONT 8
#define LCD_VSYNC_PULSE 4
#define LCD_VSYNC_BACK 16
#define LCD_VSYNC_FRONT 16
#define LCD_BOUNCE_BUFFER_LINES 10

#define PIN_LCD_DE 5
#define PIN_LCD_VSYNC 3
#define PIN_LCD_HSYNC 46
#define PIN_LCD_PCLK 7
// DATA0..15 = B3..B7, G2..G7, R3..R7
#define PIN_LCD_DATA {14, 38, 18, 17, 10, 39, 0, 45, 48, 47, 21, 1, 2, 42, 41, 40}

// ---------------------------------------------------------------- I2C bus (touch + IO expander)
#define PIN_I2C_SDA 8
#define PIN_I2C_SCL 9
#define I2C_FREQ_HZ 400000
#define PIN_TOUCH_INT 4

// CH422G IO expander
#define CH422G_ADDR_MODE 0x24  // WR_SET: system parameters
#define CH422G_ADDR_OUT 0x38   // WR_IO: output levels for EXIO0..7
#define EXIO_TP_RST (1u << 1)
#define EXIO_LCD_BL (1u << 2)
#define EXIO_LCD_RST (1u << 3)
#define EXIO_SD_CS (1u << 4)
#define EXIO_USB_SEL (1u << 5)

// GT911 capacitive touch
#define GT911_ADDR_PRIMARY 0x5D
#define GT911_ADDR_ALT 0x14

// ---------------------------------------------------------------- UI geometry (spec)
#define UI_TOPBAR_H 56
#define UI_WORK_H (LCD_V_RES - UI_TOPBAR_H)  // 424
#define UI_PAD 16
#define UI_PREVIEW_W 440
#define UI_PREVIEW_H 270

// ---------------------------------------------------------------- NTP (spec order)
#define DT_NTP_PRIMARY "time.microsoft.com"
#define DT_NTP_FALLBACK1 "pool.ntp.org"
#define DT_NTP_FALLBACK2 "time.google.com"
