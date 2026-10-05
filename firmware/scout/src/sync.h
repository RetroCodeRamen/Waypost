// Peer sync on the Scout (roadmap D4) — the same SYNC protocol as
// server/services/sync/engine.py, with any peer: Station, an Outpost,
// another Scout. "Objects this node knows that the other may not."
//
// The Scout's objects are the signed Dispatch messages in its store
// (store::signed_refs). Its interests: its own person ("u:<me>") and the
// rooms it's in ("c:<id>"). Everything that arrives is checked with cached
// certificates (certs::verify_dispatch) before it's kept, whoever carried it.
#pragma once

#include <cstdint>
#include <string>

#include <microReticulum/Bytes.h>

#include "waylink_cbor.h"

namespace peersync {

struct Result {
  bool ok = true;  // false: the peer stopped answering (resumes next time)
  int pulled = 0, pushed = 0, rejected = 0, requests = 0;
};

// Reconcile with the peer at `dest` (16-byte destination hash), node id
// `node`. Blocking: the sync worker only (loop() starts it there).
Result with(const RNS::Bytes& dest, const std::string& node);

// An unsolicited SYNC request from a peer (net::incoming): answer it. UI task.
void handle(const waylink::Reply& request);

// The biggest packet a signed message to `conv` with a `body_len`-byte body
// takes in peer sync (PUT, or a WANT reply) — the compose limit checks it.
size_t largest_packet(const std::string& conv, const std::string& peer, size_t body_len);

// Something was just written: sync with peers in range at the next loop
// rather than waiting (Station gets it through the outbox).
void hurry();

// UI task, every frame: starts a sync (on the sync worker) with Station
// every few minutes while it's in reach, and with peers in range.
void loop();

}  // namespace peersync
