// The Scout's own copy of its messages: conversations, history, and an
// outbox — so Dispatch works with Station out of reach (read history,
// compose; queued messages go out when a path appears). Roadmap D1,
// docs/network-model.md.
//
// Files (LittleFS):
//   /wp_index     "#owner\t<user>", then  id \t title \t ts \t unread
//   /wp_outbox    "#owner\t<user>", then  id \t conv \t peer \t ts \t body
//   /wp_c_<hash>  one per conversation:   id \t sender \t ts \t state \t note \t body
// Text fields are escaped (\\ \t \n). Everything belongs to one account and
// is wiped when the account changes, like contacts.
//
// Storage isn't safe for two tasks at once (see station_link.h): until the
// radio task is done (ready() or failed()), changes stay in RAM and loop()
// writes them afterwards. Conversation files are only read once safe.
#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace store {

struct Message {
  std::string id, sender, body;
  uint64_t ts = 0;  // wall-clock ms; 0 = not known yet
  // 'r' received (or history from Station), 's' sent (Station has it),
  // 'q' queued in the outbox, 'f' failed for good (note says why).
  char state = 'r';
  std::string note;
};

// Plain aggregates (brace-initialised): no default member values.
struct Conversation {
  std::string id, title;
  uint64_t ts;
  int unread;
};

struct Outgoing {
  std::string id, conv, peer, body;  // peer set for direct messages
  uint64_t ts;                       // queued at (wall ms, 0 = unknown)
  // Signed by this person's signing key (roadmap D3); empty sig = unsigned.
  std::string sig;     // 64 raw bytes
  uint64_t serial;     // device certificate serial
  uint64_t signed_t;   // signed time (s), sent as the envelope ts
};

void load();  // after mount_storage + account::load, before start_radio
void loop();  // call every loop(): writes deferred changes when safe
bool files_safe();

// -- conversations (newest first) --
const std::vector<Conversation>& conversations();
const Conversation* conversation(const std::string& id);
// Creates or updates (title if given, ts if newer); keeps unread.
void note_conversation(const std::string& id, const std::string& title, uint64_t ts);
void mark_read(const std::string& id);
int unread_total();

// -- messages --
// Oldest first, including this conversation's queued outbox entries.
// Needs files_safe() (returns only queued ones otherwise).
std::vector<Message> messages(const std::string& conv);
// How many messages Station already gave us for this conversation (for
// MSG_LIST's skip). Needs files_safe().
size_t synced_count(const std::string& conv);
// Adds unless a message with this id is already stored. True if new.
// `unread` bumps the conversation's unread count when new.
bool add(const std::string& conv, const Message& m, bool unread);

// -- outbox --
std::string new_id();  // 128 random bits, 32 hex chars
// Adds to the outbox (o.id from new_id(); o.ts set here).
const Outgoing& queue(Outgoing o);
const std::vector<Outgoing>& outbox();
// Station has it: moves it into the conversation (Station's conversation
// id, in case it differs) as sent.
void outbox_sent(const std::string& id, const std::string& station_conv);
// Station refused it for good: kept in the conversation, marked failed.
void outbox_failed(const std::string& id, const std::string& reason);

void clear();  // account changed or unpaired: forget everything

// Line-file helpers shared with other saved data (Beacon alerts).
std::string escape(const std::string& s);
std::string unescape(const std::string& s);
std::vector<std::string> split_tabs(const std::string& line);
std::vector<std::string> read_lines(const char* path);

}  // namespace store
