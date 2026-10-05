// Capability records in Reticulum announces (roadmap D6) — the C++ side of
// shared/protocol/caps.py. A node's announce app_data is
//
//   <marker text> NUL <CBOR {r, s, st, n?}>
//
// where the marker is what older code reads (WPOST-CLAIM:/WPOST-OUTPOST:,
// empty for Station and Scouts). Scouts put no name on the air.
#pragma once

#include <cstdint>
#include <string>

#include <microReticulum/Bytes.h>

namespace wp {

constexpr uint32_t kRoleStation = 1, kRoleOutpost = 2, kRoleScout = 4;

constexpr uint32_t kSvcDispatch = 1u << 0, kSvcPostbox = 1u << 1, kSvcNoticeboard = 1u << 2,
                   kSvcBeacon = 1u << 3, kSvcFieldbook = 1u << 4, kSvcCommons = 1u << 5,
                   kSvcLocker = 1u << 6, kSvcRollcall = 1u << 7, kSvcCorkboard = 1u << 8,
                   kSvcTrailhead = 1u << 9, kSvcSignal = 1u << 10, kSvcSync = 1u << 11,
                   kSvcWifiPage = 1u << 12;

constexpr uint32_t kStNone = 0, kStSelf = 1, kStDirect = 2;

struct Caps {
  uint32_t role = 0, services = 0, station = kStNone;
  std::string name;  // Outposts only
};

RNS::Bytes caps_app_data(const std::string& marker, const Caps& caps);
// Splits an announce's app_data. False (marker still filled) when there's
// no record — an older node.
bool split_caps(const RNS::Bytes& app_data, std::string& marker, Caps& caps);

}  // namespace wp
