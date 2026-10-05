// Fieldbook — read the camp wiki over LoRa: search -> page outline -> section.
// Uses the radio-sized forms of WIKI_SEARCH / WIKI_GET (docs/protocol.md
// "Fieldbook"), each reply one packet; section text arrives in chunks.
#include <string>
#include <vector>

#include <Arduino.h>

#include "app.h"
#include "reader.h"
#include "tasks.h"
#include "ui.h"

namespace {

using waylink::Field;

struct Item {
  std::string key;    // slug, or section index as text
  std::string label;
};

class FieldbookApp : public App {
 public:
  const char* title() const override { return "Fieldbook"; }

  void enter() override { show_query(); }

  void on_event(const input::Event& e) override {
    using input::Kind;
    switch (_mode) {
      case Mode::Query:
        if (e.kind == Kind::Left || (e.kind == Kind::Backspace && _query.empty())) {
          apps::home();
        } else if (e.kind == Kind::Backspace) {
          _query.pop_back();
          draw_query();
        } else if (e.kind == Kind::Char && _query.size() < 60) {
          _query.push_back(e.ch);
          draw_query();
        } else if ((e.kind == Kind::Enter || e.kind == Kind::Select) && !_query.empty()) {
          _items.clear();
          _more = false;
          _sel = _top = 0;
          load_results();
        }
        return;

      case Mode::Results:
      case Mode::Outline:
        if (e.kind == Kind::Left) {
          if (_mode == Mode::Results) show_query();
          else show_results();
          return;
        }
        if (e.kind == Kind::Up && _sel > 0) _sel--;
        else if (e.kind == Kind::Down && _sel + 1 < list_size()) _sel++;
        else if (e.kind == Kind::Select || e.kind == Kind::Enter || e.kind == Kind::Right) {
          choose();
          return;
        } else return;
        draw_list();
        return;

      case Mode::Reading:
        if (e.kind == Kind::Left) {
          show_outline_list();
          return;
        }
        _reader.on_event(e);
        return;
    }
  }

 private:
  enum class Mode { Query, Results, Outline, Reading };

  // -- query --------------------------------------------------------------

  void show_query() {
    _mode = Mode::Query;
    ui::title_bar("Fieldbook");
    ui::clear_body();
    ui::body_line(0, "Search the camp wiki:", ui::kText);
    draw_query();
    ui::body_line(3, "Type words, then Enter.", ui::kMuted);
    ui::footer("roll left: back");
  }

  void draw_query() { ui::body_line(1, "> " + _query + "_", ui::kOk); }

  // -- search results (paged; "more..." fetches the next page) -------------

  void load_results() {
    ui::footer("Searching...", ui::kLive);
    size_t offset = _items.size();
    rpc::cancel(_req);  // one at a time: a second Enter replaces the first
    _req = rpc::ask("FIELDBOOK", "WIKI_SEARCH",
              {Field::text("q", _query), Field::boolean("compact", true), Field::num("offset", offset)},
              [this](net::Result r, waylink::Reply& reply) {
                if (apps::current() != this) return;
                if (r != net::Result::Ok) {
                  fail(reply, r);
                  return;
                }
                const waylink::Value* results = reply.payload().get("results");
                if (results && results->type == waylink::Value::Array) {
                  for (const auto& v : results->items) _items.push_back({v.text("slug"), v.text("title")});
                }
                _more = reply.payload().flag("more");
                _result_items = _items;
                _result_more = _more;
                _result_sel = _sel;
                _mode = Mode::Results;
                ui::title_bar(("Fieldbook: " + _query).c_str());
                if (_items.empty()) {
                  ui::message("No pages match \"" + _query + "\".", ui::kWarn);
                  ui::footer("roll left: new search");
                  return;
                }
                draw_list();
              });
  }

  void show_results() {
    _items = _result_items;
    _more = _result_more;
    _sel = _result_sel;
    _top = 0;
    _mode = Mode::Results;
    ui::title_bar(("Fieldbook: " + _query).c_str());
    ui::clear_body();
    draw_list();
  }

