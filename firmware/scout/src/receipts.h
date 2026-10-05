// Delivery receipts (dispatch.rcpt, roadmap D4; docs/protocol.md "Peer sync").
//
// When a message from someone else lands on this Scout, it signs a receipt
// with the person's identity key. The receipt travels by peer sync like a
// message, so the sender learns "delivered" whichever way it went — via
// Station, an Outpost, or straight Scout to Scout. Receipts from others for
// this person's messages arrive the same way.
//
// While the PIN keeps the key locked, a new receipt waits unsigned and is
// signed at unlock (loop()). Saved in /wp_rcpts, owner-tagged like the store.
// UI task only.
#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace receipts {

struct Receipt {
  std::string oid;        // 16 raw bytes (wp::receipt_oid(m, user))
  std::string m;          // the message's object id, 16 raw bytes
  std::string conv;       // the message's conversation
  std::string user;       // who confirms (the receipt's author)
  std::string author_id;  // their identity id, 16 raw bytes ("" until signed)
  std::string sig;        // 64 raw bytes; "" = not signed yet (key locked)
  uint64_t t;             // when it arrived (s); 1 = time unknown
};

void load();   // after account::load()
void loop();   // every frame: signs waiting receipts once the key is open, saves
void clear();  // signed out / another person

// A message from someone else landed here (id: 32 hex = a signed object).
void message_arrived(const std::string& conv, const std::string& message_id_hex);
// A receipt that arrived by sync, already verified. True when it's new here.
bool add(const Receipt& r);

const std::vector<Receipt>& all();
const Receipt* find(const std::string& oid);
// Someone other than this person confirmed the message (32 hex id).
bool delivered(const std::string& message_id_hex);

}  // namespace receipts
