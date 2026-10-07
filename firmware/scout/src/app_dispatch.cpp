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
#include "certs.h"
#include "contacts.h"
#include "receipts.h"
#include "tasks.h"
#include "store.h"
#include "sync.h"
#include "ui.h"

namespace {

using waylink::Field;

constexpr size_t kMaxBody = 140;  // bytes; the most any path allows (signed: less, see max_body)
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

// Message ids are 32 hex characters; signed messages carry the 16 raw bytes.
std::string raw_id(const std::string& hex) {
  std::string out;
  for (size_t i = 0; i + 1 < hex.size(); i += 2)
    out += static_cast<char>(strtoul(hex.substr(i, 2).c_str(), nullptr, 16));
  return out;
}

// MSG_SEND payload: signed (D3) when the outbox entry carries a signature,
// otherwise the paired-device form.
std::vector<waylink::Field> send_fields(const store::Outgoing& o) {
  std::vector<waylink::Field> f;
  if (!o.sig.empty()) {
    if (!o.peer.empty()) f.push_back(waylink::Field::text("p", o.peer));
    else f.push_back(waylink::Field::text("v", o.conv));
    f.push_back(waylink::Field::text("b", o.body));
    f.push_back(waylink::Field::bytes("o", raw_id(o.id)));
    f.push_back(waylink::Field::bytes("a", o.author_id));
    f.push_back(waylink::Field::bytes("s", o.sig));
  } else {
    if (!o.peer.empty()) f.push_back(waylink::Field::text("peer", o.peer));
    else f.push_back(waylink::Field::text("conversation_id", o.conv));
    f.push_back(waylink::Field::text("body", o.body));
    f.push_back(waylink::Field::text("message_id", o.id));
  }
  return f;
}

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
    store::Message m;
    m.id = id;
    m.sender = sender;
    m.body = body;
    m.ts = net::now_ms();
    m.state = is_me(sender) ? 's' : 'r';
    receive(conv, m);
  }

  // Any message for the store (signed copies from peer sync included).
  bool receive(const std::string& conv, const store::Message& m) {
    bool viewing = _mode == Mode::Chat && apps::current() == this && conv == _conv_id;
    if (!store::conversation(conv)) store::note_conversation(conv, title_for(conv), 0);
    if (!store::add(conv, m, !viewing && !is_me(m.sender))) {
      if (viewing) {  // maybe a signed copy replaced a cut-short push
        reload();
        draw_chat();
      }
      return false;  // seen it already
    }
    ui::set_unread(store::unread_total());
    if (!is_me(m.sender)) receipts::message_arrived(conv, m.id);  // signed at once, or at unlock
    if (viewing) {
      reload();
      _scroll = 0;
      draw_chat();
    } else if (apps::current() == this && _mode == Mode::List) {
      draw_list();
    }
    return true;
  }

  // Pages of MSG_SYNC until Station has nothing more for us. Each request
  // confirms (`ack`) the messages stored from the previous reply: Station
  // keeps them pending until then, so a reply lost on the radio (or one
  // that arrived after a retry and was dropped as stale) comes again instead
  // of being lost. Duplicates are dropped by id.
  void catch_up(int round = 0, std::vector<std::string> ack = {}) {
    if (!account::paired() || (_catching && round == 0)) return;
    _catching = true;
    net::Request req;
    req.svc = "DISPATCH";
    req.op = "MSG_SYNC";
    req.use_tree = true;
    req.tree = waylink::Value::make_map();
    req.tree.set("username", waylink::Value::of_text(account::username()));
    req.tree.set("messages", waylink::Value::make_array());
    waylink::Value acks = waylink::Value::make_array();
    for (const auto& id : ack) acks.push(waylink::Value::of_text(id));
    req.tree.set("ack", acks);
    rpc::ask_background_request(std::move(req), [this, round](net::Result r, waylink::Reply& reply) {
      if (r != net::Result::Ok) {
        _catching = false;
        return;
      }
      const waylink::Value* pending = reply.payload().get("pending");
      std::vector<std::string> got;
      if (pending && pending->type == waylink::Value::Array) {
        for (const auto& m : pending->items) {
          receive(m.text("id"), m.text("conversation_id"), m.text("sender"), m.text("body"));
          got.push_back(m.text("id"));
        }
      }
      if (!got.empty()) Serial.printf("dispatch: caught up %u message(s)\n", static_cast<unsigned>(got.size()));
      // Confirm these (and fetch more) — until a round brings nothing.
      if (!got.empty() && round + 1 < 20) {
        catch_up(round + 1, std::move(got));
        return;
      }
      _catching = false;
    });
  }

  // Sends the oldest queued message if Station is in reach. One at a time;
  // `force` skips the retry wait (just composed).
  void flush_outbox(bool force) {
    if (_sending || store::outbox().empty() || !account::paired() || !net::station_known()) return;
    if (!force && _retry_at && static_cast<int32_t>(millis() - _retry_at) < 0) return;
    store::Outgoing o = store::outbox().front();
    _sending = true;
    if (apps::current() == this && _mode == Mode::Chat) ui::footer("Sending...", ui::kLive);
    // Retries are safe: the message id is ours, Station keeps one copy.
    // Just composed (force): the person is watching. Retries: background.
    net::Request req;
    req.svc = "DISPATCH";
    req.op = "MSG_SEND";
    req.fields = send_fields(o);
    req.attempts = 2;
    req.timeout_ms = 8000;
    req.ts = o.signed_t;
    req.asked = force;
    rpc::ask(std::move(req),
              [this, o](net::Result r, waylink::Reply& reply) {
                _sending = false;
                if (r == net::Result::Ok && reply.payload().flag("ok")) {
                  store::outbox_sent(o.id, reply.payload().text("conversation_id", o.conv));
                  _retry_at = 0;
                  Serial.printf("dispatch: sent %s%s (%u still queued)\n", o.id.c_str(),
                                reply.payload().flag("signed") ? " signed" : "",
                                static_cast<unsigned>(store::outbox().size()));
                } else if (r == net::Result::Error) {
                  // Station refused it (unknown person, not a member...): retrying
                  // won't help. Kept in the conversation, marked, with the reason.
                  store::outbox_failed(o.id, reply.error);
                  Serial.printf("dispatch: %s refused: %s\n", o.id.c_str(), reply.error.c_str());
                } else {
                  _retry_at = millis() + kRetryMs;
                  if (!_retry_at) _retry_at = 1;
                }
                refresh_view();
              });
  }

  void receipt_arrived(const std::string& conv) {
    if (apps::current() == this && _mode == Mode::Chat && conv == _conv_id) draw_chat();
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
    if (refresh && net::station_known()) {
      _station_offset = 0;
      fetch_convs();
    }
  }

  // Merges a page of Station's conversation list into the store.
  void fetch_convs() {
    if (_convs_req) return;
    ui::footer("Checking Station...", ui::kLive);
    _convs_req = rpc::ask(
        "DISPATCH", "MSG_CONVS", {Field::num("offset", _station_offset)},
        [this](net::Result r, waylink::Reply& reply) {
          _convs_req = 0;
          if (r != net::Result::Ok) {
            _list_note = std::string("Station: ") + (r == net::Result::Error ? reply.error : net::describe(r));
          } else {
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
          if (apps::current() == this && _mode == Mode::List) draw_list();
        });
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
    } else if (!net::station_known()) {
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
    if (contacts::all().empty() && net::station_known()) refresh_contacts();
    draw_pick();
  }

  void refresh_contacts() {
    if (_contacts_loading) return;
    _contacts_loading = true;
    _pick_note = "Loading contacts...";
    contacts::refresh([this](net::Result r) {
      _contacts_loading = false;
      _pick_note = r == net::Result::Ok ? "" : std::string("Couldn't refresh: ") + net::describe(r);
      if (apps::current() == this && _mode == Mode::Pick) draw_pick();
    });
  }

  void draw_pick() {
    std::vector<std::string> rows;
    for (const auto& c : contacts::all()) rows.push_back(c.name + "  (" + c.username + ")");
    rows.push_back("  Refresh contacts");
    ui::list(rows, _pick_sel, _pick_top);
    std::string foot = _pick_note.empty() ? "press: choose   roll left: back" : _pick_note;
    if (_pick_note.empty() && contacts::all().empty())
      foot = "No saved contacts yet - Station needed once";
    ui::footer(foot, _pick_note.empty() ? ui::kMuted : _contacts_loading ? ui::kLive : ui::kWarn);
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
    reload();
    draw_chat();
    rpc::cancel(_history_req);  // still loading another conversation's
    _history_req = 0;
    if (net::station_known()) fetch_history(0);  // newest page: anything we missed
  }

  void reload() { _msgs = store::messages(_conv_id); }

  // A page of Station's history for this conversation into the store, then
  // redrawn if it's still on screen. `skip` = how many of the newest
  // messages to pass over; `older` = the person scrolled up for it.
  void fetch_history(size_t skip, bool older = false) {
    if (_history_req) return;
    ui::footer("Checking Station...", ui::kLive);
    std::vector<Field> f{Field::text("conversation_id", _conv_id), Field::num("skip", skip)};
    std::string conv = _conv_id;
    _history_req = rpc::ask("DISPATCH", "MSG_LIST", f, [this, conv, older](net::Result r, waylink::Reply& reply) {
      _history_req = 0;
      bool viewing = apps::current() == this && _mode == Mode::Chat && _conv_id == conv;
      if (r == net::Result::Error && reply.error == "not_a_member") {
        if (viewing) {
          _older = false;  // new conversation: Station has nothing yet
          draw_chat();
        }
        return;
      }
      if (r != net::Result::Ok) {
        if (viewing) {
          _chat_note = std::string("Station: ") + net::describe(r) + " - showing saved";
          draw_input();
        }
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
          store::add(conv, msg, false);
        }
      }
      if (!viewing) return;
      store::mark_read(conv);  // we're looking at it
      _older = reply.payload().flag("more");
      int before = static_cast<int>(chat_lines().size());
      reload();
      // Scrolled up for older ones: keep the same lines on screen.
      if (older) _scroll += static_cast<int>(chat_lines().size()) - before;
      draw_chat();
    });
  }

  std::vector<std::pair<std::string, uint16_t>> chat_lines() const {
    std::vector<std::pair<std::string, uint16_t>> lines;
    if (_older) lines.push_back({"  (roll up for older)", ui::kMuted});
    // "delivered" on this person's newest sent message once a receipt for
    // it is back (one line of state, not a mark on every message).
    int last_mine = -1;
    for (int i = 0; i < static_cast<int>(_msgs.size()); i++)
      if (is_me(_msgs[i].sender)) last_mine = i;
    for (int i = 0; i < static_cast<int>(_msgs.size()); i++) {
      const store::Message& m = _msgs[i];
      bool mine = is_me(m.sender);
      std::string text = (mine ? "me" : m.sender) + ": " + m.body;
      uint16_t color = mine ? ui::kTextDim : ui::kText;
      if (i == last_mine && m.state == 's' && receipts::delivered(m.id)) text += "  (delivered)";
      if (m.state == 'q') {
        text += "  (waiting)";
        color = ui::kMuted;
      } else if (m.state == 'p') {
        text += "  (passed on)";
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
    while (shown.size() > 3 && ui::text_width(shown) > ui::kWidth - 8)
      shown.erase(2, 1);
    ui::body_line(kHistoryRows, shown, ui::kLive);
    if (!_chat_note.empty()) {
      ui::footer(_chat_note, ui::kWarn);
    } else {
      std::string foot = std::to_string(_input.size()) + "/" + std::to_string(max_body()) +
                         "   Enter: send   roll left: back";
      if (!net::station_known()) foot += "   (offline: queued)";
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
        if (_input.size() < max_body()) _input.push_back(e.ch);
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
        } else if (_older && net::station_known()) {
          fetch_history(store::synced_count(_conv_id), /*older=*/true);
          return;
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
    store::note_conversation(_conv_id, _title, net::now_ms());
    store::Outgoing o{};
    o.id = store::new_id();
    o.conv = _conv_id;
    o.peer = _peer;
    o.body = body;
    // Signed now, while unlocked, so it can go out later whoever carries it.
    uint64_t now = net::now_ms() / 1000;
    o.signed_t = now ? now : 1;  // 1 = this Scout didn't know the time
    if (!certs::sign_dispatch(raw_id(o.id), o.conv, o.body, o.signed_t, o.sig, o.author_id)) {
      o.sig.clear();
      o.author_id.clear();
      o.signed_t = 0;
    }
    store::queue(o);
    peersync::hurry();  // an Outpost or Scout in range can take it now
    reload();
    _scroll = 0;
    draw_chat();
    flush_outbox(true);
  }

  // The longest body that still makes one packet for this conversation —
  // a signature costs ~80 bytes, a long name or room id a little more.
  size_t max_body() {
    bool signing = certs::can_sign();
    if (_max_conv == _conv_id && _max_signed == signing) return _max_body;
    store::Outgoing probe{};
    probe.id = std::string(32, '0');
    probe.conv = _conv_id;
    probe.peer = _peer;
    if (signing) {
      probe.sig = std::string(64, '\0');
      probe.author_id = std::string(16, '\0');
      probe.signed_t = 4000000000ULL;
    }
    size_t n = kMaxBody;
    for (; n > 1; n--) {
      probe.body.assign(n, 'x');
      // It has to fit going to Station (MSG_SEND) and between devices (sync);
      // same as server/services/sync/engine.py max_signed_body.
      if (net::encoded_size("DISPATCH", "MSG_SEND", send_fields(probe), probe.signed_t) <=
              waylink::kRadioMdu &&
          (!signing || peersync::largest_packet(_conv_id, _peer, n) <= waylink::kRadioMdu))
        break;
    }
    _max_conv = _conv_id;
    _max_signed = signing;
    _max_body = n;
    return n;
  }

  Mode _mode = Mode::List;
  uint32_t _retry_at = 0;
  bool _catching = false, _sending = false, _contacts_loading = false;
  uint32_t _convs_req = 0, _history_req = 0;  // requests out (one of each at a time)
  std::string _max_conv;
  bool _max_signed = false;
  size_t _max_body = kMaxBody;

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
  net::send(RNS::Bytes(), waylink::encode_msg_ack(net::status().node_id.c_str(),
                                                  net::kStationNodeId, msg.rid, msg.message_id));
  instance().receive(msg.message_id, msg.conversation_id, msg.sender, msg.body);
}

void apps::catch_up_chat() { instance().catch_up(); }

bool apps::deliver_message(const std::string& conv, const store::Message& m) {
  return instance().receive(conv, m);
}

void apps::flush_outbox(bool force) { instance().flush_outbox(force); }

void apps::receipt_arrived(const std::string& conv) { instance().receipt_arrived(conv); }
