# Kiosk UI simulator

Builds the **real** firmware UI (`main/ui/*.cpp`, `main/fonts/*.c`) against LVGL 8.3.11 on a desktop. `sim_main.cpp` replaces the ESP-IDF platform (NVS, Wi-Fi, HTTP workers, camera) with in-process fakes, drives the touchscreen through a scripted scenario, and writes an 800×480 screenshot of each state.

```bash
cmake -S firmware/sim -B build-sim && cmake --build build-sim -j
python3 - <<'PY'   # optional: live-preview frame from the mock card
import cv2, numpy as np
img = cv2.resize(cv2.imread('firmware/main/assets/mock_card.jpg'), (320, 240))
rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.uint16)
(((rgb[...,0] >> 3) << 11) | ((rgb[...,1] >> 2) << 5) | (rgb[...,2] >> 3)).astype('<u2').tofile('frame.rgb565')
PY
mkdir -p out && ./build-sim/kiosk_sim out frame.rgb565   # writes out/*.ppm
```
LVGL is fetched with CMake FetchContent; pass `-DFETCHCONTENT_SOURCE_DIR_LVGL=/path/to/lvgl` to build offline.
