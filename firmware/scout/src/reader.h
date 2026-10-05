// Scrolling reader for text fetched from Station a chunk at a time.
// Shared by Fieldbook (section text) and Trailhead (linked pages).
//
// Markup, one construct per line (Trailhead's gemtext-style format;
// Fieldbook sections use the same '#' headings):
//   # Heading / ## Sub / ### Sub-sub
//   => path Label        (a link; only when links are enabled)
//   anything else        (wrapped text)
#pragma once

#include <functional>
#include <string>
#include <vector>

#include "input.h"

class App;
#include "net.h"

class Reader {
 public:
  // `owner`: the app showing this reader; chunks arriving while another
  // app has the screen are kept but not drawn.
  explicit Reader(const App* owner) : _owner(owner) {}

  // Fetch `offset`.. from Station without waiting, then call `got` (on the
  // UI task) with the text (may be empty at the end) and `total` (bytes),
  // or a failure; `err` is shown.
  using Got = std::function<void(net::Result r, const std::string& text, size_t total,
                                 const std::string& err)>;
  using Fetch = std::function<void(size_t offset, Got got)>;

  void open(const std::string& title, Fetch fetch, bool links);

  // Returns true when the user chose a link; `link_target()` names it.
  bool on_event(const input::Event& e);
  const std::string& link_target() const { return _chosen; }
  const std::string& title() const { return _title; }

  void draw();

 private:
  struct Line {
    Line(const std::string& t, uint16_t c, int l) : text(t), color(c), link(l) {}
    std::string text;
    uint16_t color;
    int link;  // index into _links, or -1
  };

  void fetch_more();
  void got(net::Result r, const std::string& text, size_t total, const std::string& err);
  void relayout();
  bool fully_loaded() const { return _loaded >= _total && _total > 0; }
  int first_visible_link() const;
  void ensure_filled();

  const App* _owner;
  bool showing() const;
  std::string _title;
  Fetch _fetch;
  bool _links_enabled = false;

  std::string _raw;  // UTF-8 received so far
  size_t _loaded = 0;
  size_t _total = 0;
  bool _started = false;
  bool _fetching = false;
  uint32_t _gen = 0;  // bumped by open(): a late chunk for the old page is dropped
  std::string _error;

  std::vector<Line> _lines;
  std::vector<std::string> _links;
  int _top = 0;
  int _selected_link = -1;
  std::string _chosen;
};
