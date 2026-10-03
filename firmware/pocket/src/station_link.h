// Scout <-> Station over Reticulum/LoRa: radio bring-up, identity, and
// Waylink request/reply. Every app talks to Station through here.
#pragma once

#include <functional>
#include <string>
#include <vector>

#include <microReticulum/Bytes.h>

#include "waylink_cbor.h"

namespace station_link {

extern const char* const kStationNodeId;  // "station"

// Brings up LittleFS, the LoRa interface, Reticulum, and Scout's persistent
// identity/destination, then announces. Returns false if the radio failed.
// `progress` (optional) is called before each stage with a label and 0-100.
using Progress = void (*)(const char* step, int percent);
bool setup(Progress progress = nullptr);

// Called repeatedly while waiting on Station (tick) and once when the wait
// ends (done) — main wires these to the title-bar spinner.
void set_busy_hooks(void (*tick)(), void (*done)());
// Call every loop(): runs Reticulum and the periodic re-announce.
void loop();

const std::string& node_id();   // e.g. "pocket-1-e75a"
const std::string& dest_hex();  // Scout's Reticulum destination hash

// True when Station's path and identity are already known (cheap, no I/O).
bool station_known();

enum class Result { Ok, NoPath, Timeout, Error };
const char* describe(Result r);

// Builds a request for a fresh (mid, rid) pair.
using Builder = std::function<RNS::Bytes(const std::string& mid, const std::string& rid)>;

// Sends and waits for the reply whose rid matches. Each attempt uses a
// fresh mid/rid (only safe for idempotent reads). `out.error` is set on
// Result::Error.
Result request(const Builder& build, waylink::Reply& out, int attempts, uint32_t timeout_ms);

// Convenience for generic ops: svc/op + flat payload, 3 attempts.
Result request(const char* svc, const char* op, const std::vector<waylink::Field>& payload,
               waylink::Reply& out, int attempts = 3, uint32_t timeout_ms = 8000);

// Fire-and-forget (acks). False if Station isn't reachable.
bool send(const RNS::Bytes& payload);

// Unsolicited DISPATCH/MSG_PUSH messages, queued from the packet callback.
bool pop_incoming(waylink::IncomingChatMessage& out);

}  // namespace station_link
