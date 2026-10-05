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
// `node`. Blocking; one request at a time.
Result with(const RNS::Bytes& dest, const std::string& node);

// An unsolicited SYNC request from a peer (station_link::pop_event): answer it.
void handle(const waylink::Reply& request);

// Call every loop(): syncs with Station while it's in reach (every few
// minutes) and with contacts whose Scouts are in range.
void loop();

}  // namespace peersync
