// Dispatch — conversations with anyone in Station's directory, over LoRa.
//
//   Conversations (MSG_CONVS) -> conversation (MSG_LIST history + live
//   MSG_PUSH) -> compose (MSG_SEND, 140 bytes). "+ New message" picks a
//   contact (contacts.*, PROFILE/ROLL_LIST). Messages missed while the
//   Scout was off or out of range arrive via MSG_SYNC catch-up.
#include <algorithm>
#include <cctype>
#include <cstring>
#include <map>
#include <string>
#include <vector>

#include <Arduino.h>

#include "account.h"
#include "app.h"
#include "contacts.h"
#include "station_link.h"
#include "ui.h"

namespace {

using waylink::Field;

constexpr size_t kMaxBody = 140;  // bytes; fits one packet on every path
constexpr int kHistoryRows = ui::kBodyLines - 1;  // last row is the input line

struct Msg {
  std::string id, sender, body;
  uint64_t ts;
};

struct Conv {
  std::string id, title;
  uint64_t ts;
};

std::string lower(std::string s) {
  for (auto& c : s) c = static_cast<char>(tolower(static_cast<unsigned char>(c)));
  return s;
}

std::string dm_id(const std::string& a, const std::string& b) {
  std::string x = lower(a), y = lower(b);
  return x < y ? "dm:" + x + ":" + y : "dm:" + y + ":" + x;
}

class DispatchApp : public App {
 public:
  const char* title() const override { return "Dispatch"; }

  void enter() override { show_list(true); }

  void on_event(const input::Event& e) override {
    switch (_mode) {
      case Mode::List: on_list(e); break;
      case Mode::Pick: on_pick(e); break;
      case Mode::Chat: on_chat(e); break;
    }
  }

  // A live push (ack sent) or a catch-up message (already confirmed).
  void receive(const std::string& id, const std::string& conv_id, const std::string& sender,
               const std::string& body) {
    // The same message can come by push and again by catch-up (lost ack).
    if (std::find(_seen.begin(), _seen.end(), id) != _seen.end()) return;
    _seen.push_back(id);
    if (_seen.size() > 64) _seen.erase(_seen.begin());
    if (_mode == Mode::Chat && apps::current() == this && conv_id == _conv_id) {
      if (std::none_of(_msgs.begin(), _msgs.end(), [&](const Msg& m) { return m.id == id; })) {
        _msgs.push_back({id, sender, body, static_cast<uint64_t>(millis())});
        _scroll = 0;
        draw_chat();
      }
      return;
    }
    _unread[conv_id]++;
    ui::set_unread(total_unread());
    if (apps::current() == this && _mode == Mode::List) draw_list();
  }

  void catch_up() {
    if (!account::paired()) return;
    for (int round = 0; round < 20; round++) {
      waylink::Reply reply;
      auto r = station_link::request(
          "DISPATCH", "MSG_SYNC",
          {Field::text("username", account::username()), Field::empty_list("messages")}, reply);
      if (r != station_link::Result::Ok) return;
      const waylink::Value* pending = reply.payload().get("pending");
      int n = 0;
      if (pending && pending->type == waylink::Value::Array) {
        for (const auto& m : pending->items) {
          receive(m.text("id"), m.text("conversation_id"), m.text("sender"), m.text("body"));
          n++;
        }
      }
      if (n) Serial.printf("dispatch: caught up %d message(s)\n", n);
      if (!reply.payload().flag("more")) return;
    }
  }

 private:
  enum class Mode { List, Pick, Chat };

  int total_unread() const {
    int n = 0;
    for (const auto& kv : _unread) n += kv.second;
    return n;
  }

  // -- conversations list -----------------------------------------------------

  void show_list(bool refresh) {
    _mode = Mode::List;
    ui::title_bar("Dispatch");
    ui::clear_body();
    if (refresh || _convs.empty()) load_convs(true);
    draw_list();
  }

  void load_convs(bool fresh) {
    if (fresh) {
      _convs.clear();
      _convs_more = false;
    }
    ui::footer("Loading conversations...", ui::kLive);
    waylink::Reply reply;
    auto r = station_link::request("DISPATCH", "MSG_CONVS",
                                   {Field::num("offset", _convs.size())}, reply);
    if (r != station_link::Result::Ok) {
      _list_error = std::string("Couldn't load: ") +
                    (r == station_link::Result::Error ? reply.error : station_link::describe(r));
      return;
    }
    _list_error.clear();
    const waylink::Value* convs = reply.payload().get("conversations");
    if (convs && convs->type == waylink::Value::Array) {
      for (const auto& c : convs->items) _convs.push_back({c.text("id"), c.text("t"), c.uint("ts")});
    }
    _convs_more = reply.payload().flag("more");
  }

  // Rows: "+ New message", conversations, "more...".
  int list_size() const { return 1 + static_cast<int>(_convs.size()) + (_convs_more ? 1 : 0); }

