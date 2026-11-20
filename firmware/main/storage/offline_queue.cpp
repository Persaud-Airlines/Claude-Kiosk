#include "offline_queue.hpp"

#include <cstdio>
#include "config.h"
#include "esp_log.h"
#include "nvs.h"

namespace dt {
namespace {
const char *TAG = "queue";
void key_for(uint32_t idx, char *out) { snprintf(out, 16, "e%lu", (unsigned long)(idx % 100000)); }
}  // namespace

OfflineQueue &OfflineQueue::get()
{
    static OfflineQueue q;
    return q;
}

OfflineQueue::OfflineQueue() { lock_ = xSemaphoreCreateMutex(); }

void OfflineQueue::load()
{
    nvs_handle_t h;
    ESP_ERROR_CHECK(nvs_open("queue", NVS_READWRITE, &h));
    handle_ = h;
    nvs_get_u32(h, "head", &head_);
    nvs_get_u32(h, "tail", &tail_);
    if (tail_ < head_) head_ = tail_ = 0;
    ESP_LOGI(TAG, "offline queue: %u pending", (unsigned)(tail_ - head_));
}

void OfflineQueue::saveIndices()
{
    nvs_set_u32(handle_, "head", head_);
    nvs_set_u32(handle_, "tail", tail_);
    nvs_commit(handle_);
}

bool OfflineQueue::push(const std::string &json)
{
    xSemaphoreTake(lock_, portMAX_DELAY);
    if (tail_ - head_ >= (uint32_t)CONFIG_DT_OFFLINE_QUEUE_MAX) {
        // Full: drop the oldest entry rather than refuse a student's sign-in during an emergency.
        char k[16];
        key_for(head_, k);
        nvs_erase_key(handle_, k);
        ++head_;
        ESP_LOGW(TAG, "queue full; oldest event dropped");
    }
    char k[16];
    key_for(tail_, k);
    bool ok = nvs_set_str(handle_, k, json.c_str()) == ESP_OK;
    if (ok) {
        ++tail_;
        saveIndices();
    }
    xSemaphoreGive(lock_);
    return ok;
}

std::vector<std::pair<uint32_t, std::string>> OfflineQueue::peek(size_t max)
{
    std::vector<std::pair<uint32_t, std::string>> out;
    xSemaphoreTake(lock_, portMAX_DELAY);
    for (uint32_t i = head_; i < tail_ && out.size() < max; ++i) {
        char k[16];
        key_for(i, k);
        size_t len = 0;
        if (nvs_get_str(handle_, k, nullptr, &len) != ESP_OK || len == 0) continue;
        std::string v(len, '\0');
        if (nvs_get_str(handle_, k, v.data(), &len) == ESP_OK) {
            v.resize(len - 1);
            out.emplace_back(i, std::move(v));
        }
    }
    xSemaphoreGive(lock_);
    return out;
}

void OfflineQueue::remove(uint32_t index)
{
    xSemaphoreTake(lock_, portMAX_DELAY);
    char k[16];
    key_for(index, k);
    nvs_erase_key(handle_, k);
    // Advance head over any leading slots that are now empty.
    while (head_ < tail_) {
        key_for(head_, k);
        size_t len = 0;
        if (nvs_get_str(handle_, k, nullptr, &len) == ESP_OK) break;
        ++head_;
    }
    if (head_ == tail_) head_ = tail_ = 0;
    saveIndices();
    xSemaphoreGive(lock_);
}

size_t OfflineQueue::size()
{
    xSemaphoreTake(lock_, portMAX_DELAY);
    size_t n = tail_ - head_;
    xSemaphoreGive(lock_);
    return n;
}

}  // namespace dt
