// Dispatch — Station-relayed chat with one default peer (WAYPOST_DISPATCH_PEER),
// over the existing MSG_SEND / MSG_PUSH ops. Multi-conversation is later.
#include <algorithm>
#include <cstring>
#include <deque>
#include <string>

#include <Arduino.h>

#include "app.h"
#include "station_link.h"
#include "ui.h"

#ifndef WAYPOST_DISPATCH_USER
#define WAYPOST_DISPATCH_USER "aj"
#endif
#ifndef WAYPOST_DISPATCH_PEER
#define WAYPOST_DISPATCH_PEER ""
#endif

namespace {

constexpr size_t kMaxInput = 200;
constexpr size_t kMaxHistoryLines = 80;
constexpr int kHistoryRows = ui::kBodyLines - 1;  // last row is the input line

struct ChatLine {
  std::string text;
  uint16_t color;
};

class DispatchApp : public App {
 public:
  const char* title() const override { return _title.c_str(); }

  void enter() override {
    _title = std::string("Dispatch: ") + WAYPOST_DISPATCH_PEER;
    _scroll = 0;
    _unread = 0;
    ui::set_unread(0);
    ui::title_bar(title());
    ui::clear_body();
    if (_history.empty()) {
      add("Type a message and press Enter.", ui::kMuted);
      add("Roll left to go back.", ui::kMuted);
    }
    draw();
  }

  void on_event(const input::Event& e) override {
    using input::Kind;
    switch (e.kind) {
      case Kind::Left:
        apps::home();
        return;
      case Kind::Backspace:
        if (_input.empty()) {
          apps::home();
          return;
        }
        _input.pop_back();
        draw_input();
        return;
      case Kind::Char:
        if (_input.size() < kMaxInput) _input.push_back(e.ch);
        draw_input();
        return;
      case Kind::Enter:
      case Kind::Select:
        send();
        return;
      case Kind::Up:
        if (_scroll + kHistoryRows < static_cast<int>(_history.size())) _scroll++;
        draw_history();
        return;
      case Kind::Down:
        if (_scroll > 0) _scroll--;
        draw_history();
        return;
      default:
        return;
    }
  }

  void deliver(const waylink::IncomingChatMessage& msg) {
    add(msg.sender + ": " + msg.body, ui::kText);
    // Ack so Station marks it delivered; if this is lost, Station keeps the
    // message pending and nothing is dropped.
    station_link::send(waylink::encode_msg_ack(station_link::node_id().c_str(),
                                               station_link::kStationNodeId, msg.rid,
                                               msg.message_id));
    if (apps::current() == this) {
      _scroll = 0;
      draw_history();
    } else {
      ui::set_unread(++_unread);
    }
  }

 private:
  void add(const std::string& text, uint16_t color) {
    for (auto& line : ui::wrap(text)) _history.push_back(ChatLine{line, color});
    while (_history.size() > kMaxHistoryLines) _history.pop_front();
  }

  void send() {
    if (_input.empty()) return;
    if (strlen(WAYPOST_DISPATCH_PEER) == 0) {
      add("(no WAYPOST_DISPATCH_PEER configured)", ui::kWarn);
      draw_history();
      return;
    }
    std::string body = _input;
    _input.clear();
    draw_input();
    ui::footer("Sending...", ui::kLive);

    waylink::Reply reply;
    // One attempt: a retry would get a fresh mid, and a lost *reply* would
    // then deliver the message twice.
    auto result = station_link::request(
        [&](const std::string& mid, const std::string& rid) {
          return waylink::encode_msg_send_request(
              station_link::node_id().c_str(), station_link::kStationNodeId, mid, rid, 120,
              WAYPOST_DISPATCH_USER, WAYPOST_DISPATCH_PEER, body.c_str());
        },
        reply, 1, 15000);
    bool ok = result == station_link::Result::Ok && reply.payload().flag("ok");
    add("me: " + body, ok ? ui::kTextDim : ui::kWarn);
    if (!ok) add(std::string("  (not sent: ") + station_link::describe(result) + ")", ui::kWarn);
    _scroll = 0;
    draw();
  }

  void draw() {
    draw_history();
    draw_input();
  }

  void draw_history() {
    int n = static_cast<int>(_history.size());
    int first = std::max(0, n - kHistoryRows - _scroll);
    for (int row = 0; row < kHistoryRows; row++) {
      int i = first + row;
      if (i < n - _scroll) ui::body_line(row, _history[i].text, _history[i].color);
      else ui::body_line(row, "");
    }
    ui::footer(_scroll > 0 ? "older messages - roll down for newest" : "Enter: send   roll left: back");
  }

  void draw_input() {
    std::string shown = "> " + _input + "_";
    // Keep the end of a long input visible.
    while (shown.size() > 3 && ui::tft().textWidth(shown.c_str(), ui::kFont) > ui::kWidth - 8)
      shown.erase(2, 1);
    ui::body_line(kHistoryRows, shown, ui::kLive);
  }

  std::string _title;
  std::deque<ChatLine> _history;
  std::string _input;
  int _scroll = 0;
  int _unread = 0;
};

DispatchApp& instance() {
  static DispatchApp app;
  return app;
}

}  // namespace

App& apps::dispatch_app() { return instance(); }

void apps::deliver_chat(const waylink::IncomingChatMessage& msg) { instance().deliver(msg); }
