#include "board.h"

#include <string.h>
#include "config.h"
#include "driver/gpio.h"
#include "driver/i2c_master.h"
#include "esp_idf_version.h"
#include "esp_lcd_panel_rgb.h"
#include "esp_log.h"
#include "esp_check.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "board";

static i2c_master_bus_handle_t s_bus;
static i2c_master_dev_handle_t s_exp_mode, s_exp_out, s_touch;
static esp_lcd_panel_handle_t s_panel;
static uint8_t s_exio = 0;  // shadow of CH422G output register

// ------------------------------------------------------------------------------- CH422G
static esp_err_t exio_write(uint8_t value)
{
    s_exio = value;
    return i2c_master_transmit(s_exp_out, &value, 1, 100);
}

static void exio_set(uint8_t mask, bool high)
{
    exio_write(high ? (s_exio | mask) : (s_exio & ~mask));
}

void board_backlight(bool on) { exio_set(EXIO_LCD_BL, on); }

void board_usb_select(bool route_to_usb)
{
    bool level = route_to_usb ? CONFIG_DT_USB_SEL_LEVEL : !CONFIG_DT_USB_SEL_LEVEL;
    exio_set(EXIO_USB_SEL, level);
}

static esp_err_t expander_init(void)
{
    i2c_device_config_t mode_cfg = {.dev_addr_length = I2C_ADDR_BIT_LEN_7, .device_address = CH422G_ADDR_MODE, .scl_speed_hz = I2C_FREQ_HZ};
    i2c_device_config_t out_cfg = {.dev_addr_length = I2C_ADDR_BIT_LEN_7, .device_address = CH422G_ADDR_OUT, .scl_speed_hz = I2C_FREQ_HZ};
    ESP_RETURN_ON_ERROR(i2c_master_bus_add_device(s_bus, &mode_cfg, &s_exp_mode), TAG, "exp mode");
    ESP_RETURN_ON_ERROR(i2c_master_bus_add_device(s_bus, &out_cfg, &s_exp_out), TAG, "exp out");
    uint8_t mode = 0x01;  // IO_OE: EXIO0..7 push-pull outputs
    ESP_RETURN_ON_ERROR(i2c_master_transmit(s_exp_mode, &mode, 1, 100), TAG, "CH422G not responding");
    // Backlight ON from the first register write: it was previously cleared here and only re-enabled
    // after the first LVGL flush, which left the panel dark.
    uint8_t initial = EXIO_TP_RST | EXIO_LCD_RST | EXIO_SD_CS | EXIO_LCD_BL;
    if (CONFIG_DT_USB_SEL_LEVEL) initial |= EXIO_USB_SEL;
    return exio_write(initial);
}

// --------------------------------------------------------------------------------- GT911
static esp_err_t gt911_read(uint16_t reg, uint8_t *buf, size_t len)
{
    uint8_t r[2] = {(uint8_t)(reg >> 8), (uint8_t)(reg & 0xFF)};
    return i2c_master_transmit_receive(s_touch, r, 2, buf, len, 50);
}

static esp_err_t gt911_write_u8(uint16_t reg, uint8_t v)
{
    uint8_t b[3] = {(uint8_t)(reg >> 8), (uint8_t)(reg & 0xFF), v};
    return i2c_master_transmit(s_touch, b, 3, 50);
}

static esp_err_t touch_init(void)
{
    // Reset sequence that latches I2C address 0x5D (INT held low while RST rises).
    gpio_config_t io = {.pin_bit_mask = 1ULL << PIN_TOUCH_INT, .mode = GPIO_MODE_OUTPUT};
    gpio_config(&io);
    gpio_set_level(PIN_TOUCH_INT, 0);
    exio_set(EXIO_TP_RST, false);
    vTaskDelay(pdMS_TO_TICKS(20));
    exio_set(EXIO_TP_RST, true);
    vTaskDelay(pdMS_TO_TICKS(60));
    io.mode = GPIO_MODE_INPUT;
    gpio_config(&io);

    const uint8_t addrs[2] = {GT911_ADDR_PRIMARY, GT911_ADDR_ALT};
    for (int i = 0; i < 2; ++i) {
        if (i2c_master_probe(s_bus, addrs[i], 50) == ESP_OK) {
            i2c_device_config_t cfg = {.dev_addr_length = I2C_ADDR_BIT_LEN_7, .device_address = addrs[i], .scl_speed_hz = I2C_FREQ_HZ};
            ESP_RETURN_ON_ERROR(i2c_master_bus_add_device(s_bus, &cfg, &s_touch), TAG, "touch dev");
            uint8_t id[4] = {0};
            gt911_read(0x8140, id, 4);
            ESP_LOGI(TAG, "GT911 at 0x%02X, product id %.4s", addrs[i], (char *)id);
            return ESP_OK;
        }
    }
    ESP_LOGE(TAG, "GT911 touch controller not found");
    return ESP_ERR_NOT_FOUND;
}

