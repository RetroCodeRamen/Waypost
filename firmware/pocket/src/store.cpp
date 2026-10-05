#include "store.h"

#include <algorithm>
#include <cstdio>

#include <Arduino.h>
#include <microReticulum.h>

#include "account.h"
#include "station_link.h"

namespace store {
namespace {

const char* const kIndexPath = "/wp_index";
const char* const kOutboxPath = "/wp_outbox";
const size_t kMaxMessages = 200;      // per conversation, newest kept
const size_t kMaxConversations = 60;  // oldest dropped (never one with queued mail)

std::vector<Conversation> g_convs;
std::vector<Outgoing> g_outbox;
bool g_index_dirty = false;
bool g_outbox_dirty = false;

// Messages added while storage wasn't safe yet.
struct Pending {
  std::string conv;
  Message msg;
};
std::vector<Pending> g_pending;
std::vector<std::string> g_wipe;  // files to remove once safe

// -- text helpers ---------------------------------------------------------------

std::string esc(const std::string& s) {
  std::string out;
  out.reserve(s.size());
  for (char c : s) {
    if (c == '\\') out += "\\\\";
    else if (c == '\t') out += "\\t";
    else if (c == '\n') out += "\\n";
    else out += c;
  }
  return out;
}

std::string unesc(const std::string& s) {
  std::string out;
  out.reserve(s.size());
  for (size_t i = 0; i < s.size(); i++) {
    if (s[i] == '\\' && i + 1 < s.size()) {
      char n = s[++i];
      out += n == 't' ? '\t' : n == 'n' ? '\n' : n;
    } else {
      out += s[i];
    }
  }
  return out;
}

std::vector<std::string> split(const std::string& line) {
  std::vector<std::string> f;
  size_t start = 0;
  while (true) {
    size_t t = line.find('\t', start);
    f.push_back(line.substr(start, t == std::string::npos ? std::string::npos : t - start));
    if (t == std::string::npos) break;
    start = t + 1;
  }
  return f;
}

std::vector<std::string> lines_of(const char* path) {
  std::vector<std::string> out;
  RNS::Bytes raw;
  if (RNS::Utilities::OS::read_file(path, raw) == 0) return out;
  std::string s(reinterpret_cast<const char*>(raw.data()), raw.size());
  size_t pos = 0;
  while (pos < s.size()) {
    size_t nl = s.find('\n', pos);
    out.push_back(s.substr(pos, nl == std::string::npos ? std::string::npos : nl - pos));
    pos = nl == std::string::npos ? s.size() : nl + 1;
  }
  return out;
}

uint64_t to_u64(const std::string& s) { return strtoull(s.c_str(), nullptr, 10); }

std::string hex_of(const std::string& raw) {
  static const char* d = "0123456789abcdef";
  std::string out;
  for (unsigned char c : raw) {
    out += d[c >> 4];
    out += d[c & 15];
  }
  return out;
}

std::string bytes_of(const std::string& hex) {
  std::string out;
  for (size_t i = 0; i + 1 < hex.size(); i += 2)
    out += static_cast<char>(strtoul(hex.substr(i, 2).c_str(), nullptr, 16));
  return out;
}

std::string owner_line() { return "#owner\t" + account::username(); }

// /wp_c_<FNV-1a of the conversation id>: LittleFS names are short.
std::string conv_path(const std::string& conv) {
  uint32_t h = 2166136261u;
  for (unsigned char c : conv) {
    h ^= c;
    h *= 16777619u;
  }
  char buf[20];
  snprintf(buf, sizeof(buf), "/wp_c_%08x", static_cast<unsigned>(h));
  return buf;
}

// Unknown times (0) sort last: they're things just written on this Scout.
uint64_t sort_key(const Message& m) { return m.ts ? m.ts : UINT64_MAX; }

// -- conversation files -----------------------------------------------------------

std::vector<Message> read_conv(const std::string& conv) {
  std::vector<Message> out;
  for (const auto& line : lines_of(conv_path(conv).c_str())) {
    auto f = split(line);
    if (f.size() < 6) continue;
    Message m;
    m.id = f[0];
    m.sender = unesc(f[1]);
    m.ts = to_u64(f[2]);
    m.state = f[3].empty() ? 'r' : f[3][0];
    m.note = unesc(f[4]);
    m.body = unesc(f[5]);
    out.push_back(std::move(m));
  }
  return out;
}

void write_conv(const std::string& conv, const std::vector<Message>& msgs) {
  std::string out;
  size_t first = msgs.size() > kMaxMessages ? msgs.size() - kMaxMessages : 0;
  for (size_t i = first; i < msgs.size(); i++) {
    const auto& m = msgs[i];
    out += m.id + "\t" + esc(m.sender) + "\t" + std::to_string(m.ts) + "\t" + std::string(1, m.state) +
           "\t" + esc(m.note) + "\t" + esc(m.body) + "\n";
  }
  RNS::Utilities::OS::write_file(conv_path(conv).c_str(), RNS::Bytes(out));
}

bool insert(std::vector<Message>& msgs, const Message& m) {
  for (auto& x : msgs) {
    if (x.id != m.id) continue;
    // Same message again. A queued/failed copy of ours being confirmed by
    // Station's history is an upgrade; anything else is a duplicate.
    if (x.state == 'f' && m.state != 'f') x = m;
    return false;
  }
  msgs.push_back(m);
  std::stable_sort(msgs.begin(), msgs.end(),
                   [](const Message& a, const Message& b) { return sort_key(a) < sort_key(b); });
  return true;
}

// -- index + outbox -------------------------------------------------------------

Conversation* find(const std::string& id) {
  for (auto& c : g_convs)
    if (c.id == id) return &c;
  return nullptr;
}

void sort_convs() {
  std::stable_sort(g_convs.begin(), g_convs.end(),
                   [](const Conversation& a, const Conversation& b) { return a.ts > b.ts; });
}

bool has_queued(const std::string& conv) {
  return std::any_of(g_outbox.begin(), g_outbox.end(), [&](const Outgoing& o) { return o.conv == conv; });
}

void trim_convs() {
  while (g_convs.size() > kMaxConversations) {
    auto victim = std::find_if(g_convs.rbegin(), g_convs.rend(),
                               [](const Conversation& c) { return !has_queued(c.id); });
    if (victim == g_convs.rend()) return;
    g_wipe.push_back(conv_path(victim->id));
    g_convs.erase(std::next(victim).base());
  }
}

void save_index() {
  std::string out = owner_line() + "\n";
  for (const auto& c : g_convs)
    out += esc(c.id) + "\t" + esc(c.title) + "\t" + std::to_string(c.ts) + "\t" +
           std::to_string(c.unread) + "\n";
  RNS::Utilities::OS::write_file(kIndexPath, RNS::Bytes(out));
}

void save_outbox() {
  std::string out = owner_line() + "\n";
  for (const auto& o : g_outbox)
    out += o.id + "\t" + esc(o.conv) + "\t" + esc(o.peer) + "\t" + std::to_string(o.ts) + "\t" +
           esc(o.body) + "\t" + hex_of(o.sig) + "\t" + std::to_string(o.serial) + "\t" +
           std::to_string(o.signed_t) + "\n";
  RNS::Utilities::OS::write_file(kOutboxPath, RNS::Bytes(out));
}

void apply(const Pending& p) {
  auto msgs = read_conv(p.conv);
  if (insert(msgs, p.msg)) write_conv(p.conv, msgs);
}

}  // namespace

std::string escape(const std::string& s) { return esc(s); }
std::string unescape(const std::string& s) { return unesc(s); }
std::vector<std::string> split_tabs(const std::string& line) { return split(line); }
std::vector<std::string> read_lines(const char* path) { return lines_of(path); }

bool files_safe() { return station_link::ready() || station_link::failed(); }

void load() {
  g_convs.clear();
  g_outbox.clear();
  auto index = lines_of(kIndexPath);
  auto outbox = lines_of(kOutboxPath);
  bool mine = account::paired() && !index.empty() && index[0] == owner_line();
  if (!mine) {
    // Another account's messages (or none): start clean. Safe here — the
    // radio task hasn't started yet.
    if (!index.empty()) {
      for (size_t i = 1; i < index.size(); i++) {
        auto f = split(index[i]);
        if (!f.empty()) RNS::Utilities::OS::remove_file(conv_path(unesc(f[0])).c_str());
      }
      RNS::Utilities::OS::remove_file(kIndexPath);
      Serial.println("store: messages belong to another account, discarded");
    }
    RNS::Utilities::OS::remove_file(kOutboxPath);
    return;
  }
  for (size_t i = 1; i < index.size(); i++) {
    auto f = split(index[i]);
    if (f.size() < 4) continue;
    g_convs.push_back({unesc(f[0]), unesc(f[1]), to_u64(f[2]), atoi(f[3].c_str())});
  }
  if (!outbox.empty() && outbox[0] == owner_line()) {
    for (size_t i = 1; i < outbox.size(); i++) {
      auto f = split(outbox[i]);
      if (f.size() < 5) continue;
      Outgoing o{f[0], unesc(f[1]), unesc(f[2]), unesc(f[4]), to_u64(f[3]), "", 0, 0};
      if (f.size() >= 8) {  // signed (D3); older lines have 5 fields
        o.sig = bytes_of(f[5]);
        o.serial = to_u64(f[6]);
        o.signed_t = to_u64(f[7]);
      }
      g_outbox.push_back(o);
    }
  }
  sort_convs();
  Serial.printf("store: %u conversation(s), %u queued\n", static_cast<unsigned>(g_convs.size()),
                static_cast<unsigned>(g_outbox.size()));
}

void loop() {
  if (!files_safe()) return;
  for (const auto& path : g_wipe) RNS::Utilities::OS::remove_file(path.c_str());
  g_wipe.clear();
  for (const auto& p : g_pending) apply(p);
  g_pending.clear();
  if (g_index_dirty) {
    g_index_dirty = false;
    save_index();
  }
  if (g_outbox_dirty) {
    g_outbox_dirty = false;
    save_outbox();
  }
}

const std::vector<Conversation>& conversations() { return g_convs; }

const Conversation* conversation(const std::string& id) { return find(id); }

void note_conversation(const std::string& id, const std::string& title, uint64_t ts) {
  Conversation* c = find(id);
  if (!c) {
    g_convs.push_back({id, title.empty() ? id : title, ts, 0});
    trim_convs();
  } else {
    if (!title.empty()) c->title = title;
    if (ts > c->ts) c->ts = ts;
  }
  sort_convs();
  g_index_dirty = true;
}

void mark_read(const std::string& id) {
  Conversation* c = find(id);
  if (c && c->unread) {
    c->unread = 0;
    g_index_dirty = true;
  }
}

int unread_total() {
  int n = 0;
  for (const auto& c : g_convs) n += c.unread;
  return n;
}

std::vector<Message> messages(const std::string& conv) {
  std::vector<Message> msgs;
  if (files_safe()) msgs = read_conv(conv);
  for (const auto& p : g_pending)
    if (p.conv == conv) insert(msgs, p.msg);
  for (const auto& o : g_outbox) {
    if (o.conv != conv) continue;
    Message m;
    m.id = o.id;
    m.sender = account::username();
    m.body = o.body;
    m.ts = 0;  // shown last, in the order written
    m.state = 'q';
    msgs.push_back(m);
  }
  return msgs;
}

size_t synced_count(const std::string& conv) {
  size_t n = 0;
  for (const auto& m : read_conv(conv))
    if (m.state == 'r' || m.state == 's') n++;
  return n;
}

bool add(const std::string& conv, const Message& m, bool unread) {
  bool fresh;
  if (files_safe()) {
    auto msgs = read_conv(conv);
    fresh = insert(msgs, m);
    if (fresh) write_conv(conv, msgs);
  } else {
    fresh = std::none_of(g_pending.begin(), g_pending.end(),
                         [&](const Pending& p) { return p.msg.id == m.id; });
    if (fresh) g_pending.push_back({conv, m});
  }
  if (!fresh) return false;
  note_conversation(conv, "", m.ts);
  if (unread) {
    find(conv)->unread++;
    g_index_dirty = true;
  }
  return true;
}

std::string new_id() {
  char buf[33];
  for (int i = 0; i < 4; i++) snprintf(buf + i * 8, 9, "%08x", static_cast<unsigned>(esp_random()));
  return std::string(buf, 32);
}

const Outgoing& queue(Outgoing o) {
  if (o.id.empty()) o.id = new_id();
  o.ts = station_link::now_ms();
  g_outbox.push_back(o);
  g_outbox_dirty = true;
  note_conversation(o.conv, "", o.ts);
  return g_outbox.back();
}

const std::vector<Outgoing>& outbox() { return g_outbox; }

namespace {

void settle(const std::string& id, const std::string& conv_override, char state,
            const std::string& note) {
  auto it = std::find_if(g_outbox.begin(), g_outbox.end(), [&](const Outgoing& o) { return o.id == id; });
  if (it == g_outbox.end()) return;
  Outgoing o = *it;
  g_outbox.erase(it);
  g_outbox_dirty = true;
  std::string conv = conv_override.empty() ? o.conv : conv_override;
  if (conv != o.conv) {
    const Conversation* old = find(o.conv);
    note_conversation(conv, old ? old->title : "", 0);
  }
  Message m;
  m.id = o.id;
  m.sender = account::username();
  m.body = o.body;
  m.ts = station_link::now_ms();
  m.state = state;
  m.note = note;
  add(conv, m, false);
}

}  // namespace

void outbox_sent(const std::string& id, const std::string& station_conv) {
  settle(id, station_conv, 's', "");
}

void outbox_failed(const std::string& id, const std::string& reason) { settle(id, "", 'f', reason); }

void clear() {
  for (const auto& c : g_convs) g_wipe.push_back(conv_path(c.id));
  g_wipe.push_back(kIndexPath);
  g_wipe.push_back(kOutboxPath);
  g_convs.clear();
  g_outbox.clear();
  g_pending.clear();
  g_index_dirty = g_outbox_dirty = false;
  loop();  // now, if storage is free
}

}  // namespace store
