#include "input.h"

#include <Arduino.h>
#include <Wire.h>

#include "board.h"
#include "ui.h"

// USB-serial remote control (development / field debugging). Every remote
// keystroke is TWO bytes: Ctrl-] then the key. Printable bytes, CR and BS
// after the prefix act like the keyboard; these control codes act like the
// trackball (emacs-style); Ctrl-D prints the screen as text, Ctrl-X sends a
// raw screenshot. The prefix keeps the tty's echo of our own log from
// turning into keypresses. Compile it out of field builds with
// -DWAYPOST_USB_REMOTE=0 (anyone with a cable could drive the UI otherwise;
// docs/security.md).
#ifndef WAYPOST_USB_REMOTE
#define WAYPOST_USB_REMOTE 1
#endif

namespace input {
namespace {

volatile int16_t g_up = 0, g_down = 0, g_left = 0, g_right = 0;
void IRAM_ATTR on_up() { g_up++; }
void IRAM_ATTR on_down() { g_down++; }
void IRAM_ATTR on_left() { g_left++; }
void IRAM_ATTR on_right() { g_right++; }

bool take(volatile int16_t& n) {
  noInterrupts();
  bool fire = n > 0;
  if (fire) n--;
  interrupts();
  return fire;
}

constexpr size_t kQueue = 32;
Event g_queue[kQueue];
size_t g_head = 0, g_count = 0;
uint32_t g_last = 0;

void push(Kind kind, char ch = 0) {
  g_last = millis();
  if (g_count == kQueue) return;  // full: drop the newest rather than reorder
  Event& e = g_queue[(g_head + g_count) % kQueue];
  e.kind = kind;
  e.ch = ch;
  g_count++;
}

void push_key(uint8_t k) {
  if (k == '\r' || k == '\n') push(Kind::Enter);
  else if (k == 0x08 || k == 0x7F) push(Kind::Backspace);
  else if (k >= 0x20 && k < 0x7F) push(Kind::Char, static_cast<char>(k));
}

bool g_press = false;
uint32_t g_press_at = 0;

// The keyboard's own controller (an ESP32-C3) restarts by itself after a
// power dip and then stops answering for a while: notice, and reconnect.
bool g_kb_present = true;
uint32_t g_kb_misses = 0, g_kb_probe_at = 0;

void poll_keyboard() {
  if (!g_kb_present) {
    if (millis() - g_kb_probe_at < 2000) return;
    g_kb_probe_at = millis();
    Wire.end();
    Wire.begin(board::kI2cSda, board::kI2cScl);
    g_kb_present = Wire.requestFrom(board::kKeyboardAddress, static_cast<uint8_t>(1)) == 1;
    if (g_kb_present) {
      Serial.println("keyboard: answering again");
      push_key(Wire.read());
    }
    return;
  }
  if (Wire.requestFrom(board::kKeyboardAddress, static_cast<uint8_t>(1)) != 1) {
    if (++g_kb_misses >= 20) {
      g_kb_present = false;
      g_kb_misses = 0;
      Serial.println("keyboard: stopped answering - reconnecting");
    }
    return;
  }
  g_kb_misses = 0;
  push_key(Wire.read());  // 0 when nothing new
}

void poll_usb() {
#if WAYPOST_USB_REMOTE
  static bool armed = false;  // saw the prefix; next byte is a key
  while (Serial.available() > 0) {
    uint8_t b = static_cast<uint8_t>(Serial.read());
    if (!armed) {
      armed = b == 0x1D;  // Ctrl-]
      continue;
    }
    armed = false;
    switch (b) {
      case 0x10: push(Kind::Up); break;      // Ctrl-P
      case 0x0E: push(Kind::Down); break;    // Ctrl-N
      case 0x02: push(Kind::Left); break;    // Ctrl-B
      case 0x06: push(Kind::Right); break;   // Ctrl-F
      case 0x07: push(Kind::Select); break;  // Ctrl-G
      case 0x04: ui::dump_to_serial(); break;
      case 0x18: ui::pixels_to_serial(); break;
      default: push_key(b);
    }
  }
#endif
}

}  // namespace

void init() {
  for (int pin : {board::kTrackUp, board::kTrackDown, board::kTrackLeft, board::kTrackRight, board::kTrackPress})
    pinMode(pin, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(board::kTrackUp), on_up, FALLING);
  attachInterrupt(digitalPinToInterrupt(board::kTrackDown), on_down, FALLING);
  attachInterrupt(digitalPinToInterrupt(board::kTrackLeft), on_left, FALLING);
  attachInterrupt(digitalPinToInterrupt(board::kTrackRight), on_right, FALLING);
}

void poll() {
  poll_usb();
  poll_keyboard();
  // Trackball press (GPIO0), on the debounced press edge.
  bool down = digitalRead(board::kTrackPress) == LOW;
  if (down != g_press && millis() - g_press_at > 40) {
    g_press = down;
    g_press_at = millis();
    if (down) push(Kind::Select);
  }
  while (take(g_up)) push(Kind::Up);
  while (take(g_down)) push(Kind::Down);
  while (take(g_left)) push(Kind::Left);
  while (take(g_right)) push(Kind::Right);
}

bool next(Event& e) {
  if (!g_count) return false;
  e = g_queue[g_head];
  g_head = (g_head + 1) % kQueue;
  g_count--;
  return true;
}

uint32_t last_activity() { return g_last; }

}  // namespace input
