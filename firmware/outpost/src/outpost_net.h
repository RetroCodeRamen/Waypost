// Outpost <-> any peer over Reticulum: requests with rid-matched replies,
// incoming requests queued for the main loop, and the wall clock learned
// from Station. Used by peer sync (outpost_objects.*); the older Corkboard /
// Beacon / claim exchanges in main.cpp keep their own helpers.
#pragma once

#include <string>
#include <vector>

#include <microReticulum.h>

#include "waylink_cbor.h"

namespace onet {

void attach(RNS::Reticulum* reticulum, RNS::Destination* self, const std::string* node_id);

// From the destination's packet callback, first. True when the packet was
// for this module (a peer's request, or the reply it's waiting for).
bool on_packet(const RNS::Bytes& data);

bool has_path(const RNS::Bytes& dest);
// One request to the peer at `dest`; true with the reply (maybe an error
// reply), false when it didn't answer.
bool request(const RNS::Bytes& dest, const char* dst_node, const char* svc, const char* op,
             const waylink::Value& payload, waylink::Reply& out, int attempts = 2, uint32_t timeout_ms = 6000);
bool send_to(const RNS::Bytes& dest, const RNS::Bytes& bytes);
bool pop_request(waylink::Reply& out);

RNS::Bytes station_dest();
std::string self_dest();  // 16 raw bytes
uint64_t now_s();         // wall seconds learned from Station, 0 until then
// Station had a path but stopped answering: out of reach for a while.
bool station_quiet();

}  // namespace onet
