# Classroom Kiosk Firmware (Slave node)

## Hardware
| Part | Notes |
|---|---|
| Waveshare **ESP32-S3-Touch-LCD-7** | ESP32-S3-WROOM-1-N8R8 (8 MB flash, 8 MB octal PSRAM), 800×480 RGB LCD, GT911 touch, CH422G IO expander |
| USB UVC webcam | Any MJPEG-capable UVC camera at 640×480. It connects to the board's **USB OTG** port (GPIO19/20) through a short OTG cable. A powered hub is recommended if the camera draws more than 300 mA. |
| 3D-printed enclosure | The camera points down at an ID-card tray about 8–12 cm away, with diffuse LED lighting (avoid glare on laminated cards) and a matte dark tray so the card's edges contrast. |
| 5 V / 2 A supply | USB-C power on the board's UART port (keep OTG free for the camera). |

Pin assignments live in `firmware/main/config.h`.

**USB_SEL caveat:** the board multiplexes USB and CAN on GPIO19/20 through **CH422G EXIO5**. If the webcam never enumerates (`uvc: webcam opened` never appears on the console), flip `DT_USB_SEL_LEVEL` in `menuconfig` (**DE-TECH-TIVE Kiosk** menu).

## Software stack
* ESP-IDF **5.3** (PlatformIO `espressif32@6.9.0`), C/C++17.
* **LVGL 8.3.11**, `espressif/usb_host_uvc` 2.x and `espressif/esp_jpeg`, all fetched automatically from the ESP Component Registry (`main/idf_component.yml`).
* Fonts: Montserrat with Latin-1 (EN/FR/ES accents) and Font Awesome 6 icons, pre-generated into `main/fonts/`. Regenerate with `tools/gen_fonts.sh`.

## Build & flash
```bash
pip install platformio
cd firmware
pio run -e kiosk-mock-camera -t upload -t monitor   # bench test: no webcam needed
pio run -e kiosk -t upload -t monitor               # production: USB UVC webcam
pio run -e kiosk -t menuconfig                       # DE-TECH-TIVE Kiosk menu: default host URL, camera, USB_SEL
```
Hold **BOOT** while tapping **RESET** if the board doesn't enter download mode automatically.

| PlatformIO env | Purpose |
|---|---|
| `kiosk` | Production firmware with the USB UVC webcam |
| `kiosk-mock-camera` | Injects `main/assets/mock_card.jpg` (Jordan Taylor) as camera frames, so the full OCR flow runs on a bare board |
| `kiosk-secure` | Flash encryption (release mode), Secure Boot v2, **encrypted NVS**, console disabled. **Burns eFuses permanently.** Generate the signing key first: `espsecure.py generate_signing_key --version 2 secure_boot_signing_key.pem` (keep it offline). |

Set the default server address before you flash a fleet: `CONFIG_DT_DEFAULT_HOST_URL` in menuconfig. It can also be changed on-device with the gear icon on the Wi-Fi step.

## First boot
1. **Splash** (3.5 s) while NVS, LVGL, Wi-Fi and NTP start.
2. **Welcome → Language** (English / Français / Español, saved in NVS).
3. **Wi-Fi:** scan list with signal and lock icons, an on-screen keyboard, and hidden-SSID support. The gear icon sets the host URL. The kiosk then checks `GET /api/health`.
4. **Pairing:** an 8-character `XXXX-XXXX` code and a QR code. The kiosk polls every 2 s with a one-time pairing secret. When an admin claims the code, the kiosk receives its device token, school, room and timezone, then goes to **Home**.

## Runtime behaviour
* **Clocks:** `LOCAL hh:mm:ss AM/PM` uses the school's IANA timezone, converted server-side to a POSIX TZ string. `UTC hh:mm:ss` uses SNTP: `time.microsoft.com`, then `pool.ntp.org`, then `time.google.com`. Microsoft's documented public NTP host is `time.windows.com`; edit `DT_NTP_PRIMARY` in `config.h` if your network needs it.
* **Heartbeat (30 s):** reports IP, RSSI, firmware and queue depth. The response updates the school name, room, destinations, timezone and lockdown state. A `401` (kiosk revoked) sends it back to pairing.
* **Scanning:** the live preview decodes MJPEG to RGB565 at 1/2 scale. Separately, up to 3 frames/s are uploaded as raw `image/jpeg` to `/api/v1/kiosk/scan-card`. The first confident read freezes the screen on **Confirm**.
* **Offline queue:** if `/events` fails (no Wi-Fi, timeout or 5xx), the exact event JSON is saved in NVS with its original timestamp, `client_event_id` and `was_offline_queued=true`. Success shows "Saved on this kiosk". Every 10 s while online, up to 20 events are replayed via `/events/batch`. The server orders them chronologically and de-duplicates them. The queue holds 300 events; if it fills, the oldest event is dropped.
* **Status dot:** green = online, amber = host unreachable or events pending, red = no Wi-Fi.
* **Diagnostics:** press and hold the clocks for 5 s. **Re-Pair** keeps Wi-Fi. **Factory Reset** erases everything, including the device identity. Both need the school's kiosk PIN, verified by the server and rate-limited.

## Code map (`firmware/main`)
```
app_main.cpp           boot order, task layout
board/board.c          I2C, CH422G, RGB panel (bounce buffers), GT911 driver
display/lvgl_port.c    LVGL draw buffers (PSRAM), flush, touch indev, tick, mutex
camera/                ICameraProvider + UVC (usb_host_uvc) + mock injector, FrameSlot
net/                   Wi-Fi manager, SNTP/time, HTTPS host client (cert bundle or pinned CA)
storage/               NVS settings, NVS offline queue
workers.cpp            net worker (jobs, pairing poll, heartbeat, queue flush), scanner, preview decoder
ui/kiosk_app.cpp       KioskState machine + every LVGL screen
ui/i18n.cpp            EN / FR / ES strings
```

## Desktop simulator
`firmware/sim` compiles the real `ui/` code, fonts and LVGL on Linux or macOS, with the ESP-IDF layer faked. It plays a scripted touch scenario and writes a screenshot of every state:
```bash
cmake -S firmware/sim -B build-sim && cmake --build build-sim -j && ./build-sim/kiosk_sim out/
```
Use it to iterate on layouts and translations without flashing hardware.
