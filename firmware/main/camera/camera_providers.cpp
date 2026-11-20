#include "camera_provider.hpp"

#include "esp_log.h"
#include "esp_timer.h"
#include "sdkconfig.h"
#include "uvc_host.h"

extern const uint8_t mock_card_jpg_start[] asm("_binary_mock_card_jpg_start");
extern const uint8_t mock_card_jpg_end[] asm("_binary_mock_card_jpg_end");

namespace dt {
namespace {
const char *TAG = "camera";

class UvcCameraProvider final : public ICameraProvider {
public:
    esp_err_t begin() override
    {
        esp_err_t err = uvc_glue_start(&UvcCameraProvider::onFrame, this, CONFIG_DT_UVC_WIDTH, CONFIG_DT_UVC_HEIGHT,
                                       CONFIG_DT_UVC_FPS);
        if (err != ESP_OK) ESP_LOGE(TAG, "USB host / UVC init failed: %s", esp_err_to_name(err));
        return err;
    }
    void setStreaming(bool on) override
    {
        if (!on) slot_.clear();
        uvc_glue_set_streaming(on);
    }
    bool connected() const override { return uvc_glue_connected(); }
    const char *name() const override { return "USB UVC webcam"; }

private:
    static void onFrame(const uint8_t *jpeg, size_t len, void *ctx)
    {
        static_cast<UvcCameraProvider *>(ctx)->slot_.put(jpeg, len);
    }
};

/** Bench-test provider: injects the embedded mock card at ~8 fps while streaming. */
class MockCameraProvider final : public ICameraProvider {
public:
    esp_err_t begin() override
    {
        const esp_timer_create_args_t args = {.callback = &MockCameraProvider::tick, .arg = this, .name = "mockcam"};
        return esp_timer_create(&args, &timer_);
    }
    void setStreaming(bool on) override
    {
        if (on == streaming_) return;
        streaming_ = on;
        if (on) esp_timer_start_periodic(timer_, 125 * 1000);
        else {
            esp_timer_stop(timer_);
            slot_.clear();
        }
    }
    bool connected() const override { return true; }
    const char *name() const override { return "Mock frame injector"; }

private:
    static void tick(void *arg)
    {
        auto *self = static_cast<MockCameraProvider *>(arg);
        self->slot_.put(mock_card_jpg_start, mock_card_jpg_end - mock_card_jpg_start);
    }
    esp_timer_handle_t timer_ = nullptr;
    bool streaming_ = false;
};
}  // namespace

ICameraProvider *createCameraProvider()
{
#if CONFIG_DT_CAMERA_MOCK
    return new MockCameraProvider();
#else
    return new UvcCameraProvider();
#endif
}

}  // namespace dt
