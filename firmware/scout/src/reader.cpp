#include "reader.h"

#include <algorithm>
#include <cstring>

#include "app.h"
#include "ui.h"

namespace {

bool starts_with(const std::string& s, const char* prefix) {
  return s.compare(0, strlen(prefix), prefix) == 0;
}

std::string trim(const std::string& s) {
  size_t a = s.find_first_not_of(" \t\r");
  if (a == std::string::npos) return "";
  size_t b = s.find_last_not_of(" \t\r");
  return s.substr(a, b - a + 1);
}

}  // namespace

void Reader::open(const std::string& title, Fetch fetch, bool links) {
  _title = title;
  _fetch = std::move(fetch);
  _links_enabled = links;
  _raw.clear();
  _loaded = _total = 0;
  _started = false;
  _fetching = false;
  _gen++;
  _error.clear();
  _lines.clear();
  _links.clear();
  _top = 0;
  _selected_link = -1;
  _chosen.clear();

  ui::title_bar(_title.c_str());
  ui::message("Loading...");
  ui::footer("Loading...", ui::kLive);
  ensure_filled();
}

bool Reader::showing() const { return apps::current() == _owner; }

void Reader::fetch_more() {
  if (_fetching || (_started && _loaded >= _total)) return;
  _fetching = true;
  uint32_t gen = _gen;
  _fetch(_loaded, [this, gen](net::Result r, const std::string& text, size_t total,
                              const std::string& err) {
    if (gen != _gen) return;  // another page was opened meanwhile
    got(r, text, total, err);
  });
}

void Reader::got(net::Result r, const std::string& text, size_t total, const std::string& err) {
  _fetching = false;
  if (r != net::Result::Ok) {
    _error = err.empty() ? net::describe(r) : err;
    if (showing()) draw();
    return;
  }
  bool first = !_started;
  _error.clear();
  _started = true;
  _raw += text;
  _loaded += text.size();
  _total = total;
  if (text.empty()) _total = _loaded;  // no progress: treat as the end
  relayout();
  if (first || _selected_link < 0) _selected_link = first_visible_link();
  if (!showing()) return;
  draw();
  ensure_filled();  // the next chunk, while the person reads this one
}

// Keeps a screen and a bit ahead loaded (one request at a time).
void Reader::ensure_filled() {
  if (!_error.empty()) return;  // scrolling retries
  if (static_cast<int>(_lines.size()) < _top + ui::kBodyLines + 2 && (!_started || _loaded < _total))
    fetch_more();
}

void Reader::relayout() {
  _lines.clear();
  _links.clear();

  size_t pos = 0;
  while (pos < _raw.size()) {
    size_t nl = _raw.find('\n', pos);
    bool complete = nl != std::string::npos;
    std::string raw = _raw.substr(pos, complete ? nl - pos : std::string::npos);
    pos = complete ? nl + 1 : _raw.size();

    // A link line cut mid-way by a chunk boundary waits for the rest.
    if (!complete && !fully_loaded() && _links_enabled && starts_with(raw, "=")) break;

    std::string text;
    uint16_t color = ui::kTextDim;
    int link = -1;
    if (_links_enabled && starts_with(raw, "=>")) {
      std::string rest = trim(raw.substr(2));
      size_t sp = rest.find_first_of(" \t");
      std::string target = rest.substr(0, sp);
      std::string label = sp == std::string::npos ? "" : trim(rest.substr(sp));
      link = static_cast<int>(_links.size());
      _links.push_back(target);
      text = "> " + (label.empty() ? target : label);
      color = ui::kLive;
    } else if (starts_with(raw, "#")) {
      size_t hashes = raw.find_first_not_of('#');
      text = trim(hashes == std::string::npos ? "" : raw.substr(hashes));
      color = ui::kText;
    } else {
      text = raw;
    }

    for (auto& wrapped : ui::wrap(text)) {
      _lines.emplace_back(wrapped, color, link);
    }
  }
}

int Reader::first_visible_link() const {
  for (int i = _top; i < _top + ui::kBodyLines && i < static_cast<int>(_lines.size()); i++) {
    if (_lines[i].link >= 0) return _lines[i].link;
  }
  return -1;
}

bool Reader::on_event(const input::Event& e) {
  using input::Kind;
  int n = static_cast<int>(_lines.size());
  auto line_of = [&](int link) {
    for (int i = 0; i < n; i++)
      if (_lines[i].link == link) return i;
    return -1;
  };
  auto visible = [&](int line) { return line >= _top && line < _top + ui::kBodyLines; };

  switch (e.kind) {
    case Kind::Down: {
      // Prefer the next link on screen; otherwise scroll one line.
      int next = _selected_link + 1;
      int line = next < static_cast<int>(_links.size()) ? line_of(next) : -1;
      if (line >= 0 && visible(line)) {
        _selected_link = next;
      } else {
        _error.clear();  // scrolling retries a failed chunk
        if (_top + ui::kBodyLines < static_cast<int>(_lines.size())) _top++;
        ensure_filled();
        if (line >= 0 && visible(line)) _selected_link = next;
      }
      break;
    }
    case Kind::Up: {
      int prev = _selected_link - 1;
      int line = prev >= 0 ? line_of(prev) : -1;
      if (line >= 0 && visible(line)) {
        _selected_link = prev;
      } else if (_top > 0) {
        _top--;
        if (line >= 0 && visible(line)) _selected_link = prev;
      }
      break;
    }
    case Kind::Right:  // page down
      _error.clear();
      _top += ui::kBodyLines - 1;
      ensure_filled();
      if (_top > static_cast<int>(_lines.size()) - ui::kBodyLines)
        _top = std::max(0, static_cast<int>(_lines.size()) - ui::kBodyLines);
      break;
    case Kind::Select:
    case Kind::Enter: {
      int line = _selected_link >= 0 ? line_of(_selected_link) : -1;
      if (line >= 0 && visible(line)) {
        _chosen = _links[_selected_link];
        return true;
      }
      break;
    }
    default:
      return false;
  }

  // Keep the selection on screen.
  int sel_line = _selected_link >= 0 ? line_of(_selected_link) : -1;
  if (sel_line < 0 || !visible(sel_line)) _selected_link = first_visible_link();
  draw();
  return false;
}

void Reader::draw() {
  int n = static_cast<int>(_lines.size());
  for (int row = 0; row < ui::kBodyLines; row++) {
    int i = _top + row;
    if (i < n) {
      const Line& l = _lines[i];
      ui::body_line(row, l.text, l.color, l.link >= 0 && l.link == _selected_link);
    } else {
      ui::body_line(row, "");
    }
  }

  std::string foot;
  uint16_t color = ui::kMuted;
  if (!_error.empty()) {
    foot = _error + " - scroll to retry";
    color = ui::kWarn;
  } else if (_fetching) {
    foot = "Loading...   roll left: back";
    color = ui::kLive;
  } else if (_total > 0) {
    int pct = static_cast<int>(_loaded * 100 / _total);
    foot = (fully_loaded() ? std::string("all loaded") : std::to_string(pct) + "% loaded") +
           "   roll left: back";
  } else {
    foot = "roll left: back";
  }
  ui::footer(foot, color);
}
