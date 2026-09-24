// Minimal CBOR (RFC 8949) codec for exactly the Waylink Envelope shape used
// by BOARD_SYNC — not a general-purpose CBOR library. Waypost's Python side
// (shared/protocol/envelope.py) encodes with cbor2, whose default dumps()
// emits definite-length maps/arrays/strings; this decoder does not support
// indefinite-length items because cbor2 never produces them for the plain
// dict/list/str/int/bool/None payloads this protocol uses.
#pragma once

// Must precede microReticulum/Bytes.h: see main.cpp's include-order comment
// (microStore's own headers need <string> included before they are).
#include <string>
#include <vector>

#include <microReticulum/Bytes.h>

namespace waylink {

// -- Encoding: build a BOARD_SYNC request Envelope as CBOR bytes --

struct OutgoingNote {
  std::string id;
  std::string body;
  std::string signature;   // empty => encoded as CBOR null
  bool has_signature = false;
};

// Field order matches shared/protocol/envelope.py's Envelope dataclass
// (v, mid, rid, src, dst, svc, op, flags, ts, ttl, payload); decode on the
// Python side is key-based (dict.get), so order isn't load-bearing there,
// but matching it keeps the two sides easy to compare by eye.
RNS::Bytes encode_board_sync_request(
    const char* src,
    const char* dst,
    const std::string& mid,
    const std::string& rid,
    uint32_t ttl,
    const char* display_name,          // nullptr => CBOR null
    const std::vector<OutgoingNote>& notes);

// 16 lowercase hex chars, matching shared/protocol/envelope.py's new_id()
// (uuid4().hex[:16]) closely enough for uniqueness — mid/rid only need to
// be unique per request, not cryptographically unguessable.
std::string new_hex_id();

// OUTPOST_CLAIM request: redeem a Station-generated pairing code, carrying
// this Outpost's own destination hash so Station can learn_route() it
// before replying (see server/services/auth/pairing.py's module
// docstring for why that ordering matters).
RNS::Bytes encode_outpost_claim_request(
    const char* src,
    const char* dst,
    const std::string& mid,
    const std::string& rid,
    uint32_t ttl,
    const std::string& code,
    const std::string& own_transport_dest,
    const char* display_name);  // nullptr => CBOR null

// -- Decoding: pull what OutpostNode.sync_corkboard needs out of the reply --

struct PendingNote {
  std::string id;
  std::string body;
  std::string signature;
  bool has_signature = false;
};

struct SyncReplyResult {
  bool parsed = false;      // outer envelope map parsed at all
  std::string rid;          // for correlating with the request that was sent
  bool ok = false;
  bool error = false;
  std::string error_msg;
  std::vector<PendingNote> pending;
};

// data/len is the raw CBOR-encoded Envelope received back from Station.
// Returns false only on malformed CBOR; a well-formed error reply still
// returns true with result.error set. Reused as-is for OUTPOST_CLAIM
// replies too — same ok/error/rid shape; `pending` just stays empty since
// a claim reply has no "pending" key, and unrecognized keys are skipped.
bool decode_sync_reply(const uint8_t* data, size_t len, SyncReplyResult& result);

}  // namespace waylink
