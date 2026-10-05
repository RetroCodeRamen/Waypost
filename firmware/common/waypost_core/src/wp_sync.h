// Peer sync — the C++ side of server/services/sync/engine.py, shared by the
// Scout and the Outpost. "Objects this node knows that the other may not":
// HELLO / SUM / WANT / PUT, a 16-way tree of object-id prefixes with 8-byte
// XOR fingerprints, objects one per packet, every one verified on arrival.
//
// A device supplies an ObjectSet (what it holds and how it checks and keeps
// new objects) and a way to ask its peer (an Ask); the engine does the rest.
#pragma once

#include <functional>
#include <string>
#include <vector>

#include "waylink_cbor.h"

namespace wp {

// A signed dispatch.msg (server/services/identity/objects.py).
struct Obj {
  std::string o;  // object id, 16 raw bytes (message id = hex)
  std::string u;  // author's username (from their certificate)
  std::string a;  // author's identity id, 16 raw bytes
  std::string v;  // conversation id
  std::string b;  // body
  std::string s;  // signature, 64 raw bytes
  uint64_t t;     // signed time (s) — a plain aggregate (brace-initialised)
};

// What a node holds, in the shape scopes need (no bodies).
struct Ref {
  std::string oid, author, conv;
};

// Scopes: "*" everything, "u:<name>" a person (author or party to a direct
// conversation), "c:<id>" one conversation (rooms).
bool in_scope(const std::string& scope, const std::string& author, const std::string& conv);
bool wants(const std::vector<std::string>& interests, const std::string& author, const std::string& conv);
std::vector<std::string> parties(const std::string& author, const std::string& conv);

class ObjectSet {
 public:
  virtual ~ObjectSet() = default;
  virtual std::vector<std::string> interests() = 0;
  virtual std::vector<Ref> refs() = 0;
  virtual bool get(const std::string& oid, Obj& out) = 0;
  // Verify, then keep. "" (kept, or already here: `created` says which) or
  // an error code (bad_signature, unknown_identity, ...).
  virtual std::string put(const Obj& obj, bool& created) = 0;
  // Whose identity id this is ("" when unknown here).
  virtual std::string owner_of(const std::string& identity_id) = 0;
  // The peer took (or already had) this object of ours.
  virtual void handed_over(const std::string& /*oid*/) {}

  std::vector<std::string> oids(const std::string& scope);
  std::vector<std::string> held_scopes(const std::vector<std::string>& interests);
};

waylink::Value to_wire(const Obj& obj);
bool from_wire(const waylink::Value& w, ObjectSet& set, Obj& obj);

struct Result {
  bool ok = true;  // false: the peer stopped answering (carries on next time)
  int pulled = 0, pushed = 0, rejected = 0, requests = 0;
};

// Ask the peer: true with the reply (which may be an error reply), false
// when it didn't answer.
using Ask = std::function<bool(const char* op, const waylink::Value& payload, waylink::Reply& out)>;

// Reconcile with one peer. `reply_dest`: this node's 16-byte destination,
// sent in HELLO so the peer can answer (a Reticulum packet doesn't say who
// sent it); "" when the peer already knows how to reach us.
Result sync_with(ObjectSet& set, const char* role, const std::string& reply_dest, const Ask& ask);

// Answer a peer's SYNC request. Fills `out`; returns false when it's an
// error reply.
bool respond(ObjectSet& set, const char* role, const std::string& op, const waylink::Value& payload,
             waylink::Value& out);

// The biggest packet a signed message with a `body_len`-byte body to `conv`
// takes in peer sync (PUT, or a WANT reply), between the longest node ids.
size_t largest_sync_packet(const std::string& author, const std::string& conv, size_t body_len);

// The longest body (bytes, ≤140) a signed message by `author` to `conv`
// may have and still travel every way in one packet: signed MSG_SEND to
// Station and peer sync. Same as server/services/sync/engine.py
// max_signed_body.
size_t max_signed_body(const std::string& author, const std::string& conv);

}  // namespace wp
