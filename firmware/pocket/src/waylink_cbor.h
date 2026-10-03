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

// BEACON_SYNC request: upload queued walk-up emergency pushes. Push-only,
// deliberately — see main.cpp's comment on why this firmware never exposes
// a walk-up "clear" (anonymously silencing a real active alert is a
// materially different risk than anonymously reporting one). Station
// attributes every ingested push to this Outpost's own claimed identity,
// never to anything in the payload (server/services/beacon/service.py's
// sync()) — no author field needed here.
struct OutgoingBeaconPush {
  std::string mid;
  std::string title;
  std::string body;
  std::string severity;  // "emergency" | "urgent" | "advisory"
};

RNS::Bytes encode_beacon_sync_request(
    const char* src,
    const char* dst,
    const std::string& mid,
    const std::string& rid,
    uint32_t ttl,
    const std::vector<OutgoingBeaconPush>& pending);

// CORE/PING — lightweight round-trip to prove Waylink over Reticulum (no binding).
RNS::Bytes encode_ping_request(
    const char* src,
    const char* dst,
    const std::string& mid,
    const std::string& rid,
    uint32_t ttl);

// DISPATCH/MSG_SEND — first Pocket-class send op (requires device binding on Station).
RNS::Bytes encode_msg_send_request(
    const char* src,
    const char* dst,
    const std::string& mid,
    const std::string& rid,
    uint32_t ttl,
    const char* sender,
    const char* peer,
    const char* body);

// DISPATCH/MSG_PUSH delivery ack. Station's handle_rpc
// (server/services/dispatch/service.py) correlates purely by the
// envelope's src (who sent it) + payload["id"] (the message id), not by
// rid -- but we echo rid anyway to match every other reply in this
// protocol. flags = RESPONSE only (no ERROR).
RNS::Bytes encode_msg_ack(
    const char* src,
    const char* dst,
    const std::string& rid,
    const std::string& message_id);

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
  // BOARD_SYNC only — whether Station has this Outpost claimed (walk-up
  // code or auto-claim). Absent (stays false) on other reply shapes, e.g.
  // OUTPOST_CLAIM's own reply, which doesn't carry this key.
  bool claimed = false;
  // DISPATCH/MSG_SEND reply — server-assigned message id when present.
  std::string message_id;
};

// data/len is the raw CBOR-encoded Envelope received back from Station.
// Returns false only on malformed CBOR; a well-formed error reply still
// returns true with result.error set. Reused as-is for OUTPOST_CLAIM
// replies too — same ok/error/rid shape; `pending` just stays empty since
// a claim reply has no "pending" key, and unrecognized keys are skipped.
// Also reused as-is for BEACON_SYNC replies (`{ok, ingested, active}`) —
// `ingested`/`active` are simply skipped as unrecognized keys; the walk-up
// UI only needs to know whether the sync succeeded at all.
bool decode_sync_reply(const uint8_t* data, size_t len, SyncReplyResult& result);

// An unsolicited DISPATCH/MSG_PUSH delivered live (not a reply Scout is
// waiting on) — Station pushes one of these whenever someone messages a
// user Scout's node_id is bound to. Payload shape is
// server/services/dispatch/service.py's _message_payload(): deliberately
// small for LoRa (no created_at/delivery_state).
struct IncomingChatMessage {
  bool parsed = false;  // true only if this really is a DISPATCH/MSG_PUSH request
  std::string rid;
  std::string message_id;      // payload.message.id -- echo in the ack
  std::string conversation_id;
  std::string sender;
  std::string body;
};

// Returns true only for a well-formed DISPATCH/MSG_PUSH request envelope
// (svc=="DISPATCH", op=="MSG_PUSH", REQUEST flag set). Anything else
// (an unmatched reply, a different op/service) returns false -- the
// caller should just ignore the packet, the same way WaylinkGateway
// ignores a response with no matching handler server-side.
bool decode_msg_push(const uint8_t* data, size_t len, IncomingChatMessage& result);

}  // namespace waylink