bool board_touch_read(uint16_t *x, uint16_t *y)
{
    if (!s_touch) return false;
    uint8_t status = 0;
    if (gt911_read(0x814E, &status, 1) != ESP_OK) return false;
    if (!(status & 0x80)) return false;  // buffer not ready: keep previous state
    uint8_t points = status & 0x0F;
    bool pressed = false;
    if (points > 0 && points <= 5) {
        uint8_t p[8];
        if (gt911_read(0x814F, p, 8) == ESP_OK) {
            uint16_t px = (uint16_t)(p[1] | (p[2] << 8));
            uint16_t py = (uint16_t)(p[3] | (p[4] << 8));
            *x = px >= LCD_H_RES ? LCD_H_RES - 1 : px;
            *y = py >= LCD_V_RES ? LCD_V_RES - 1 : py;
            pressed = true;
        }
    }
    gt911_write_u8(0x814E, 0);
    return pressed;
}

// --------------------------------------------------------------------------- RGB panel
static esp_err_t lcd_init(void)
{
    esp_lcd_rgb_panel_config_t cfg = {
        .clk_src = LCD_CLK_SRC_DEFAULT,
        .timings = {
            .pclk_hz = LCD_PIXEL_CLOCK_HZ,
            .h_res = LCD_H_RES,
            .v_res = LCD_V_RES,
            .hsync_pulse_width = LCD_HSYNC_PULSE,
            .hsync_back_porch = LCD_HSYNC_BACK,
            .hsync_front_porch = LCD_HSYNC_FRONT,
            .vsync_pulse_width = LCD_VSYNC_PULSE,
            .vsync_back_porch = LCD_VSYNC_BACK,
            .vsync_front_porch = LCD_VSYNC_FRONT,
            .flags = {.pclk_active_neg = 1},
        },
        .data_width = 16,
        .bits_per_pixel = 16,
        .num_fbs = 1,
        .bounce_buffer_size_px = LCD_H_RES * LCD_BOUNCE_BUFFER_LINES,
#if ESP_IDF_VERSION >= ESP_IDF_VERSION_VAL(5, 4, 0)
        .dma_burst_size = 64,
#else
        .psram_trans_align = 64,
#endif
        .hsync_gpio_num = PIN_LCD_HSYNC,
        .vsync_gpio_num = PIN_LCD_VSYNC,
        .de_gpio_num = PIN_LCD_DE,
        .pclk_gpio_num = PIN_LCD_PCLK,
        .disp_gpio_num = -1,
        .data_gpio_nums = PIN_LCD_DATA,
        .flags = {.fb_in_psram = 1},
    };
    ESP_RETURN_ON_ERROR(esp_lcd_new_rgb_panel(&cfg, &s_panel), TAG, "rgb panel");
    ESP_RETURN_ON_ERROR(esp_lcd_panel_reset(s_panel), TAG, "panel reset");
    return esp_lcd_panel_init(s_panel);
}

esp_lcd_panel_handle_t board_panel(void) { return s_panel; }

esp_err_t board_init(void)
{
    i2c_master_bus_config_t bus = {
        .i2c_port = I2C_NUM_0,
        .sda_io_num = PIN_I2C_SDA,
        .scl_io_num = PIN_I2C_SCL,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags = {.enable_internal_pullup = true},
    };
    ESP_RETURN_ON_ERROR(i2c_new_master_bus(&bus, &s_bus), TAG, "i2c bus");
    ESP_RETURN_ON_ERROR(expander_init(), TAG, "expander");
    ESP_RETURN_ON_ERROR(lcd_init(), TAG, "lcd");
    board_backlight(true);
    ESP_LOGI(TAG, "backlight on");
    if (touch_init() != ESP_OK) ESP_LOGW(TAG, "continuing without touch");
    return ESP_OK;
}
