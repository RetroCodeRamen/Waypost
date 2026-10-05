// The net task: everything Reticulum, on core 0. It owns the radio, the
// network identity and every packet; nothing else calls microReticulum's
// transport. Other tasks talk to it only through this API, which never
// waits on the network:
//
//   request()   queue a Waylink request (to Station or a peer); returns an id
//   result()    collect the reply for that id once it's in
//   send()      fire-and-forget packet (acks, replies to peers)
//   incoming()  pushes and unsolicited requests (chat, Beacon, peer sync)
//   status()    a snapshot: ready, Station reachable, clock, ...
//
// docs/scout-firmware-architecture.md §4.
#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include <microReticulum/Bytes.h>

#include "radio.h"
#include "waylink_cbor.h"
#include "wp_caps.h"

namespace net {

extern const char* const kStationNodeId;  // "station"

enum class Result : uint8_t { Ok, NoPath, Timeout, Error, NotReady };
const char* describe(Result r);

struct Request {
  RNS::Bytes dest;          // 16-byte destination hash; empty = Station
  std::string dst_node;     // envelope dst; empty = "station"
  std::string svc, op;
  // Payload: flat fields (most requests) or a tree (peer sync).
  std::vector<waylink::Field> fields;
  waylink::Value tree;
  bool use_tree = false;
  uint64_t ts = 0;          // envelope ts (signed messages)
  int attempts = 3;
  uint32_t timeout_ms = 6000;  // per attempt
};

// Queues a request. Returns its id (never 0).
uint32_t request(Request r);
// Shorthand for a request to Station with flat fields.
uint32_t request(const char* svc, const char* op, std::vector<waylink::Field> fields,
                 int attempts = 3, uint32_t timeout_ms = 6000, uint64_t ts = 0);
// True once the request is finished; fills `r` and `out` and forgets it.
bool result(uint32_t id, Result& r, waylink::Reply& out);
// No longer interested (the reply, if it comes, is dropped).
void forget(uint32_t id);
// Requests not finished yet (for the busy indicator).
int pending();

// Fire-and-forget: one packet to `dest` (empty = Station). Dropped if no path.
void send(const RNS::Bytes& dest, const RNS::Bytes& payload);

struct Incoming {
  enum Kind : uint8_t { Chat, Event } kind = Event;
  waylink::IncomingChatMessage chat;  // Chat: a MSG_PUSH from Station
  waylink::Reply event;               // Event: a request nobody asked for (Beacon, SYNC)
};
bool incoming(Incoming& out);

// Ask for a path to `dest` if none is known; answers from a cache that the
// net task refreshes (has_path reads flash, ~45 ms — never per frame).
bool has_path(const RNS::Bytes& dest);

// A Waypost node heard announcing (roadmap D6): what it says it can do.
struct Peer {
  std::string dest_hex;
  wp::Caps caps;
  bool has_caps = false;  // an older node: only its marker
  std::string marker;     // WPOST-OUTPOST:<id> / WPOST-CLAIM:<id> / ""
  uint32_t heard_at = 0;  // millis()
  bool outpost() const { return (caps.role & wp::kRoleOutpost) || marker.compare(0, 6, "WPOST-") == 0; }
};

struct Status {
  bool ready = false, failed = false;
  bool station_known = false;  // path known and not gone quiet
  std::string node_id;         // e.g. "pocket-1-e75a"
  std::string dest_hex;        // this Scout's destination
  std::string boot;            // boot timing, once finished
  std::vector<std::string> outposts;  // Outposts heard announcing (dest hex)
  std::vector<Peer> nearby;           // every Waypost node heard, newest first
  radio::Stats radio;
};
Status status();
bool ready();
bool station_known();
// Wall clock in ms from Station's replies (0 until the first one).
uint64_t now_ms();
RNS::Bytes station_dest();

// Encoded size of a request, as it would go to Station (compose limits).
size_t encoded_size(const char* svc, const char* op, const std::vector<waylink::Field>& fields,
                    uint64_t ts);

void mount_storage();  // first: the apps load their files after it
void start();          // then: spawns the task

}  // namespace net
