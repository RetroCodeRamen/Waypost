#include "reader.h"

#include <algorithm>
#include <cstring>

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
  _error.clear();
  _lines.clear();
  _links.clear();
  _top = 0;
  _selected_link = -1;
  _chosen.clear();

  ui::title_bar(_title.c_str());
  ui::message("Loading...");
  ensure_filled();
  if (_selected_link < 0) _selected_link = first_visible_link();
  draw();
}

bool Reader::fetch_more() {
  if (_started && _loaded >= _total) return false;
  ui::footer("Loading...", TFT_YELLOW);
  std::string text, err;
  size_t total = 0;
  station_link::Result r = _fetch(_loaded, text, total, err);
  if (r != station_link::Result::Ok) {
    _error = err.empty() ? station_link::describe(r) : err;
    return false;
  }
  _error.clear();
  _started = true;
  _raw += text;
  _loaded += text.size();
  _total = total;
  if (text.empty()) _total = _loaded;  // no progress: treat as the end
  relayout();
  return true;
}

void Reader::ensure_filled() {
  while (static_cast<int>(_lines.size()) < _top + ui::kBodyLines + 2 &&
         (!_started || _loaded < _total)) {
    if (!fetch_more()) break;
  }
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
    uint16_t color = TFT_LIGHTGREY;
    int link = -1;
    if (_links_enabled && starts_with(raw, "=>")) {
      std::string rest = trim(raw.substr(2));
      size_t sp = rest.find_first_of(" \t");
      std::string target = rest.substr(0, sp);
      std::string label = sp == std::string::npos ? "" : trim(rest.substr(sp));
      link = static_cast<int>(_links.size());
      _links.push_back(target);
      text = "> " + (label.empty() ? target : label);
      color = TFT_CYAN;
    } else if (starts_with(raw, "#")) {
      size_t hashes = raw.find_first_not_of('#');
      text = trim(hashes == std::string::npos ? "" : raw.substr(hashes));
      color = TFT_YELLOW;
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
        if (_top + ui::kBodyLines >= n) ensure_filled();
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
  uint16_t color = TFT_DARKGREY;
  if (!_error.empty()) {
    foot = _error + " - scroll to retry";
    color = TFT_ORANGE;
  } else if (_total > 0) {
    int pct = static_cast<int>(_loaded * 100 / _total);
    foot = (fully_loaded() ? std::string("all loaded") : std::to_string(pct) + "% loaded") +
           "   roll left: back";
  } else {
    foot = "roll left: back";
  }
  ui::footer(foot, color);
}