  void draw_list() {
    std::vector<std::string> rows{"+ New message"};
    for (const auto& c : _convs) {
      auto it = _unread.find(c.id);
      bool unread = it != _unread.end() && it->second > 0;
      rows.push_back((unread ? "* " : "  ") + c.title);
    }
    if (_convs_more) rows.push_back("  more...");
    if (_sel >= list_size()) _sel = 0;
    ui::list(rows, _sel, _top);
    ui::footer(_list_error.empty() ? "press: open   roll left: home" : _list_error,
               _list_error.empty() ? ui::kMuted : ui::kWarn);
  }

  void on_list(const input::Event& e) {
    using input::Kind;
    switch (e.kind) {
      case Kind::Left:
      case Kind::Backspace:
        apps::home();
        return;
      case Kind::Up: if (_sel > 0) _sel--; break;
      case Kind::Down: if (_sel + 1 < list_size()) _sel++; break;
      case Kind::Select:
      case Kind::Enter:
      case Kind::Right:
        if (_sel == 0) {
          show_pick();
        } else if (_sel <= static_cast<int>(_convs.size())) {
          const Conv& c = _convs[_sel - 1];
          open_chat(c.id, "", c.title);
        } else {
          load_convs(false);
          draw_list();
        }
        return;
      default:
        return;
    }
    draw_list();
  }

  // -- contact picker ----------------------------------------------------------

  void show_pick() {
    _mode = Mode::Pick;
    _pick_sel = _pick_top = 0;
    ui::title_bar("New message to...");
    ui::clear_body();
    if (contacts::all().empty()) refresh_contacts();
    draw_pick();
  }

  void refresh_contacts() {
    ui::footer("Loading contacts...", ui::kLive);
    auto r = contacts::refresh();
    _pick_note = r == station_link::Result::Ok ? "" : std::string("Couldn't refresh: ") + station_link::describe(r);
  }

  void draw_pick() {
    std::vector<std::string> rows;
    for (const auto& c : contacts::all()) rows.push_back(c.name + "  (" + c.username + ")");
    rows.push_back("  Refresh contacts");
    ui::list(rows, _pick_sel, _pick_top);
    ui::footer(_pick_note.empty() ? "press: choose   roll left: back" : _pick_note,
               _pick_note.empty() ? ui::kMuted : ui::kWarn);
  }

  void on_pick(const input::Event& e) {
    using input::Kind;
    int n = static_cast<int>(contacts::all().size()) + 1;
    switch (e.kind) {
      case Kind::Left:
      case Kind::Backspace:
        show_list(false);
        return;
      case Kind::Up: if (_pick_sel > 0) _pick_sel--; break;
      case Kind::Down: if (_pick_sel + 1 < n) _pick_sel++; break;
      case Kind::Select:
      case Kind::Enter:
      case Kind::Right:
        if (_pick_sel == n - 1) {
          refresh_contacts();
        } else {
          const auto& c = contacts::all()[_pick_sel];
          open_chat(dm_id(account::username(), c.username), c.username, c.name);
          return;
        }
        break;
      default:
        return;
    }
    draw_pick();
  }

  // -- conversation ------------------------------------------------------------

  void open_chat(const std::string& conv_id, const std::string& peer, const std::string& title) {
    _mode = Mode::Chat;
    _conv_id = conv_id;
    _peer = peer;
    _title = title;
    _msgs.clear();
    _older = false;
    _scroll = 0;
    _input.clear();
    _chat_note.clear();
    _unread.erase(conv_id);
    ui::set_unread(total_unread());
    ui::title_bar(_title.c_str());
    ui::clear_body();
    load_older();
    draw_chat();
  }

  // Fetches the page of history older than what we hold (skip = how many
  // newest messages we already have; duplicates are dropped by id).
  void load_older() {
    ui::footer("Loading messages...", ui::kLive);
    std::vector<Field> f{Field::text("conversation_id", _conv_id),
                         Field::num("skip", _msgs.size())};
    waylink::Reply reply;
    auto r = station_link::request("DISPATCH", "MSG_LIST", f, reply);
    if (r == station_link::Result::Error && reply.error == "not_a_member") {
      _older = false;  // new conversation: nothing to load yet
      return;
    }
    if (r != station_link::Result::Ok) {
      _chat_note = std::string("Couldn't load history: ") + station_link::describe(r);
      return;
    }
    const waylink::Value* list = reply.payload().get("messages");
    std::vector<Msg> page;
    if (list && list->type == waylink::Value::Array) {
      for (const auto& m : list->items) {
        std::string id = m.text("id");
        bool have = std::any_of(_msgs.begin(), _msgs.end(), [&](const Msg& x) { return x.id == id; });
        if (!have) page.push_back({id, m.text("s"), m.text("b"), m.uint("ts")});
      }
    }
    std::reverse(page.begin(), page.end());  // reply is newest first
    _msgs.insert(_msgs.begin(), page.begin(), page.end());
    _older = reply.payload().flag("more");
  }

