// Persistent FIFO of sign-in / sign-out events recorded while the host was unreachable.
// Each entry is the exact JSON body for POST /api/v1/kiosk/events (with the original UTC timestamp and a
// client_event_id idempotency key), so replay is safe even if a flush is interrupted.
#pragma once

#include <string>
#include <utility>
#include <vector>
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

namespace dt {

class OfflineQueue {
public:
    static OfflineQueue &get();
    void load();
    bool push(const std::string &json);
    /** Oldest `max` entries as (slot index, json). */
    std::vector<std::pair<uint32_t, std::string>> peek(size_t max);
    void remove(uint32_t index);
    size_t size();

private:
    OfflineQueue();
    void saveIndices();
    SemaphoreHandle_t lock_;
    unsigned handle_ = 0;
    uint32_t head_ = 0;  // next slot to read
    uint32_t tail_ = 0;  // next slot to write
};

}  // namespace dt
