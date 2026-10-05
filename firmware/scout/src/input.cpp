#include "input.h"

#include <Arduino.h>
#include <Wire.h>

#include "board.h"

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

void push(Kind kind, char ch = 0) {
  if (g_count == kQueue) return;
  Event& e = g_queue[(g_head + g_count) % kQueue];
  e.kind = kind;
  e.ch = ch;
  g_count++;
}

bool g_press = false;
uint32_t g_press_at = 0;

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
  // Keyboard: one byte per read, 0 when nothing new.
  if (Wire.requestFrom(board::kKeyboardAddress, static_cast<uint8_t>(1)) == 1) {
    uint8_t k = Wire.read();
    if (k == '\r' || k == '\n') push(Kind::Enter);
    else if (k == 0x08 || k == 0x7F) push(Kind::Backspace);
    else if (k >= 0x20 && k < 0x7F) push(Kind::Char, static_cast<char>(k));
  }
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

}  // namespace input
