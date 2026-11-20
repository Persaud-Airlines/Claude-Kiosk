#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

esp_err_t lvgl_port_init(void);
/** Recursive lock; every LVGL call made outside the LVGL task must hold it. */
bool lvgl_port_lock(uint32_t timeout_ms);
void lvgl_port_unlock(void);

#ifdef __cplusplus
}
#endif
