#include "prompt.h"

#include <cctype>

#include "ui.h"

void Prompt::open(const std::string& title, const std::string& label, const Options& opts) {
  _title = title;
  _label = label;
  _opts = opts;
  _value.clear();
  _message.clear();
  ui::title_bar(_title.c_str());
  ui::clear_body();
  draw();
}

void Prompt::set_error(const std::string& msg) {
  _message = msg;
  _message_is_error = true;
  draw();
}

void Prompt::set_note(const std::string& msg) {
  _message = msg;
  _message_is_error = false;
  draw();
}

Prompt::Result Prompt::on_event(const input::Event& e) {
  using input::Kind;
  switch (e.kind) {
    case Kind::Enter:
    case Kind::Select:
      return Result::Submitted;
    case Kind::Left:
      return _opts.allow_back ? Result::Back : Result::None;
    case Kind::Backspace:
      if (_value.empty()) return _opts.allow_back ? Result::Back : Result::None;
      _value.pop_back();
      draw();
      return Result::None;
    case Kind::Char:
      if (_opts.digits_only && !isdigit(static_cast<unsigned char>(e.ch))) return Result::None;
      if (_value.size() < _opts.max_len) {
        _value.push_back(e.ch);
        if (!_message.empty() && _message_is_error) _message.clear();
        draw();
      }
      return Result::None;
    default:
      return Result::None;
  }
}

void Prompt::draw() {
  auto label = ui::wrap(_label);
  int row = 0;
  for (; row < static_cast<int>(label.size()) && row < 4; row++) {
    ui::body_line(row, label[row], ui::kTextDim);
  }
  for (int r = row; r < 5; r++) ui::body_line(r, "");
  std::string shown = _opts.masked ? std::string(_value.size(), '*') : _value;
  ui::body_line(5, "> " + shown + "_", ui::kLive);
  ui::body_line(6, "");
  auto msg = ui::wrap(_message);
  for (int r = 0; r < 3; r++) {
    ui::body_line(7 + r, r < static_cast<int>(msg.size()) ? msg[r] : "",
                  _message_is_error ? ui::kWarn : ui::kMuted);
  }
  ui::footer(_opts.allow_back ? "Enter: OK   roll left: back" : "Enter: OK");
}
