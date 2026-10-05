// The Outpost as a full Waypost node (roadmap D5): it keeps signed messages
// in flash, checks them with certificates cached from Station, syncs with
// Station, Scouts and other Outposts (firmware/common/waypost_core), and
// delivers to people nearby — Scouts that synced with it recently, and
// people signed in on its Wi-Fi page (outpost_web.*).
#pragma once

#include <string>
#include <vector>

#include "waylink_cbor.h"
#include "wp_objects.h"
#include "wp_sync.h"

namespace oobj {

void load();  // after the filesystem is up
void set_self_node(const std::string& node);  // this Outpost's node id (outpost-1-xxxx)
void loop();  // certificates, Station sync, pushes to Scouts in range — one step at a time
void handle_request(const waylink::Reply& req);  // a peer's SYNC request

wp::CertCache& certs();
size_t count();

// -- for the Wi-Fi page --
struct Conversation {
  std::string id, with;  // with: the other person (direct conversations)
  uint64_t last_t = 0;
  std::string last_body;
  size_t count = 0;
};
std::vector<Conversation> conversations_for(const std::string& user);
// Messages only (oldest first); `delivered`, if given, gets the ids of
// messages that have a delivery receipt.
std::vector<wp::Obj> messages(const std::string& conv, size_t max,
                              std::vector<std::string>* delivered = nullptr);
// A message written on the Wi-Fi page, already checked against the
// signed-in session's key. "" when kept.
std::string add_local(const wp::Obj& obj);
// Station hasn't vouched for this key (yet)? Used to tell the person.
bool vouched(const std::string& username, const std::string& public_key);

}  // namespace oobj
