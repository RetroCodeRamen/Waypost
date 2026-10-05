// Identity on the Scout (docs/identity.md; roadmap D2, reworked 2026-10-05).
//
// - A person's **identity key** is derived from username + password at
//   login (kdf.*, same as server/services/identity/keys.py). It signs their
//   messages. With a PIN set it is stored sealed with a key derived from the
//   PIN and is only in memory while unlocked; without one it's stored as is.
//   The Reticulum network identity is separate and never sealed, so a locked
//   Scout still receives (messages, Beacon alerts).
// - The **community key** (Station's public key) is pinned the first time
//   this Scout hears it, and never silently replaced.
// - Certificates signed by it say "<username> is identity key p" for this
//   person, their contacts, and anyone whose message arrives; plus
//   revocations. Kept in flash, so people can be checked with Station gone.
//
// Files: /wp_certs (owner-tagged text), /wp_idkey (seed, maybe PIN-sealed),
// /wp_idpub (its public half, readable while locked).
#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include "wp_objects.h"

namespace certs {

using Cert = wp::Cert;  // firmware/common/waypost_core/src/wp_objects.h

void load();       // after mount_storage + account::load, before start_radio
bool self_test();  // canonical bytes + Ed25519 against the pinned vectors
// Call every loop(): fetches one missing/stale certificate at a time while
// Station is in reach; writes changes once storage is free.
void loop();
// True once nothing is left to fetch (sync waits for this, so messages from
// contacts aren't refused for a certificate that's still on its way).
bool idle();

// -- the identity key --
// After login: the seed derived from username + password (32 bytes),
// stored sealed with `pin` ("" = no PIN).
void set_identity(const std::string& seed, const std::string& pin);
bool have_key();       // exists (maybe locked)
bool key_unlocked();   // usable now
void unlock(const std::string& pin);  // after a correct PIN
void lock();                          // wipe it from memory
void rewrap(const std::string& pin);  // PIN set/changed ("" = removed)
std::string sign(const std::string& message);  // 64 bytes, "" if locked
const std::string& identity_public();
std::string identity_id_of(const std::string& public_key);  // SHA-256[:16]

// Signed Dispatch messages (server/services/identity/objects.py).
bool can_sign();
// oid: 16 raw bytes; conv: dm:<a>:<b> or room:...; t: signed time in s
// (1 when unknown). Fills the 64-byte signature and this person's identity id.
bool sign_dispatch(const std::string& oid, const std::string& conv, const std::string& body,
                   uint64_t t, std::string& sig, std::string& author_id);

// A delivery receipt for message `m` (16 raw bytes) in `conv`, by this
// person: fills the signature and their identity id. False when locked.
bool sign_receipt(const std::string& oid, const std::string& conv, const std::string& m, uint64_t t,
                  std::string& sig, std::string& author_id);
// Checks a receipt with cached certificates (offline), same codes as below.
std::string verify_receipt(const std::string& oid, const std::string& author, const std::string& id,
                           const std::string& conv, const std::string& m, uint64_t t, const std::string& sig);

// -- lookups (only certificates that verify, unexpired, not revoked) --
const Cert* identity(const std::string& username);
const Cert* identity_by_id(const std::string& id);
bool revoked(uint64_t serial);
// Whose identity id this is ("" when not known here yet — it will be
// fetched from Station when in reach).
std::string owner_of(const std::string& id);
// Checks a signed Dispatch message with cached certificates only (offline,
// whoever carried it). "" when genuine, else an error code (same codes as
// Station: unknown_identity, identity_revoked, bad_signature...).
std::string verify_dispatch(const std::string& oid, const std::string& author, const std::string& id,
                            const std::string& conv, const std::string& body, uint64_t t,
                            const std::string& sig);

struct Status {
  bool root = false;           // community key pinned
  bool root_conflict = false;  // Station offered a different key
  bool mine = false;           // Station vouches for this person's key
  bool key_differs = false;    // ...but for a different key (another password?)
  uint64_t mine_until = 0;
  int contacts = 0, contacts_verified = 0;  // contacts with a valid certificate
};
Status status();

void clear();  // signed out / different person: forget certificates and key

}  // namespace certs