  // -- page outline (paged the same way) ------------------------------------

  void load_outline(bool fresh) {
    if (fresh) {
      _items.clear();
      _sel = _top = 0;
    }
    ui::footer("Loading outline...", ui::kLive);
    size_t offset = _items.size();
    rpc::cancel(_req);
    _req = rpc::ask("FIELDBOOK", "WIKI_GET",
              {Field::text("slug", _slug), Field::boolean("outline", true),
               Field::num("offset", offset), Field::num("limit", 8)},
              [this](net::Result r, waylink::Reply& reply) {
                if (apps::current() != this) return;
                if (r != net::Result::Ok) {
                  fail(reply, r);
                  return;
                }
                const waylink::Value* outline = reply.payload().get("outline");
                if (outline && outline->type == waylink::Value::Array) {
                  for (const auto& v : outline->items) {
                    std::string heading = v.text("heading");
                    _items.push_back({std::to_string(v.uint("index")), heading.empty() ? "(intro)" : heading});
                  }
                }
                _more = reply.payload().flag("more");
                _outline_items = _items;
                _outline_more = _more;
                show_outline_list();
              });
  }

  void show_outline_list() {
    _items = _outline_items;
    _more = _outline_more;
    if (_sel >= list_size()) _sel = 0;
    _mode = Mode::Outline;
    ui::title_bar(_page_title.c_str());
    ui::clear_body();
    draw_list();
  }

  // -- shared list ----------------------------------------------------------

  int list_size() const { return static_cast<int>(_items.size()) + (_more ? 1 : 0); }

  void draw_list() {
    std::vector<std::string> labels;
    for (const auto& it : _items) labels.push_back(it.label);
    if (_more) labels.push_back("more...");
    ui::list(labels, _sel, _top);
    ui::footer("press: open   roll left: back");
  }

  void choose() {
    if (_more && _sel == static_cast<int>(_items.size())) {
      if (_mode == Mode::Results) load_results();
      else load_outline(false);
      return;
    }
    if (_sel >= static_cast<int>(_items.size())) return;
    if (_mode == Mode::Results) {
      _result_sel = _sel;
      _slug = _items[_sel].key;
      _page_title = _items[_sel].label;
      load_outline(true);
    } else {
      open_section(_items[_sel]);
    }
  }

  void open_section(const Item& item) {
    _mode = Mode::Reading;
    std::string slug = _slug;
    uint64_t index = strtoull(item.key.c_str(), nullptr, 10);
    _reader.open(
        item.label,
        [slug, index](size_t offset, Reader::Got got) {
          rpc::ask("FIELDBOOK", "WIKI_GET",
                    {Field::text("slug", slug), Field::num("section", index),
                     Field::num("offset", offset), Field::num("limit", 160)},
                    [got](net::Result r, waylink::Reply& reply) {
                      if (r != net::Result::Ok) {
                        got(r, "", 0, r == net::Result::Error ? reply.error : "");
                        return;
                      }
                      got(r, reply.payload().text("text"), reply.payload().uint("total"), "");
                    });
        },
        /*links=*/false);
  }

  void fail(const waylink::Reply& reply, net::Result r) {
    std::string why = r == net::Result::Error ? reply.error : net::describe(r);
    ui::footer("Failed: " + why + " - press to retry", ui::kWarn);
  }

  Mode _mode = Mode::Query;
  uint32_t _req = 0;  // the list request out, if any
  std::string _query;
  std::string _slug;
  std::string _page_title;

  std::vector<Item> _items;
  bool _more = false;
  int _sel = 0;
  int _top = 0;

  std::vector<Item> _result_items;
  bool _result_more = false;
  int _result_sel = 0;
  std::vector<Item> _outline_items;
  bool _outline_more = false;

  Reader _reader{this};
};

}  // namespace

App& apps::fieldbook_app() {
  static FieldbookApp app;
  return app;
}
