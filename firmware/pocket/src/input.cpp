#include "input.h"

#include <Arduino.h>

#include "keyboard.h"
#include "ui.h"
#include "utilities.h"

namespace input {
namespace {

// Each trackball direction is a hall sensor that pulses its GPIO as the
// ball rolls; count falling edges in interrupts, turn them into steps here.
volatile int16_t g_up = 0, g_down = 0, g_left = 0, g_right = 0;

void IRAM_ATTR on_up() { g_up++; }
void IRAM_ATTR on_down() { g_down++; }
void IRAM_ATTR on_left() { g_left++; }
void IRAM_ATTR on_right() { g_right++; }

// Edges per emitted step. 1 = every pulse moves the cursor; raise it if the
// ball feels too twitchy on hardware.
constexpr int16_t kPulsesPerStep = 1;
constexpr uint32_t kPressDebounceMs = 40;

bool take(volatile int16_t& counter) {
  bool fire = false;
  noInterrupts();
  if (counter >= kPulsesPerStep) {
    counter -= kPulsesPerStep;
    fire = true;
  }
  interrupts();
  return fire;
}

bool g_press_down = false;
uint32_t g_press_changed_ms = 0;

}  // namespace

void init() {
  keyboard::init();
  pinMode(BOARD_TBOX_UP, INPUT_PULLUP);
  pinMode(BOARD_TBOX_DOWN, INPUT_PULLUP);
  pinMode(BOARD_TBOX_LEFT, INPUT_PULLUP);
  pinMode(BOARD_TBOX_RIGHT, INPUT_PULLUP);
  pinMode(BOARD_BOOT_PIN, INPUT_PULLUP);  // trackball press shares GPIO0
  attachInterrupt(digitalPinToInterrupt(BOARD_TBOX_UP), on_up, FALLING);
  attachInterrupt(digitalPinToInterrupt(BOARD_TBOX_DOWN), on_down, FALLING);
  attachInterrupt(digitalPinToInterrupt(BOARD_TBOX_LEFT), on_left, FALLING);
  attachInterrupt(digitalPinToInterrupt(BOARD_TBOX_RIGHT), on_right, FALLING);
}

// USB-serial remote control (development / field debugging): printable
// bytes and CR/BS act like the keyboard; these control codes act like the
// trackball (emacs-style), and Ctrl-D prints the current screen as text.
constexpr uint8_t kSerialUp = 0x10;      // Ctrl-P
constexpr uint8_t kSerialDown = 0x0E;    // Ctrl-N
constexpr uint8_t kSerialLeft = 0x02;    // Ctrl-B
constexpr uint8_t kSerialRight = 0x06;   // Ctrl-F
constexpr uint8_t kSerialSelect = 0x07;  // Ctrl-G
constexpr uint8_t kSerialDump = 0x04;    // Ctrl-D

Event poll() {
  Event e;

  if (Serial.available() > 0) {
    uint8_t b = static_cast<uint8_t>(Serial.read());
    switch (b) {
      case kSerialUp: e.kind = Kind::Up; return e;
      case kSerialDown: e.kind = Kind::Down; return e;
      case kSerialLeft: e.kind = Kind::Left; return e;
      case kSerialRight: e.kind = Kind::Right; return e;
      case kSerialSelect: e.kind = Kind::Select; return e;
      case kSerialDump: ui::dump_to_serial(); return e;
      default: break;
    }
    if (b == '\r' || b == '\n') e.kind = Kind::Enter;
    else if (b == 0x08 || b == 0x7F) e.kind = Kind::Backspace;
    else if (b >= 0x20 && b < 0x7F) {
      e.kind = Kind::Char;
      e.ch = static_cast<char>(b);
    }
    return e;
  }

  uint8_t key = keyboard::poll();
  if (key != 0) {
    if (key == '\r' || key == '\n') {
      e.kind = Kind::Enter;
    } else if (key == 0x08 || key == 0x7F) {
      e.kind = Kind::Backspace;
    } else if (key >= 0x20 && key < 0x7F) {
      e.kind = Kind::Char;
      e.ch = static_cast<char>(key);
    }
    if (e.kind != Kind::None) return e;
  }

  // Press fires once on the debounced press edge, not while held.
  bool down = digitalRead(BOARD_BOOT_PIN) == LOW;
  uint32_t now = millis();
  if (down != g_press_down && now - g_press_changed_ms >= kPressDebounceMs) {
    g_press_down = down;
    g_press_changed_ms = now;
    if (down) {
      e.kind = Kind::Select;
      return e;
    }
  }

  if (take(g_up)) e.kind = Kind::Up;
  else if (take(g_down)) e.kind = Kind::Down;
  else if (take(g_left)) e.kind = Kind::Left;
  else if (take(g_right)) e.kind = Kind::Right;
  return e;
}

}  // namespace input
