#pragma once
#include "lvgl.h"

LV_FONT_DECLARE(dt_font_16);
LV_FONT_DECLARE(dt_font_20);
LV_FONT_DECLARE(dt_font_24);
LV_FONT_DECLARE(dt_font_bold_28);
LV_FONT_DECLARE(dt_font_bold_40);
LV_FONT_DECLARE(dt_font_bold_56);
LV_FONT_DECLARE(dt_font_code_64);
LV_FONT_DECLARE(dt_icons_32);
LV_FONT_DECLARE(dt_icons_56);
LV_FONT_DECLARE(dt_icons_120);

namespace dt::theme {
// High-contrast palette (WCAG AA against the label colours used on each)
constexpr uint32_t BG = 0x0B1220;          // screen background
constexpr uint32_t SURFACE = 0x16213A;     // cards / panels
constexpr uint32_t SURFACE_HI = 0x22304F;  // pressed / list rows
constexpr uint32_t TOPBAR = 0x0F1B33;      // dark slate / navy header
constexpr uint32_t TEXT = 0xF8FAFC;
constexpr uint32_t TEXT_DIM = 0xA9B4C7;
constexpr uint32_t ACCENT = 0x38BDF8;      // cyan (emblem, scan frame corners)
constexpr uint32_t SIGN_OUT = 0xE8590C;    // deep amber / coral-orange
constexpr uint32_t SIGN_IN = 0x0F8A72;     // deep emerald / teal
constexpr uint32_t RED = 0xDC2626;         // CANCEL
constexpr uint32_t YELLOW = 0xEAB308;      // RETAKE (dark text)
constexpr uint32_t GREEN = 0x16A34A;       // CONFIRM
constexpr uint32_t DARK_TEXT = 0x111827;
constexpr uint32_t STATUS_OK = 0x22C55E;
constexpr uint32_t STATUS_WARN = 0xF59E0B;
constexpr uint32_t STATUS_BAD = 0xEF4444;
constexpr uint32_t PRIMARY = 0x2563EB;
}  // namespace dt::theme
