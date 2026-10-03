#include "app.h"

namespace apps {
namespace {
App* g_current = nullptr;
}

void open(App& app) {
  g_current = &app;
  app.enter();
}

void home() { open(home_app()); }

App* current() { return g_current; }

}  // namespace apps
