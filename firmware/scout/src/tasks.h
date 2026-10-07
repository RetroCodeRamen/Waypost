// How work moves between tasks (docs/scout-firmware-architecture.md §4).
//
// The UI task owns all app state (account, messages, certificates, the
// screen). Two workers do the slow things off it:
//   Crypto  the password key (scrypt, ~4 s) and the PIN seal (PBKDF2)
//   Sync    peer sync, whose engine (shared with the Outpost) waits on
//           each reply — fine on its own task, never on the UI's
// A worker never touches app state directly: it hands the change to the UI
// task with post() (or on_ui(), which waits for it).
#pragma once

#include <functional>

#include "net.h"

namespace tasks {

// -- the UI task ------------------------------------------------------------------

void set_ui_task();  // called once by the UI task itself
bool on_ui_task();
// Run `fn` on the UI task (from any task), soon.
void post(std::function<void()> fn);
// From a worker: run `fn` on the UI task and wait until it has.
void on_ui(const std::function<void()>& fn);
// UI task, every frame: runs what was posted. Returns false if nothing ran.
bool drain();
// UI task: sleep until the next frame or until something is posted.
void wait(uint32_t ms);

// -- workers ----------------------------------------------------------------------

enum class Worker { Crypto, Sync };
void start_workers();
void run(Worker w, std::function<void()> work);
bool idle(Worker w);

}  // namespace tasks

// Network requests with a callback (UI task) or blocking (workers only).
namespace rpc {

using Callback = std::function<void(net::Result, waylink::Reply&)>;

// UI task: `done` runs on the UI task when the request finishes.
// ask(): something the person is waiting for (a page, a search, a send): it
// goes out even while Station is marked quiet after a timeout.
// ask_background(): jobs nobody is watching (certificates, catch-up, the
// identity check): they wait the quiet out instead of piling onto the radio.
uint32_t ask(net::Request r, Callback done);
uint32_t ask(const char* svc, const char* op, std::vector<waylink::Field> fields, Callback done,
             int attempts = 3, uint32_t timeout_ms = 6000, uint64_t ts = 0);
uint32_t ask_background_request(net::Request r, Callback done);  // r.asked is ignored
uint32_t ask_background(const char* svc, const char* op, std::vector<waylink::Field> fields, Callback done,
                        int attempts = 3, uint32_t timeout_ms = 6000, uint64_t ts = 0);
void cancel(uint32_t id);  // the callback won't run
void poll();               // UI task, every frame
int busy();                // requests with a callback still waiting

// A worker task only: waits (that task only) until the request finishes.
net::Result call(net::Request r, waylink::Reply& out);

}  // namespace rpc
