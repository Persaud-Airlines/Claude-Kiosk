#include <cstring>
#include "camera_provider.hpp"
#include "esp_heap_caps.h"

namespace dt {

FrameSlot::FrameSlot(size_t capacity) : cap_(capacity)
{
    lock_ = xSemaphoreCreateMutex();
    buf_ = static_cast<uint8_t *>(heap_caps_malloc(capacity, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
}

FrameSlot::~FrameSlot()
{
    heap_caps_free(buf_);
    vSemaphoreDelete(lock_);
}

void FrameSlot::put(const uint8_t *jpeg, size_t len)
{
    if (!buf_ || len == 0 || len > cap_) return;
    if (xSemaphoreTake(lock_, pdMS_TO_TICKS(20)) != pdTRUE) return;  // drop frame rather than stall USB
    memcpy(buf_, jpeg, len);
    len_ = len;
    ++seq_;
    xSemaphoreGive(lock_);
}

size_t FrameSlot::copyIfNewer(uint8_t *out, size_t cap, uint32_t *seq)
{
    size_t n = 0;
    xSemaphoreTake(lock_, portMAX_DELAY);
    if (len_ && seq_ != *seq && len_ <= cap) {
        memcpy(out, buf_, len_);
        n = len_;
        *seq = seq_;
    }
    xSemaphoreGive(lock_);
    return n;
}

size_t FrameSlot::copyLatest(uint8_t *out, size_t cap, uint32_t *seq)
{
    size_t n = 0;
    xSemaphoreTake(lock_, portMAX_DELAY);
    if (len_ && len_ <= cap) {
        memcpy(out, buf_, len_);
        n = len_;
        if (seq) *seq = seq_;
    }
    xSemaphoreGive(lock_);
    return n;
}

void FrameSlot::clear()
{
    xSemaphoreTake(lock_, portMAX_DELAY);
    len_ = 0;
    xSemaphoreGive(lock_);
}

}  // namespace dt
