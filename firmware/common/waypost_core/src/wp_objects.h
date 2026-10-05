// Certificates and signed objects — the C++ side of
// server/services/identity/{certs,objects,keys}.py, shared by the Scout and
// the Outpost. Signed bytes are canonical (`name:len:value` per field), not
// CBOR, so both languages produce them identically; pinned vectors in the
// Python tests are checked by self_test() at boot.
#pragma once

// <string> first: microStore headers (via microReticulum) need it.
#include <string>
#include <vector>

#include <microReticulum/Bytes.h>

#include "waylink_cbor.h"

namespace wp {

// -- bytes ----------------------------------------------------------------------
std::string raw(const RNS::Bytes& b);
RNS::Bytes bytes(const std::string& s);
std::string hex(const std::string& raw);
std::string unhex(const std::string& hex);
std::string lower(std::string s);
std::string escape(const std::string& s);    // \\ \t \n for tab-separated lines
std::string unescape(const std::string& s);
std::vector<std::string> split_tabs(const std::string& line);
std::string dm_id(const std::string& a, const std::string& b);  // dm:<a>:<b>, sorted, lower-case

// -- crypto -------------------------------------------------------------------------
bool ed25519_ok(const std::string& pub, const std::string& sig, const std::string& msg);
std::string identity_id_of(const std::string& public_key);  // SHA-256(p)[:16]

// -- certificates -----------------------------------------------------------------------
struct Cert {
  std::string kind;  // "id" | "rev"
  uint64_t n = 0;    // serial
  std::string i;     // identity id (16 raw bytes)        id
  std::string u;     // username                           id
  std::string dn;    // display name                       id
  std::string p;     // identity public key (32 bytes)     id
  uint64_t t = 0;    // issued (s)
  uint64_t x = 0;    // expires (s)                        id
  uint64_t r = 0;    // serial revoked                     rev
  std::string s;     // community signature (64 raw bytes)
};

bool canonical(const Cert& c, std::string& out);
bool from_value(const waylink::Value& v, Cert& c);

// The bytes a dispatch.msg signature covers.
std::string dispatch_bytes(const std::string& oid, const std::string& user, const std::string& author_id,
                           const std::string& conv, const std::string& body, uint64_t t);

// Delivery receipts (dispatch.rcpt, server/services/identity/objects.py):
// signed by the recipient when a message lands. The id is derived, so every
// device of the same person makes the same receipt for a message.
std::string receipt_oid(const std::string& message_oid, const std::string& recipient);
std::string receipt_bytes(const std::string& oid, const std::string& user, const std::string& author_id,
                          const std::string& conv, const std::string& message_oid, uint64_t t);

// Everything this node has been told by Station's community key, checked.
class CertCache {
 public:
  using Clock = uint64_t (*)();  // wall seconds, 0 = unknown
  explicit CertCache(Clock now) : _now(now) {}

  std::string root;            // community public key, pinned the first time
  bool root_conflict = false;  // Station later offered a different one
  std::vector<Cert> certs;     // verified id + rev certificates

  // Pin (first time) or compare. False when it differs from the pinned key.
  bool offer_root(const std::string& pk);
  bool verify(const Cert& c) const;
  // Verified: keep (newest id per person; every revocation). Returns false
  // when it didn't verify.
  bool add(const Cert& c);

  bool current(const Cert& c) const;            // not revoked, not expired
  bool fresh(const Cert* c, uint64_t renew_before_s) const;
  bool revoked(uint64_t serial) const;
  const Cert* identity(const std::string& username) const;
  const Cert* identity_by_id(const std::string& id) const;
  std::string owner_of(const std::string& id) const;  // "" when unknown
  // "" when genuine, else unknown_identity / identity_revoked /
  // certificate_expired / bad_signature.
  std::string verify_dispatch(const std::string& oid, const std::string& author, const std::string& id,
                              const std::string& conv, const std::string& body, uint64_t t,
                              const std::string& sig) const;
  // The same for a receipt, plus its rules: the derived id, and a direct
  // conversation's receipt comes from one of its two people.
  std::string verify_receipt(const std::string& oid, const std::string& author, const std::string& id,
                             const std::string& conv, const std::string& message_oid, uint64_t t,
                             const std::string& sig) const;

  // Tab-separated lines (root first) for a flash file; load() re-verifies.
  std::string serialize(const std::string& owner) const;
  void load(const std::vector<std::string>& lines, const std::string& owner);

 private:
  Clock _now;
};

// Pinned vectors from server/tests (certificates, objects). True when the
// C++ bytes and signatures match Python's exactly.
bool self_test();

}  // namespace wp
