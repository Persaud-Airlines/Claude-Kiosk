// Host-simulator stub: just enough FreeRTOS types for the shared headers to compile.
#pragma once
#include <stdint.h>
typedef void *SemaphoreHandle_t;
typedef void *QueueHandle_t;
typedef int BaseType_t;
typedef uint32_t TickType_t;
#define pdMS_TO_TICKS(x) (x)
#define portMAX_DELAY 0xFFFFFFFFu
#define pdTRUE 1
#define pdFALSE 0
