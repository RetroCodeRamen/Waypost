#include "radio.h"

#include <cmath>
#include <cstring>

#include <Arduino.h>
#include <RadioLib.h>
#include <esp_random.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

#include "board.h"
#include "bus.h"

namespace radio {
namespace {

// Same air settings as Station's RNode and the old driver.
constexpr float kFrequency = 915.0;  // MHz
constexpr float kBandwidth = 125.0;  // kHz
constexpr int kSpreading = 8;
constexpr int kCoding = 5;
constexpr int kPower = 17;  // dBm
constexpr int kPreamble = 20;
constexpr float kTcxo = 1.8;  // V, T-Deck (as RNode's BOARD_TDECK)

constexpr int kMaxScans = 8;           // then send anyway rather than stall
constexpr uint32_t kTxTimeoutMs = 3000;  // a 255-byte frame at SF8 takes ~0.5 s
constexpr size_t kMaxQueue = 16;

bus::LockingHal* g_hal = nullptr;
Module* g_module = nullptr;
SX1262* g_radio = nullptr;

volatile bool g_dio1 = false;
TaskHandle_t g_wake = nullptr;

void IRAM_ATTR on_dio1_isr() {
  g_dio1 = true;
  if (g_wake) {
    BaseType_t woke = pdFALSE;
    vTaskNotifyGiveFromISR(g_wake, &woke);
    if (woke) portYIELD_FROM_ISR();
  }
}

bool take_dio1() {
  if (!g_dio1) return false;
  g_dio1 = false;
  return true;
}

}  // namespace

void set_wake_task(void* task_handle) { g_wake = static_cast<TaskHandle_t>(task_handle); }

AsyncLoRa::AsyncLoRa() : RNS::InterfaceImpl("LoRa") {
  _IN = true;
  _OUT = true;
  _bitrate = kSpreading * ((4.0 / kCoding) / (pow(2, kSpreading) / kBandwidth)) * 1000.0;
  _HW_MTU = 508;
}

AsyncLoRa::~AsyncLoRa() { stop(); }

bool AsyncLoRa::start() {
  _online = false;
  // board::bring_up() already started the SPI bus with every chip-select high.
  g_hal = new bus::LockingHal(SPI, SPISettings(8000000, MSBFIRST, SPI_MODE0));
  g_module = new Module(g_hal, board::kRadioCs, board::kRadioDio1, board::kRadioRst, board::kRadioBusy);
  g_radio = new SX1262(g_module);
  int state = g_radio->begin(kFrequency, kBandwidth, kSpreading, kCoding,
                             RADIOLIB_SX126X_SYNC_WORD_PRIVATE, kPower, kPreamble, kTcxo, false);
  if (state == RADIOLIB_ERR_NONE) state = g_radio->setDio2AsRfSwitch(true);
  if (state != RADIOLIB_ERR_NONE) {
    Serial.printf("radio: init failed (%d)\n", state);
    return false;
  }
  g_radio->setDio1Action(on_dio1_isr);
  listen();
  _online = true;
  _stats.online = true;
  Serial.println("radio: up, listening");
  return true;
}

void AsyncLoRa::stop() {
  if (g_radio) g_radio->standby();
  _state = State::Off;
  _online = false;
  _stats.online = false;
}

void AsyncLoRa::listen() {
  g_dio1 = false;
  g_radio->startReceive();  // continuous receive; DIO1 fires per frame
  _state = State::Receive;
}

bool AsyncLoRa::send_outgoing(const RNS::Bytes& data) {
  if (!_online) return false;
  if (_queue.size() >= kMaxQueue) {
    Serial.println("radio: send queue full, packet dropped");
    _stats.tx_errors++;
    return false;
  }
  _queue.push_back(data);
  InterfaceImpl::handle_outgoing(data);  // Reticulum's counters; the send itself is in loop()
  return true;
}

void AsyncLoRa::loop() {
  if (_state == State::Off) return;
  switch (_state) {
    case State::Receive:
      if (take_dio1()) read_frame();
      // Nothing half-heard: our turn to talk.
      if (!_queue.empty() && _state == State::Receive && !g_dio1) begin_send();
      break;
    case State::Backoff:
      if (take_dio1()) read_frame();
      if (static_cast<int32_t>(millis() - _backoff_until) >= 0 && !g_dio1) begin_send();
      break;
    case State::Transmit:
      if (take_dio1()) {
        g_radio->finishTransmit();
        _stats.tx_frames++;
        if (++_frame < _frames.size()) {
          transmit_next_frame();  // second half right behind the first, as RNode does
        } else {
          _stats.tx_packets++;
          _frames.clear();
          listen();
        }
      } else if (millis() - _tx_started > kTxTimeoutMs) {
        Serial.println("radio: transmit never finished, giving up on the packet");
        _stats.tx_errors++;
        g_radio->finishTransmit();
        _frames.clear();
        listen();
      }
      break;
    case State::Off:
      break;
  }
}

void AsyncLoRa::begin_send() {
  if (_frames.empty()) {
    if (_queue.empty()) return;
    const RNS::Bytes data = _queue.front();
    _queue.pop_front();
    // RNode framing: the header's random upper nibble is the sequence;
    // over 254 bytes goes as two frames sharing one header.
    uint8_t header = static_cast<uint8_t>(esp_random()) & 0xF0;
    const uint8_t* p = data.data();
    size_t n = data.size();
    if (n > static_cast<size_t>(kMaxPayload)) header |= kHeaderSplit;
    while (n > 0) {
      size_t take = std::min(n, static_cast<size_t>(kMaxPayload));
      std::string frame(1, static_cast<char>(header));
      frame.append(reinterpret_cast<const char*>(p), take);
      _frames.push_back(std::move(frame));
      p += take;
      n -= take;
    }
    _frame = 0;
    _scans = 0;
  }
  // Listen before talk (channel activity detection, a few ms at SF8).
  int16_t scan = g_radio->scanChannel();
  g_dio1 = false;  // CAD-done fired DIO1 too
  if (scan == RADIOLIB_CHANNEL_FREE || ++_scans >= kMaxScans) {
    transmit_next_frame();
    return;
  }
  _stats.busy_backoffs++;
  listen();
  _state = State::Backoff;
  _backoff_until = millis() + 100 + esp_random() % 300;
}

void AsyncLoRa::transmit_next_frame() {
  const std::string& f = _frames[_frame];
  g_dio1 = false;
  int16_t st = g_radio->startTransmit(reinterpret_cast<const uint8_t*>(f.data()), f.size());
  if (st != RADIOLIB_ERR_NONE) {
    Serial.printf("radio: startTransmit failed (%d)\n", st);
    _stats.tx_errors++;
    _frames.clear();
    listen();
    return;
  }
  _tx_started = millis();
  _state = State::Transmit;
}

void AsyncLoRa::read_frame() {
  size_t len = g_radio->getPacketLength();
  uint8_t buf[256];
  if (len > 255) len = 255;
  int16_t st = g_radio->readData(buf, len);
  if (st != RADIOLIB_ERR_NONE || len < 2) {
    _stats.rx_errors++;
    g_radio->startReceive();  // recover from a bad read
    return;
  }
  // Still in continuous receive: don't restart it, or the second half of
  // a split packet arriving right now would be cut off.
  _stats.rx_frames++;
  _stats.last_rssi = g_radio->getRSSI();
  _stats.last_snr = g_radio->getSNR();

  uint8_t header = buf[0];
  int seq = header >> 4;
  if (header & kHeaderSplit) {
    if (_rx_seq != seq) {  // first half (or a new one after a lost half)
      _rx_seq = seq;
      _rx_buffer.clear();
      _rx_buffer.append(buf + 1, len - 1);
      return;
    }
    _rx_buffer.append(buf + 1, len - 1);
  } else {
    _rx_buffer.clear();
    _rx_buffer.append(buf + 1, len - 1);
  }
  _rx_seq = -1;
  _stats.rx_packets++;
  RNS::Bytes packet = _rx_buffer;
  _rx_buffer.clear();
  InterfaceImpl::handle_incoming(packet);
}

}  // namespace radio
