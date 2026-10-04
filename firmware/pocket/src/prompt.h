// One-line text entry screen: pairing codes, PINs, confirmations.
#pragma once

#include <string>

#include "input.h"

class Prompt {
 public:
  enum class Result { None, Submitted, Back };

  struct Options {
    bool masked = false;       // show '*' instead of characters
    bool digits_only = false;  // ignore anything but 0-9
    size_t max_len = 32;
    bool allow_back = true;    // roll left / Backspace on empty = Back
  };

  void open(const std::string& title, const std::string& label, const Options& opts);
  Result on_event(const input::Event& e);

  const std::string& value() const { return _value; }
  void clear() { _value.clear(); }
  // Message under the input (kWarn); empty clears it.
  void set_error(const std::string& msg);
  void set_note(const std::string& msg);  // neutral message (kMuted)
  void draw();

 private:
  std::string _title, _label, _value, _message;
  bool _message_is_error = false;
  Options _opts;
};
