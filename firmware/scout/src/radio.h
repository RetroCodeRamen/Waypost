// The LoRa radio as a microReticulum interface that never waits.
//
// The old driver (pocket's LoRaInterface) sent with RadioLib's blocking
// transmit() — a two-frame packet held the caller ~1 s — and polled for
// receives. This one follows Meshtastic's RadioLibInterface: the SX1262's
// DIO1 interrupt wakes the net task, send_outgoing() only queues, and
// loop() moves a small state machine along (listen before talk, start a
// transmit, finish it on TX_DONE, back to receive). Every SPI transaction
// goes through bus::LockingHal, so it can't interleave with a screen flush.
//
// Over the air it is unchanged: RNode's one-byte header (random upper
// nibble = sequence, bit 0 = split) and packets over 254 bytes sent as two
// frames — Station's RNode reads it exactly as before.
//
// Only the net task calls into this.
#pragma once

#include <deque>
#include <string>
#include <vector>

#include <microReticulum/Bytes.h>
#include <microReticulum/Interface.h>

namespace radio {

struct Stats {
  uint32_t tx_packets = 0, rx_packets = 0;
  uint32_t tx_frames = 0, rx_frames = 0;
  uint32_t busy_backoffs = 0;  // channel heard busy before a send
  uint32_t rx_errors = 0;      // CRC / read failures
  uint32_t tx_errors = 0;
  float last_rssi = 0, last_snr = 0;
  bool online = false;
};

class AsyncLoRa : public RNS::InterfaceImpl {
 public:
  AsyncLoRa();
  ~AsyncLoRa() override;

  bool start() override;
  void stop() override;
  void loop() override;

  const Stats& stats() const { return _stats; }
  bool idle() const { return _state == State::Receive && _queue.empty(); }

  static constexpr uint8_t kHeaderSplit = 0x01;  // RNode FLAG_SPLIT
  static constexpr int kMaxPayload = 254;        // 255 - header byte

 private:
  bool send_outgoing(const RNS::Bytes& data) override;

  enum class State { Off, Receive, Backoff, Transmit };
  void on_dio1();
  void read_frame();
  void begin_send();
  void transmit_next_frame();
  void listen();

  State _state = State::Off;
  std::deque<RNS::Bytes> _queue;        // whole Reticulum packets waiting to go
  std::vector<std::string> _frames;     // the packet being sent, as LoRa frames
  size_t _frame = 0;
  int _scans = 0;                       // listen-before-talk attempts so far
  uint32_t _backoff_until = 0;
  uint32_t _tx_started = 0;

  RNS::Bytes _rx_buffer;                // first half of a split packet
  int _rx_seq = -1;

  Stats _stats;
};

// The net task's handle: wakes when DIO1 fires (radio.cpp's ISR notifies it).
void set_wake_task(void* task_handle);

}  // namespace radio
