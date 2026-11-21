# Kiosk UI simulator

Builds the **real** firmware UI (`main/ui/*.cpp`, `main/fonts/*.c`) against LVGL 8.3.11 on a desktop. `sim_main.cpp` replaces the ESP-IDF platform (NVS, Wi-Fi, HTTP workers, camera) with in-process fakes, drives the touchscreen through a scripted scenario, and writes an 800×480 screenshot of each state.

```bash
cmake -S firmware/sim -B build-sim && cmake --build build-sim -j
# Optional: a live-preview frame from the mock card (needs Python with opencv-python-headless and numpy)
python firmware/sim/make_preview_frame.py frame.rgb565
# Windows: build with Visual Studio (the default generator), then run:
#   cmake --build build-sim --config Release
#   mkdir out; .\build-sim\Release\kiosk_sim.exe out frame.rgb565
# macOS / Linux:
mkdir -p out && ./build-sim/kiosk_sim out frame.rgb565   # writes out/*.ppm
```
LVGL is fetched with CMake FetchContent; pass `-DFETCHCONTENT_SOURCE_DIR_LVGL=/path/to/lvgl` to build offline.
