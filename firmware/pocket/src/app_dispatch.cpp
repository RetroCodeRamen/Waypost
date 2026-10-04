// Dispatch — conversations, kept on the Scout and synced with Station.
//
// Everything shown comes from the Scout's own store (store.*), so history
// reads and compose work with Station out of reach. When Station is in
// reach, conversations (MSG_CONVS) and history (MSG_LIST) are merged into
// the store, live MSG_PUSH and catch-up (MSG_SYNC) land there too, and the
// outbox sends queued messages (MSG_SEND with the Scout's own message id, so
// a resend after a lost reply is the same message). Roadmap D1.
#include <algorithm>
#include <cctype>
#include <cstring>
#include <string>
#include <vector>

#include <Arduino.h>

#include "account.h"
#include "app.h"
#include "contacts.h"
#include "station_link.h"
#include "store.h"
#include "ui.h"

namespace {

using waylink::Field;

constexpr size_t kMaxBody = 140;  // bytes; fits one packet on every path
constexpr int kHistoryRows = ui::kBodyLines - 1;  // last row is the input line
constexpr uint32_t kRetryMs = 30000;              // outbox retry after a failed try

std::string lower(std::string s) {
  for (auto& c : s) c = static_cast<char>(tolower(static_cast<unsigned char>(c)));
  return s;
}

std::string dm_id(const std::string& a, const std::string& b) {
  std::string x = lower(a), y = lower(b);
  return x < y ? "dm:" + x + ":" + y : "dm:" + y + ":" + x;
}

// The other person in a direct conversation ("" for rooms).
std::string dm_peer(const std::string& conv) {
  if (conv.compare(0, 3, "dm:") != 0) return "";
  size_t colon = conv.find(':', 3);
  if (colon == std::string::npos) return "";
  std::string a = conv.substr(3, colon - 3), b = conv.substr(colon + 1);
  return a == lower(account::username()) ? b : a;
}

// A title for a conversation we've only seen an id for (a push).
std::string title_for(const std::string& conv) {
  std::string peer = dm_peer(conv);
  if (peer.empty()) return conv;
  const contacts::Contact* c = contacts::find(peer);
  return c ? c->name : peer;
}

bool is_me(const std::string& user) { return lower(user) == lower(account::username()); }

int queued_in(const std::string& conv) {
  int n = 0;
  for (const auto& o : store::outbox()) n += o.conv == conv;
  return n;
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
  void receive(const std::string& id, const std::string& conv, const std::string& sender,
               const std::string& body) {
    bool viewing = _mode == Mode::Chat && apps::current() == this && conv == _conv_id;
    if (!store::conversation(conv)) store::note_conversation(conv, title_for(conv), 0);
    store::Message m;
    m.id = id;
    m.sender = sender;
    m.body = body;
    m.ts = station_link::now_ms();
    m.state = is_me(sender) ? 's' : 'r';
    if (!store::add(conv, m, !viewing && !is_me(sender))) return;  // seen it already
    ui::set_unread(store::unread_total());
    if (viewing) {
      reload();
      _scroll = 0;
      draw_chat();
    } else if (apps::current() == this && _mode == Mode::List) {
      draw_list();
    }
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

  // Sends the oldest queued message if Station is in reach. One per call;
  // `force` skips the retry wait (just composed).
  void flush_outbox(bool force) {
    if (store::outbox().empty() || !account::paired() || !station_link::station_known()) return;
    if (!force && _retry_at && static_cast<int32_t>(millis() - _retry_at) < 0) return;
    store::Outgoing o = store::outbox().front();
    std::vector<Field> f;
    if (!o.peer.empty()) f.push_back(Field::text("peer", o.peer));
    else f.push_back(Field::text("conversation_id", o.conv));
    f.push_back(Field::text("body", o.body));
    f.push_back(Field::text("message_id", o.id));
    waylink::Reply reply;
    if (apps::current() == this && _mode == Mode::Chat) ui::footer("Sending...", ui::kLive);
    // Retries are safe: the message id is ours, Station keeps one copy.
    auto r = station_link::request("DISPATCH", "MSG_SEND", f, reply, 2, 8000);
    if (r == station_link::Result::Ok && reply.payload().flag("ok")) {
      store::outbox_sent(o.id, reply.payload().text("conversation_id", o.conv));
      _retry_at = 0;
      Serial.printf("dispatch: sent %s (%u still queued)\n", o.id.c_str(),
                    static_cast<unsigned>(store::outbox().size()));
    } else if (r == station_link::Result::Error) {
      // Station refused it (unknown person, not a member...): retrying
      // won't help. Kept in the conversation, marked, with the reason.
      store::outbox_failed(o.id, reply.error);
      Serial.printf("dispatch: %s refused: %s\n", o.id.c_str(), reply.error.c_str());
    } else {
      _retry_at = millis() + kRetryMs;
      if (!_retry_at) _retry_at = 1;
    }
    refresh_view();
  }

 private:
  enum class Mode { List, Pick, Chat };

  void refresh_view() {
    if (apps::current() != this) return;
    if (_mode == Mode::Chat) {
      reload();
      draw_chat();
    } else if (_mode == Mode::List) {
      draw_list();
    }
  }

  // -- conversations list -----------------------------------------------------

  void show_list(bool refresh) {
    _mode = Mode::List;
    ui::title_bar("Dispatch");
    ui::clear_body();
    draw_list();  // what we have, right away
    if (refresh && station_link::station_known()) {
      _station_offset = 0;
      fetch_convs();
      draw_list();
    }
  }

  // Merges a page of Station's conversation list into the store.
  void fetch_convs() {
    ui::footer("Checking Station...", ui::kLive);
    waylink::Reply reply;
    auto r = station_link::request("DISPATCH", "MSG_CONVS", {Field::num("offset", _station_offset)}, reply);
    if (r != station_link::Result::Ok) {
      _list_note = std::string("Station: ") +
                   (r == station_link::Result::Error ? reply.error : station_link::describe(r));
      return;
    }
    _list_note.clear();
    const waylink::Value* convs = reply.payload().get("conversations");
    size_t n = 0;
    if (convs && convs->type == waylink::Value::Array) {
      for (const auto& c : convs->items) {
        store::note_conversation(c.text("id"), c.text("t"), c.uint("ts"));
        n++;
      }
    }
    _station_offset += n;
    _convs_more = reply.payload().flag("more");
  }

  // Rows: "+ New message", conversations, "more..." (from Station).
  int list_size() const {
    return 1 + static_cast<int>(store::conversations().size()) + (_convs_more ? 1 : 0);
  }

  void draw_list() {
    std::vector<std::string> rows{"+ New message"};
    for (const auto& c : store::conversations()) {
      std::string row = (c.unread ? "* " : "  ") + c.title;
      int q = queued_in(c.id);
      if (q) row += "  (" + std::to_string(q) + " waiting)";
      rows.push_back(row);
    }
    if (_convs_more) rows.push_back("  more...");
    if (_sel >= list_size()) _sel = 0;
    ui::list(rows, _sel, _top);
    std::string foot = "press: open   roll left: home";
    uint16_t color = ui::kMuted;
    if (!_list_note.empty()) {
      foot = _list_note;
      color = ui::kWarn;
    } else if (!station_link::station_known()) {
      foot = "Station out of reach - saved messages";
      color = ui::kWarn;
    }
    if (!store::outbox().empty()) foot = std::to_string(store::outbox().size()) + " waiting to send. " + foot;
    ui::footer(foot, color);
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
      case Kind::Right: {
        const auto& convs = store::conversations();
        if (_sel == 0) {
          show_pick();
        } else if (_sel <= static_cast<int>(convs.size())) {
          store::Conversation c = convs[_sel - 1];
          open_chat(c.id, dm_peer(c.id), c.title);
        } else {
          fetch_convs();
          draw_list();
        }
        return;
      }
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
    if (contacts::all().empty() && station_link::station_known()) refresh_contacts();
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
    std::string foot = _pick_note.empty() ? "press: choose   roll left: back" : _pick_note;
    if (_pick_note.empty() && contacts::all().empty())
      foot = "No saved contacts yet - Station needed once";
    ui::footer(foot, _pick_note.empty() ? ui::kMuted : ui::kWarn);
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
          contacts::Contact c = contacts::all()[_pick_sel];
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
    _older = false;
    _scroll = 0;
    _input.clear();
    _chat_note.clear();
    store::mark_read(conv_id);
    ui::set_unread(store::unread_total());
    ui::title_bar(_title.c_str());
    ui::clear_body();
    wait_for_files();
    reload();
    draw_chat();
    if (station_link::station_known()) {
      fetch_history(0);  // newest page: anything we missed
      reload();
      draw_chat();
    }
  }

  // Saved conversations can't be read while the radio is still starting
  // (storage is busy, see store.h); that takes seconds after boot.
  void wait_for_files() {
    if (store::files_safe()) return;
    ui::footer("Opening saved messages...", ui::kLive);
    uint32_t start = millis();
    while (!store::files_safe() && millis() - start < 60000) {
      ui::busy_tick();
      ui::present();
      delay(50);
    }
    ui::busy_clear();
    store::loop();
  }

  void reload() { _msgs = store::messages(_conv_id); }

  // A page of Station's history for this conversation into the store.
  // `skip` = how many of the newest messages to pass over.
  void fetch_history(size_t skip) {
    ui::footer("Checking Station...", ui::kLive);
    std::vector<Field> f{Field::text("conversation_id", _conv_id), Field::num("skip", skip)};
    waylink::Reply reply;
    auto r = station_link::request("DISPATCH", "MSG_LIST", f, reply);
    if (r == station_link::Result::Error && reply.error == "not_a_member") {
      _older = false;  // new conversation: Station has nothing yet
      return;
    }
    if (r != station_link::Result::Ok) {
      _chat_note = std::string("Station: ") + station_link::describe(r) + " - showing saved";
      return;
    }
    const waylink::Value* list = reply.payload().get("messages");
    if (list && list->type == waylink::Value::Array) {
      for (const auto& m : list->items) {
        store::Message msg;
        msg.id = m.text("id");
        msg.sender = m.text("s");
        msg.body = m.text("b");
        msg.ts = m.uint("ts");
        msg.state = is_me(msg.sender) ? 's' : 'r';
        store::add(_conv_id, msg, false);
      }
    }
    store::mark_read(_conv_id);  // we're looking at it
    _older = reply.payload().flag("more");
  }

  std::vector<std::pair<std::string, uint16_t>> chat_lines() const {
    std::vector<std::pair<std::string, uint16_t>> lines;
    if (_older) lines.push_back({"  (roll up for older)", ui::kMuted});
    for (const auto& m : _msgs) {
      bool mine = is_me(m.sender);
      std::string text = (mine ? "me" : m.sender) + ": " + m.body;
      uint16_t color = mine ? ui::kTextDim : ui::kText;
      if (m.state == 'q') {
        text += "  (waiting)";
        color = ui::kMuted;
      } else if (m.state == 'f') {
        text += "  (not sent: " + m.note + ")";
        color = ui::kWarn;
      }
      for (auto& l : ui::wrap(text)) lines.push_back({l, color});
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
      std::string foot = std::to_string(_input.size()) + "/" + std::to_string(kMaxBody) +
                         "   Enter: send   roll left: back";
      if (!station_link::station_known()) foot += "   (offline: queued)";
      ui::footer(foot);
    }
  }

  void on_chat(const input::Event& e) {
    using input::Kind;
    switch (e.kind) {
      case Kind::Left:
        show_list(false);
        return;
      case Kind::Backspace:
        if (_input.empty()) {
          show_list(false);
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
        } else if (_older && station_link::station_known()) {
          int before = n;
          fetch_history(store::synced_count(_conv_id));
          reload();
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

  // Queues the message (saved at once) and tries to send it now; if
  // Station is out of reach it goes when Station is back.
  void send() {
    if (_input.empty()) return;
    std::string body = _input;
    _input.clear();
    _chat_note.clear();
    store::note_conversation(_conv_id, _title, station_link::now_ms());
    store::queue(_conv_id, _peer, body);
    reload();
    _scroll = 0;
    draw_chat();
    flush_outbox(true);
  }

  Mode _mode = Mode::List;
  uint32_t _retry_at = 0;

  size_t _station_offset = 0;
  bool _convs_more = false;
  int _sel = 0, _top = 0;
  std::string _list_note;

  int _pick_sel = 0, _pick_top = 0;
  std::string _pick_note;

  std::string _conv_id, _peer, _title;
  std::vector<store::Message> _msgs;
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

void apps::flush_outbox(bool force) { instance().flush_outbox(force); }