  std::vector<std::pair<std::string, uint16_t>> chat_lines() const {
    std::vector<std::pair<std::string, uint16_t>> lines;
    if (_older) lines.push_back({"  (roll up for older)", ui::kMuted});
    for (const auto& m : _msgs) {
      bool mine = lower(m.sender) == lower(account::username());
      std::string who = mine ? "me" : m.sender;
      for (auto& l : ui::wrap(who + ": " + m.body)) lines.push_back({l, mine ? ui::kTextDim : ui::kText});
    }
    if (_msgs.empty() && !_older) lines.push_back({"No messages yet. Type one below.", ui::kMuted});
    return lines;
  }

  void draw_chat() {
    auto lines = chat_lines();
    int n = static_cast<int>(lines.size());
    int max_scroll = std::max(0, n - kHistoryRows);
    if (_scroll > max_scroll) _scroll = max_scroll;
    int first = std::max(0, n - kHistoryRows - _scroll);
    // Bottom-align: the newest message sits just above the input line.
    int pad = std::max(0, kHistoryRows - n);
    for (int row = 0; row < kHistoryRows; row++) {
      int i = first + row - pad;
      if (i >= 0 && i < n - _scroll) ui::body_line(row, lines[i].first, lines[i].second);
      else ui::body_line(row, "");
    }
    draw_input();
  }

  void draw_input() {
    std::string shown = "> " + _input + "_";
    while (shown.size() > 3 && ui::tft().textWidth(shown.c_str(), ui::kFont) > ui::kWidth - 8)
      shown.erase(2, 1);
    ui::body_line(kHistoryRows, shown, ui::kLive);
    if (!_chat_note.empty()) {
      ui::footer(_chat_note, ui::kWarn);
    } else {
      ui::footer(std::to_string(_input.size()) + "/" + std::to_string(kMaxBody) +
                 "   Enter: send   roll left: back");
    }
  }

  void on_chat(const input::Event& e) {
    using input::Kind;
    switch (e.kind) {
      case Kind::Left:
        show_list(true);
        return;
      case Kind::Backspace:
        if (_input.empty()) {
          show_list(true);
          return;
        }
        _input.pop_back();
        draw_input();
        return;
      case Kind::Char:
        if (_input.size() < kMaxBody) _input.push_back(e.ch);
        _chat_note.clear();
        draw_input();
        return;
      case Kind::Enter:
      case Kind::Select:
        send();
        return;
      case Kind::Up: {
        int n = static_cast<int>(chat_lines().size());
        if (_scroll + kHistoryRows < n) {
          _scroll++;
        } else if (_older) {
          int before = n;
          load_older();
          _scroll += static_cast<int>(chat_lines().size()) - before;
        }
        draw_chat();
        return;
      }
      case Kind::Down:
        if (_scroll > 0) _scroll--;
        draw_chat();
        return;
      default:
        return;
    }
  }

  void send() {
    if (_input.empty()) return;
    std::string body = _input;
    _input.clear();
    draw_input();
    ui::footer("Sending...", ui::kLive);

    std::vector<Field> f;
    if (!_peer.empty()) f.push_back(Field::text("peer", _peer));
    else f.push_back(Field::text("conversation_id", _conv_id));
    f.push_back(Field::text("body", body));

    waylink::Reply reply;
    // One attempt: a retry gets a fresh mid, and a lost *reply* would then
    // deliver the message twice.
    auto r = station_link::request("DISPATCH", "MSG_SEND", f, reply, 1, 15000);
    bool ok = r == station_link::Result::Ok && reply.payload().flag("ok");
    if (ok) {
      std::string id = reply.payload().text("id");
      _conv_id = reply.payload().text("conversation_id", _conv_id);
      _msgs.push_back({id, account::username(), body, static_cast<uint64_t>(millis())});
      _chat_note.clear();
    } else {
      _input = body;  // keep it so it can be sent again
      _chat_note = std::string("Not sent: ") +
                   (r == station_link::Result::Error ? reply.error : station_link::describe(r)) +
                   ". Enter to retry.";
    }
    _scroll = 0;
    draw_chat();
  }

  Mode _mode = Mode::List;
  std::map<std::string, int> _unread;
  std::vector<std::string> _seen;  // recent message ids

  std::vector<Conv> _convs;
  bool _convs_more = false;
  int _sel = 0, _top = 0;
  std::string _list_error;

  int _pick_sel = 0, _pick_top = 0;
  std::string _pick_note;

  std::string _conv_id, _peer, _title;
  std::vector<Msg> _msgs;
  bool _older = false;
  int _scroll = 0;
  std::string _input, _chat_note;
};

DispatchApp& instance() {
  static DispatchApp app;
  return app;
}

}  // namespace

App& apps::dispatch_app() { return instance(); }

void apps::deliver_chat(const waylink::IncomingChatMessage& msg) {
  // Ack so Station marks it delivered; if the ack is lost Station keeps it
  // pending and the next catch-up brings it again (deduped by id).
  station_link::send(waylink::encode_msg_ack(station_link::node_id().c_str(),
                                             station_link::kStationNodeId, msg.rid,
                                             msg.message_id));
  instance().receive(msg.message_id, msg.conversation_id, msg.sender, msg.body);
}

void apps::catch_up_chat() { instance().catch_up(); }
