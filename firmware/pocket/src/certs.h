// Offline identity on the Scout (roadmap D2, docs/identity.md "Offline
// identity (target)").
//
// - The **community key** (Station's public key) is pinned the first time
//   this Scout hears it after pairing, and never silently replaced.
// - Certificates signed by it — this person's identity, this device's
//   signing key, the same for every contact, and revocations — are fetched
//   while Station is in reach and kept in flash, so people can be checked
//   with Station gone.
// - The **signing key** (Ed25519) authors this person's messages (D3). It is
//   separate from the Reticulum network identity, which must keep working
//   while the Scout is locked (receiving, Beacon alerts). With a PIN set the
//   signing key is stored encrypted with a key derived from the PIN and is
//   only in memory while unlocked.
//
// Files: /wp_certs (owner-tagged text), /wp_sigkey (key, maybe PIN-wrapped),
// /wp_sigpub (its public half, readable while locked).
#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace certs {

struct Cert {
  std::string kind;  // "id" | "dev" | "rev"
  uint64_t n = 0;    // serial
  std::string i;     // identity id (16 raw bytes)          id, dev
  std::string u;     // username                             id, dev
  std::string dn;    // display name                         id
  std::string p;     // signing public key (32 raw bytes)    dev
  std::string d;     // Reticulum identity hash (16 bytes)   dev
  uint64_t t = 0;    // issued (s)
  uint64_t x = 0;    // expires (s)                          id, dev
  uint64_t r = 0;    // serial revoked                       rev
  std::string s;     // community signature (64 raw bytes)
};

void load();       // after mount_storage + account::load, before start_radio
bool self_test();  // canonical bytes + Ed25519 against the pinned vector
// Call every loop(): fetches one missing/stale certificate at a time while
// Station is in reach; writes changes once storage is free.
void loop();
// True once nothing is left to fetch (sync waits for this, so messages from
// contacts aren't refused for a certificate that's still on its way).
bool idle();

// -- the signing key --
bool have_key();       // exists (maybe locked)
bool key_unlocked();   // usable now
void unlock(const std::string& pin);  // after a correct PIN (also creates the key)
void lock();                          // wipe it from memory
void rewrap(const std::string& pin);  // PIN set/changed ("" = removed)
std::string sign(const std::string& message);  // 64 bytes, "" if locked
const std::string& signing_public();

// Signed Dispatch messages (roadmap D3; server/services/identity/objects.py).
// True when a message can be signed right now: key unlocked and this
// device holds a current certificate. Otherwise messages go unsigned (the
// pre-D3 path, accepted by Station from this paired device).
bool can_sign();
// oid: 16 raw bytes; conv: conversation id (dm:<a>:<b> or room:...);
// t: signed time in seconds (1 when unknown). Fills the 64-byte signature
// and the device certificate serial.
bool sign_dispatch(const std::string& oid, const std::string& conv, const std::string& body,
                   uint64_t t, std::string& sig, uint64_t& serial);

// -- lookups (only certificates that verify, unexpired, not revoked) --
const Cert* identity(const std::string& username);
std::vector<const Cert*> devices(const std::string& username);
bool revoked(uint64_t serial);
// Whose device certificate `serial` is ("" when unknown here / not valid).
std::string device_owner(uint64_t serial);
// Checks a signed Dispatch message with cached certificates only (offline,
// whoever carried it). "" when genuine, else an error code (same codes as
// Station: unknown_certificate, certificate_revoked, bad_signature...).
std::string verify_dispatch(const std::string& oid, const std::string& author, uint64_t serial,
                            const std::string& conv, const std::string& body, uint64_t t,
                            const std::string& sig);

struct Status {
  bool root = false;            // community key pinned
  bool root_conflict = false;   // Station offered a different key
  bool mine = false;            // our identity + device cert valid
  uint64_t mine_until = 0;      // earliest expiry of those (s)
  int contacts = 0, contacts_verified = 0;  // contacts with a valid identity certificate
};
Status status();

void clear();  // unpaired / different account: forget certificates and key

}  // namespace certs
