#include "tasks.h"

#include <map>
#include <string>

#include <Arduino.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/semphr.h>
#include <freertos/task.h>

namespace tasks {
namespace {

using Fn = std::function<void()>;

TaskHandle_t g_ui = nullptr;
QueueHandle_t g_posted = nullptr;  // Fn* for the UI task

struct WorkerState {
  const char* name;
  uint32_t stack;
  QueueHandle_t queue;
  volatile bool busy;
};
WorkerState g_workers[2] = {{"crypto", 16384, nullptr, false}, {"sync", 24576, nullptr, false}};

void worker_main(void* arg) {
  auto* w = static_cast<WorkerState*>(arg);
  for (;;) {
    Fn* fn = nullptr;
    if (xQueueReceive(w->queue, &fn, portMAX_DELAY) != pdTRUE) continue;
    w->busy = true;
    (*fn)();
    delete fn;
    w->busy = uxQueueMessagesWaiting(w->queue) > 0;
  }
}

}  // namespace

void set_ui_task() {
  g_ui = xTaskGetCurrentTaskHandle();
  if (!g_posted) g_posted = xQueueCreate(32, sizeof(Fn*));
}

bool on_ui_task() { return g_ui && xTaskGetCurrentTaskHandle() == g_ui; }

void post(Fn fn) {
  if (!g_posted) g_posted = xQueueCreate(32, sizeof(Fn*));
  Fn* p = new Fn(std::move(fn));
  if (xQueueSend(g_posted, &p, pdMS_TO_TICKS(1000)) != pdTRUE) {
    Serial.println("tasks: UI queue full, dropped a posted job");
    delete p;
    return;
  }
  if (g_ui) xTaskNotifyGive(g_ui);
}

void on_ui(const Fn& fn) {
  if (on_ui_task()) {
    fn();
    return;
  }
  SemaphoreHandle_t done = xSemaphoreCreateBinary();
  post([&fn, done] {
    fn();
    xSemaphoreGive(done);
  });
  xSemaphoreTake(done, portMAX_DELAY);
  vSemaphoreDelete(done);
}

bool drain() {
  bool ran = false;
  Fn* p = nullptr;
  while (g_posted && xQueueReceive(g_posted, &p, 0) == pdTRUE) {
    (*p)();
    delete p;
    ran = true;
  }
  return ran;
}

void wait(uint32_t ms) { ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(ms)); }

void start_workers() {
  for (auto& w : g_workers) {
    w.queue = xQueueCreate(8, sizeof(Fn*));
    // Core 1 with the UI, below it in priority: the UI preempts them, and
    // core 0 stays the radio's.
    xTaskCreatePinnedToCore(worker_main, w.name, w.stack, &w, 1, nullptr, 1);
  }
}

void run(Worker which, Fn work) {
  WorkerState& w = g_workers[static_cast<int>(which)];
  Fn* p = new Fn(std::move(work));
  w.busy = true;
  if (xQueueSend(w.queue, &p, 0) != pdTRUE) {
    Serial.printf("tasks: %s worker queue full\n", w.name);
    delete p;
  }
}

bool idle(Worker which) {
  WorkerState& w = g_workers[static_cast<int>(which)];
  return !w.busy && uxQueueMessagesWaiting(w.queue) == 0;
}

}  // namespace tasks

namespace rpc {
namespace {
std::map<uint32_t, Callback> g_waiting;  // UI task only
}

uint32_t ask(net::Request r, Callback done) {
  uint32_t id = net::request(std::move(r));
  g_waiting[id] = std::move(done);
  return id;
}

uint32_t ask(const char* svc, const char* op, std::vector<waylink::Field> fields, Callback done,
             int attempts, uint32_t timeout_ms, uint64_t ts) {
  uint32_t id = net::request(svc, op, std::move(fields), attempts, timeout_ms, ts, /*asked=*/true);
  g_waiting[id] = std::move(done);
  return id;
}

uint32_t ask_background_request(net::Request r, Callback done) {
  r.asked = false;
  return ask(std::move(r), std::move(done));
}

uint32_t ask_background(const char* svc, const char* op, std::vector<waylink::Field> fields, Callback done,
                        int attempts, uint32_t timeout_ms, uint64_t ts) {
  uint32_t id = net::request(svc, op, std::move(fields), attempts, timeout_ms, ts, /*asked=*/false);
  g_waiting[id] = std::move(done);
  return id;
}

void cancel(uint32_t id) {
  if (g_waiting.erase(id)) net::forget(id);
}

void poll() {
  // Collect first: a callback may start (or cancel) other requests.
  std::vector<std::pair<Callback, std::pair<net::Result, waylink::Reply>>> finished;
  for (auto it = g_waiting.begin(); it != g_waiting.end();) {
    net::Result r;
    waylink::Reply reply;
    if (net::result(it->first, r, reply)) {
      finished.push_back({std::move(it->second), {r, std::move(reply)}});
      it = g_waiting.erase(it);
    } else {
      ++it;
    }
  }
  for (auto& f : finished) f.first(f.second.first, f.second.second);
}

int busy() { return static_cast<int>(g_waiting.size()); }

net::Result call(net::Request r, waylink::Reply& out) {
  uint32_t id = net::request(std::move(r));
  net::Result res;
  while (!net::result(id, res, out)) vTaskDelay(pdMS_TO_TICKS(20));
  return res;
}

}  // namespace rpc
