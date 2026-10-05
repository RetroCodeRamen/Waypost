// Trailhead — browse the Station's linked text pages over LoRa (TRAIL_GET).
#include <string>
#include <vector>

#include "app.h"
#include "reader.h"
#include "tasks.h"
#include "ui.h"

namespace {

using waylink::Field;

class TrailheadApp : public App {
 public:
  const char* title() const override { return "Trailhead"; }

  void enter() override {
    if (_path.empty()) _path = "home";
    open_page();
  }

  void on_event(const input::Event& e) override {
    using input::Kind;
    if (e.kind == Kind::Left || e.kind == Kind::Backspace) {
      if (_history.empty()) {
        apps::home();
      } else {
        _path = _history.back();
        _history.pop_back();
        open_page();
      }
      return;
    }
    if (_reader.on_event(e)) {
      _history.push_back(_path);
      if (_history.size() > 16) _history.erase(_history.begin());
      _path = _reader.link_target();
      open_page();
    }
  }

 private:
  void open_page() {
    std::string path = _path;
    _reader.open(
        path,
        [this, path](size_t offset, Reader::Got got) {
          rpc::ask("TRAILHEAD", "TRAIL_GET",
                    {Field::text("path", path), Field::num("offset", offset), Field::num("limit", 160)},
                    [this, path, got](net::Result r, waylink::Reply& reply) {
                      if (r != net::Result::Ok) {
                        std::string err;
                        if (r == net::Result::Error)
                          err = reply.error == "not_found" ? "no page \"" + path + "\"" : reply.error;
                        got(r, "", 0, err);
                        return;
                      }
                      std::string title = reply.payload().text("title");
                      if (!title.empty() && apps::current() == this) ui::title_bar(title.c_str());
                      got(r, reply.payload().text("text"), reply.payload().uint("total"), "");
                    });
        },
        /*links=*/true);
  }

  std::string _path;
  std::vector<std::string> _history;
  Reader _reader{this};
};

}  // namespace

App& apps::trailhead_app() {
  static TrailheadApp app;
  return app;
}
