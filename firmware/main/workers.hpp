#pragma once
#include <cstddef>
#include <cstdint>
#include "camera_provider.hpp"
#include "lvgl.h"

namespace dt {

void workers_start(ICameraProvider *cam);
/** Card upload loop (2–3 frames/s) — enabled only while the scan screen is shown. */
void scanner_set_active(bool on);

/** Decodes camera MJPEG into RGB565 for the on-screen preview (double buffered). */
class PreviewDecoder {
public:
    static PreviewDecoder &get();
    void start(ICameraProvider *cam);
    void setActive(bool on);
    /** UI thread: returns a newly decoded frame (or nullptr). The descriptor stays valid until the next call. */
    const lv_img_dsc_t *takeFrame();
    /** UI thread: snapshot of the last displayed frame (for the confirm-screen thumbnail). */
    const lv_img_dsc_t *snapshot();

private:
    static void task(void *arg);
    ICameraProvider *cam_ = nullptr;
    volatile bool active_ = false;
};

}  // namespace dt
