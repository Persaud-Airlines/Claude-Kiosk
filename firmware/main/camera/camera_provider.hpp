// Camera hardware abstraction. The UI and network layers only ever see ICameraProvider.
//   * UvcCameraProvider  — USB UVC webcam on the ESP32-S3 OTG port (MJPEG frames, PSRAM buffers)
//   * MockCameraProvider — injects an embedded test card JPEG for bench testing without hardware
#pragma once

#include <cstddef>
#include <cstdint>
#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

namespace dt {

/** Thread-safe "latest frame" slot backed by PSRAM (single producer, many consumers). */
class FrameSlot {
public:
    explicit FrameSlot(size_t capacity);
    ~FrameSlot();
    void put(const uint8_t *jpeg, size_t len);
    /** Copies the newest frame if its sequence differs from *seq. Returns bytes copied (0 = nothing new). */
    size_t copyIfNewer(uint8_t *out, size_t cap, uint32_t *seq);
    size_t copyLatest(uint8_t *out, size_t cap, uint32_t *seq);
    void clear();

private:
    SemaphoreHandle_t lock_;
    uint8_t *buf_;
    size_t cap_;
    size_t len_ = 0;
    uint32_t seq_ = 0;
};

class ICameraProvider {
public:
    virtual ~ICameraProvider() = default;
    virtual esp_err_t begin() = 0;
    /** Start / stop streaming (the camera only streams while the scan screen is visible). */
    virtual void setStreaming(bool on) = 0;
    virtual bool connected() const = 0;
    virtual const char *name() const = 0;
    FrameSlot &frames() { return slot_; }

protected:
    ICameraProvider() : slot_(kMaxJpegBytes) {}
    static constexpr size_t kMaxJpegBytes = 256 * 1024;
    FrameSlot slot_;
};

ICameraProvider *createCameraProvider();

}  // namespace dt
