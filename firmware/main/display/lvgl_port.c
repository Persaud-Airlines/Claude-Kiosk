#include "lvgl_port.h"

#include "board.h"
#include "config.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "lvgl.h"

static const char *TAG = "lvgl";
#define LVGL_TICK_MS 2
#define LVGL_BUF_LINES 120

static SemaphoreHandle_t s_lock;
static lv_disp_draw_buf_t s_draw_buf;
static lv_disp_drv_t s_disp_drv;
static lv_indev_drv_t s_indev_drv;
static bool s_backlight_on;

static void flush_cb(lv_disp_drv_t *drv, const lv_area_t *a, lv_color_t *map)
{
    // RGB panel draw_bitmap copies into the PSRAM frame buffer synchronously.
    esp_lcd_panel_draw_bitmap(board_panel(), a->x1, a->y1, a->x2 + 1, a->y2 + 1, map);
    lv_disp_flush_ready(drv);
    if (!s_backlight_on && lv_disp_flush_is_last(drv)) {
        s_backlight_on = true;
        board_backlight(true);  // turn on only once the first frame is drawn (no white flash)
    }
}

static void touch_cb(lv_indev_drv_t *drv, lv_indev_data_t *data)
{
    // GT911 only reports when its buffer has fresh samples; hold the pressed state across a couple of
    // empty polls so drags and long-presses are not broken up.
    static uint16_t last_x, last_y;
    static bool last_pressed;
    static int idle_polls;
    uint16_t x, y;
    if (board_touch_read(&x, &y)) {
        last_x = x;
        last_y = y;
        last_pressed = true;
        idle_polls = 0;
    } else if (last_pressed && ++idle_polls > 2) {
        last_pressed = false;
        idle_polls = 0;
    }
    data->point.x = last_x;
    data->point.y = last_y;
    data->state = last_pressed ? LV_INDEV_STATE_PRESSED : LV_INDEV_STATE_RELEASED;
}

static void tick_cb(void *arg) { lv_tick_inc(LVGL_TICK_MS); }

bool lvgl_port_lock(uint32_t timeout_ms)
{
    TickType_t t = timeout_ms == 0 ? portMAX_DELAY : pdMS_TO_TICKS(timeout_ms);
    return xSemaphoreTakeRecursive(s_lock, t) == pdTRUE;
}

void lvgl_port_unlock(void) { xSemaphoreGiveRecursive(s_lock); }

static void lvgl_task(void *arg)
{
    while (true) {
        uint32_t delay = 10;
        if (lvgl_port_lock(0)) {
            delay = lv_timer_handler();
            lvgl_port_unlock();
        }
        if (delay < 5) delay = 5;
        if (delay > 30) delay = 30;
        vTaskDelay(pdMS_TO_TICKS(delay));
    }
}

esp_err_t lvgl_port_init(void)
{
    s_lock = xSemaphoreCreateRecursiveMutex();
    lv_init();

    size_t px = LCD_H_RES * LVGL_BUF_LINES;
    lv_color_t *b1 = heap_caps_malloc(px * sizeof(lv_color_t), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    lv_color_t *b2 = heap_caps_malloc(px * sizeof(lv_color_t), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!b1 || !b2) return ESP_ERR_NO_MEM;
    lv_disp_draw_buf_init(&s_draw_buf, b1, b2, px);

    lv_disp_drv_init(&s_disp_drv);
    s_disp_drv.hor_res = LCD_H_RES;
    s_disp_drv.ver_res = LCD_V_RES;
    s_disp_drv.flush_cb = flush_cb;
    s_disp_drv.draw_buf = &s_draw_buf;
    lv_disp_drv_register(&s_disp_drv);

    lv_indev_drv_init(&s_indev_drv);
    s_indev_drv.type = LV_INDEV_TYPE_POINTER;
    s_indev_drv.read_cb = touch_cb;
    s_indev_drv.long_press_time = 600;
    lv_indev_drv_register(&s_indev_drv);

    const esp_timer_create_args_t targs = {.callback = tick_cb, .name = "lv_tick"};
    esp_timer_handle_t tick;
    ESP_ERROR_CHECK(esp_timer_create(&targs, &tick));
    ESP_ERROR_CHECK(esp_timer_start_periodic(tick, LVGL_TICK_MS * 1000));

    BaseType_t ok = xTaskCreatePinnedToCore(lvgl_task, "lvgl", 10 * 1024, NULL, 4, NULL, 1);
    ESP_LOGI(TAG, "LVGL %d.%d.%d ready", lv_version_major(), lv_version_minor(), lv_version_patch());
    return ok == pdPASS ? ESP_OK : ESP_FAIL;
}
