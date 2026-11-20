#include "app_bus.hpp"

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

namespace dt {
namespace {
QueueHandle_t s_ui, s_jobs;
NetSnapshot s_snap;
}  // namespace

void bus_init()
{
    s_ui = xQueueCreate(32, sizeof(UiMsg *));
    s_jobs = xQueueCreate(16, sizeof(JobMsg *));
}

void post_ui(UiMsg *m)
{
    if (xQueueSend(s_ui, &m, pdMS_TO_TICKS(200)) != pdTRUE) delete m;
}

UiMsg *pop_ui()
{
    UiMsg *m = nullptr;
    return xQueueReceive(s_ui, &m, 0) == pdTRUE ? m : nullptr;
}

void post_job(JobMsg *j)
{
    if (xQueueSend(s_jobs, &j, pdMS_TO_TICKS(200)) != pdTRUE) delete j;
}

QueueHandle_t jobs_queue() { return s_jobs; }
NetSnapshot &net_snapshot() { return s_snap; }

}  // namespace dt
