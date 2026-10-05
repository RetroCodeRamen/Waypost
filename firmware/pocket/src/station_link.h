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

// Two steps, in this order:
//   mount_storage()  — synchronous; then load the account/contacts files;
//   start_radio()    — LoRa, Reticulum, identity on a background task.
// Storage (microStore/LittleFS) isn't safe for two tasks at once: loading
// files while the radio task started Reticulum once left the radio stuck
// part-way, so nothing else may touch files until ready().
//
// Threading: until ready(), only the background task touches Reticulum;
// after, only the main loop does. Everything below that needs the radio
// returns NotReady / false / "" until then.
bool mount_storage();
void start_radio();
bool ready();   // radio, Reticulum, and identity are up
bool failed();  // radio init failed (ready() stays false)

// One line for a person ("12 s; slowest: Starting LoRa radio 11.2 s") plus a
// per-step breakdown, once ready() or failed(). Empty before that.
std::string boot_timing();

// Called repeatedly while waiting on Station (tick) and once when the wait
// ends (done) — main wires these to the title-bar spinner.
void set_busy_hooks(void (*tick)(), void (*done)());
// Call every loop(): runs Reticulum and the periodic re-announce.
void loop();

const std::string& node_id();   // e.g. "pocket-1-e75a"
const std::string& dest_hex();  // Scout's Reticulum destination hash

// This Scout's Reticulum (network) identity: 64-byte public key, 16-byte
// hash, and signing with it — used to prove a certificate request comes
// from this device (certs.*). Empty until ready().
RNS::Bytes identity_public_key();
RNS::Bytes identity_hash();
RNS::Bytes identity_sign(const RNS::Bytes& message);

// True when Station's path and identity are already known (cheap, no I/O).
bool station_known();
// Non-blocking: if Station's path isn't known, ask the network for it
// (throttled to once per 30 s). Paths aren't kept across reboots, and
// Station only announces now and then, so a fresh boot must ask.
void seek_station();

enum class Result { Ok, NoPath, Timeout, Error, NotReady };
const char* describe(Result r);

// Builds a request for a fresh (mid, rid) pair.
using Builder = std::function<RNS::Bytes(const std::string& mid, const std::string& rid)>;

// Sends and waits for the reply whose rid matches. Each attempt uses a
// fresh mid/rid (only safe for idempotent reads). `out.error` is set on
// Result::Error.
Result request(const Builder& build, waylink::Reply& out, int attempts, uint32_t timeout_ms);

// Convenience for generic ops: svc/op + flat payload, 3 attempts.
Result request(const char* svc, const char* op, const std::vector<waylink::Field>& payload,
               waylink::Reply& out, int attempts = 3, uint32_t timeout_ms = 6000,
               uint64_t ts = 0);
// The exact bytes such a request would be (for size checks before sending).
RNS::Bytes encode(const char* svc, const char* op, const std::vector<waylink::Field>& payload,
                  uint64_t ts = 0);

// Fire-and-forget (acks). False if Station isn't reachable.
bool send(const RNS::Bytes& payload);

// Wall-clock milliseconds, learned from Station's replies; 0 if never heard.
uint64_t now_ms();

// Unsolicited DISPATCH/MSG_PUSH messages, queued from the packet callback.
bool pop_incoming(waylink::IncomingChatMessage& out);
// Other unsolicited requests from Station (e.g. BEACON/BEACON_ALERT).
bool pop_event(waylink::Reply& out);

}  // namespace station_link
