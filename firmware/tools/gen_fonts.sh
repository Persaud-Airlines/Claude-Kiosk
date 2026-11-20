#!/usr/bin/env bash
# Regenerates main/fonts/*.c (LVGL 8 fonts) — only needed if you change sizes or glyph ranges.
#   Montserrat (SIL OFL 1.1) with Latin-1 for English / French / Spanish, falling back to LVGL's
#   built-in Montserrat for LV_SYMBOL_* glyphs; Font Awesome 6 Free Solid for kiosk icons.
set -euo pipefail
cd "$(dirname "$0")/.."
WORK=$(mktemp -d)
(cd "$WORK" && npm init -y >/dev/null && npm i --no-audit --no-fund lv_font_conv@1.5.3 @fortawesome/fontawesome-free@6.7.2 @fontsource/montserrat@5.3.0 >/dev/null)
NM="$WORK/node_modules"
M5="$NM/@fontsource/montserrat/files/montserrat-latin-500-normal.woff"
M7="$NM/@fontsource/montserrat/files/montserrat-latin-700-normal.woff"
FA="$NM/@fortawesome/fontawesome-free/webfonts/fa-solid-900.ttf"
CONV="$NM/.bin/lv_font_conv --bpp 4 --format lvgl --no-compress --lv-include lvgl.h"
OUT=main/fonts
LAT="0x20-0x7E,0xA0-0xFF,0x2014,0x2022,0x2026"
for s in 16 20 24; do $CONV --size $s --font "$M5" -r $LAT --lv-fallback lv_font_montserrat_$s -o $OUT/dt_font_$s.c --lv-font-name dt_font_$s; done
$CONV --size 28 --font "$M7" -r $LAT --lv-fallback lv_font_montserrat_28 -o $OUT/dt_font_bold_28.c --lv-font-name dt_font_bold_28
$CONV --size 40 --font "$M7" -r $LAT --lv-fallback lv_font_montserrat_40 -o $OUT/dt_font_bold_40.c --lv-font-name dt_font_bold_40
$CONV --size 56 --font "$M7" -r $LAT --lv-fallback lv_font_montserrat_48 -o $OUT/dt_font_bold_56.c --lv-font-name dt_font_bold_56
$CONV --size 64 --font "$M7" -r "0x20,0x2D,0x30-0x39,0x41-0x5A" -o $OUT/dt_font_code_64.c --lv-font-name dt_font_code_64
ICONS="0xf7bd,0xf1ad,0xf518,0xf14e,0xf043,0xf141,0xf52b,0xf2f5,0xf2f6,0xf2c2,0xf058,0xf3ed,0xf002,0xf3c5,0xf1eb,0xf023,0xf013,0xf060,0xf2f9,0xf00d,0xf00c,0xf071,0xf11c,0xf030,0xf0ee,0xf0ac,0xf029,0xf0c2,0xf127"
$CONV --size 32 --font "$FA" -r $ICONS -o $OUT/dt_icons_32.c --lv-font-name dt_icons_32
$CONV --size 56 --font "$FA" -r $ICONS -o $OUT/dt_icons_56.c --lv-font-name dt_icons_56
$CONV --size 120 --font "$FA" -r 0xf2f5,0xf2f6,0xf058,0xf3ed -o $OUT/dt_icons_120.c --lv-font-name dt_icons_120
rm -rf "$WORK"
echo "fonts regenerated in $OUT"
