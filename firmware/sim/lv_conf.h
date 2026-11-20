// LVGL 8.3 configuration for the desktop simulator — mirrors sdkconfig.defaults (CONFIG_LV_*).
#if 1
#ifndef LV_CONF_H
#define LV_CONF_H
#include <stdint.h>
#define LV_COLOR_DEPTH 16
#define LV_COLOR_16_SWAP 0
#define LV_MEM_CUSTOM 1
#define LV_MEM_CUSTOM_INCLUDE <stdlib.h>
#define LV_MEM_CUSTOM_ALLOC malloc
#define LV_MEM_CUSTOM_FREE free
#define LV_MEM_CUSTOM_REALLOC realloc
#define LV_MEMCPY_MEMSET_STD 1
#define LV_DISP_DEF_REFR_PERIOD 16
#define LV_INDEV_DEF_READ_PERIOD 10
#define LV_TICK_CUSTOM 1
#define LV_TICK_CUSTOM_INCLUDE "sim_tick.h"
#define LV_TICK_CUSTOM_SYS_TIME_EXPR (sim_tick_ms())
#define LV_DPI_DEF 130
#define LV_DRAW_COMPLEX 1
#define LV_SHADOW_CACHE_SIZE 0
#define LV_CIRCLE_CACHE_SIZE 4
#define LV_IMG_CACHE_DEF_SIZE 0
#define LV_USE_LOG 0
#define LV_USE_ASSERT_NULL 1
#define LV_USE_ASSERT_MALLOC 1
#define LV_USE_PERF_MONITOR 0
#define LV_FONT_MONTSERRAT_16 1
#define LV_FONT_MONTSERRAT_20 1
#define LV_FONT_MONTSERRAT_24 1
#define LV_FONT_MONTSERRAT_28 1
#define LV_FONT_MONTSERRAT_40 1
#define LV_FONT_MONTSERRAT_48 1
#define LV_FONT_DEFAULT &lv_font_montserrat_20
#define LV_USE_FONT_PLACEHOLDER 1
#define LV_TXT_ENC LV_TXT_ENC_UTF8
#define LV_USE_CANVAS 1
#define LV_USE_KEYBOARD 1
#define LV_USE_SPINNER 1
#define LV_USE_QRCODE 1
#define LV_USE_THEME_DEFAULT 1
#define LV_THEME_DEFAULT_DARK 1
#define LV_USE_FLEX 1
#define LV_USE_GRID 1
#endif
#endif
