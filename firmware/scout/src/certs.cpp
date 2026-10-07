#include "certs.h"

#include <algorithm>
#include <cstdio>
#include <cstring>
#include <map>

#include <Arduino.h>
#include <SHA256.h>
#include <microReticulum.h>
#include <microReticulum/Cryptography/Ed25519.h>
#include <microReticulum/Cryptography/Token.h>

#include "account.h"
#include "wp_objects.h"
#include "contacts.h"
#include "net.h"
#include "tasks.h"
#include "store.h"

namespace certs {
namespace {

using waylink::Field;

const char* const kCertsPath = "/wp_certs";
const char* const kKeyPath = "/wp_idkey";
const char* const kPubPath = "/wp_idpub";
const char* const kOldKeyPath = "/wp_sigkey";  // per-device signing key, 2026-10-04 (gone)
const char* const kOldPubPath = "/wp_sigpub";

const char* const kMagic = "WAYPOST-CERT-1\n";

const uint64_t kRenewBeforeS = 7ULL * 24 * 3600;  // matches Station's RENEW_BEFORE_SEC
const uint32_t kRefreshMs = 6UL * 3600UL * 1000UL;  // revocations
const uint32_t kPinIterations = 10000;

// -- helpers (shared code: firmware/common/waypost_core) ------------------------------

using wp::bytes;
using wp::hex;
using wp::lower;
using wp::raw;
using wp::unhex;

std::string u64be(uint64_t v) {
  std::string s(8, '\0');
  for (int i = 0; i < 8; i++) s[7 - i] = static_cast<char>((v >> (8 * i)) & 0xFF);
  return s;
}

// -- state ------------------------------------------------------------------------

uint64_t now_s();
wp::CertCache g_cache(&now_s);  // community key + verified certificates
bool g_dirty = false;

std::string g_pub;           // identity public key
std::string g_seed;          // identity key seed, only while unlocked
std::string g_key_file;      // /wp_idkey as read (maybe sealed)
bool g_key_dirty = false;
bool g_wipe = false;

std::vector<std::string> g_unknown_ids;  // authors seen in messages, to look up
uint32_t g_revs_at = 0;
uint32_t g_next_ms = 0;
bool g_idle = false;

uint64_t now_s() { return net::now_ms() / 1000ULL; }

bool fresh(const Cert* c) { return g_cache.fresh(c, kRenewBeforeS); }

void save() { RNS::Utilities::OS::write_file(kCertsPath, RNS::Bytes(g_cache.serialize(account::username()))); }

void add(const Cert& c) {
  if (!g_cache.add(c)) {
    Serial.printf("certs: %s #%llu does not verify, ignored\n", c.kind.c_str(),
                  static_cast<unsigned long long>(c.n));
    return;
  }
  Serial.printf("certs: verified %s %s #%llu\n", c.kind.c_str(), c.kind == "rev" ? "" : c.u.c_str(),
                static_cast<unsigned long long>(c.n));
  g_dirty = true;
}

// -- the identity key -------------------------------------------------------------

std::string public_of(const std::string& seed);
std::string public_of_seed(const std::string& seed) { return public_of(seed); }

// PBKDF2-HMAC-SHA256 (RFC 8018) for the PIN seal. A short PIN is guessable
// by anyone who reads the flash however slow this is; it stops casual
// reading, not a lab — and the identity key itself is only as strong as the
// password it came from anyway.
std::string pbkdf2(const std::string& pass, const std::string& salt, uint32_t iters, size_t len) {
  std::string out;
  SHA256 sha;
  const uint8_t* key = reinterpret_cast<const uint8_t*>(pass.data());
  for (uint32_t block = 1; out.size() < len; block++) {
    uint8_t u[32], t[32];
    std::string first = salt + u64be(block).substr(4);
    sha.resetHMAC(key, pass.size());
    sha.update(first.data(), first.size());
    sha.finalizeHMAC(key, pass.size(), u, sizeof(u));
    memcpy(t, u, sizeof(t));
    for (uint32_t i = 1; i < iters; i++) {
      sha.resetHMAC(key, pass.size());
      sha.update(u, sizeof(u));
      sha.finalizeHMAC(key, pass.size(), u, sizeof(u));
      for (int j = 0; j < 32; j++) t[j] ^= u[j];
    }
    out.append(reinterpret_cast<const char*>(t), sizeof(t));
  }
  out.resize(len);
  return out;
}

// /wp_idkey: "P" + seed (no PIN), or
//            "W" + salt(16) + iterations(4, BE) + Token(AES-256-CBC + HMAC)
std::string sealed_file(const std::string& seed, const std::string& pin) {
  uint32_t start = millis();
  std::string salt = raw(RNS::Cryptography::random(16));
  std::string dk = pbkdf2(pin, salt, kPinIterations, 64);
  RNS::Cryptography::Token token(bytes(dk), RNS::Type::Cryptography::Token::MODE_AES_256_CBC);
  std::string file = "W" + salt + u64be(kPinIterations).substr(4) + raw(token.encrypt(bytes(seed)));
  Serial.printf("certs: identity key sealed with the PIN (%lu ms)\n",
                static_cast<unsigned long>(millis() - start));
  return file;
}

// PBKDF2 takes about a second: on the crypto worker, never the UI task.
// Until it's done the old file stays (a power cut in between keeps the
// key under the old PIN, never lost).
void seal(const std::string& pin) {
  if (g_seed.empty()) return;
  if (pin.empty()) {
    g_key_file = "P" + g_seed;
    g_key_dirty = true;
    return;
  }
  std::string seed = g_seed;
  tasks::run(tasks::Worker::Crypto, [seed, pin] {
    std::string file = sealed_file(seed, pin);
    tasks::post([seed, file] {
      if (g_pub.empty() || public_of_seed(seed) != g_pub) return;  // signed out meanwhile
      g_key_file = file;
      g_key_dirty = true;
    });
  });
}

std::string public_of(const std::string& seed) {
  RNS::Cryptography::Ed25519PrivateKey key(bytes(seed));
  return raw(key.public_key()->public_bytes());
}

std::string my_id() { return g_pub.empty() ? "" : wp::identity_id_of(g_pub); }

// -- talking to Station (one request at a time, never waiting) ---------------------

using Res = net::Result;

bool g_busy = false;  // a request is out

// Finished: the next step soon if it went well, in a minute if not.
void stepped(Res r) {
  g_busy = false;
  if (r == Res::Ok) {
    g_next_ms = millis() + 1500;  // keep going, without hogging the radio
  } else {
    Serial.printf("certs: Station request failed (%s), retry in 1 min\n", net::describe(r));
    g_next_ms = millis() + 60000;
  }
  if (!g_next_ms) g_next_ms = 1;
}

void fetch_root() {
  rpc::ask_background("PROFILE", "CERT_ROOT", {}, [](Res r, waylink::Reply& reply) {
    if (r == Res::Ok) {
      std::string pk = reply.payload().bytes("pk");
      if (pk.size() != 32) {
        r = Res::Error;
      } else {
        bool first = g_cache.root.empty();
        if (!g_cache.offer_root(pk)) {
          Serial.println("certs: Station offered a DIFFERENT community key - kept the pinned one");
        } else if (first) {
          g_dirty = true;
          Serial.printf("certs: community key pinned %s\n", hex(pk).substr(0, 16).c_str());
        }
      }
    }
    stepped(r);
  });
}

// CERT_GET by username ("" = me) or identity id. A person Station has no
// key for yet ("no_identity_yet") isn't an error worth retrying soon.
void fetch_identity(const std::string& username, const std::string& id = "") {
  std::vector<Field> f;
  if (!id.empty()) f.push_back(Field::bytes("i", id));
  else if (!username.empty()) f.push_back(Field::text("u", username));
  rpc::ask_background("PROFILE", "CERT_GET", f, [](Res r, waylink::Reply& reply) {
    if (r == Res::Error) r = Res::Ok;  // unknown / no key yet: nothing to cache
    else if (r == Res::Ok) {
      Cert c;
      const waylink::Value* v = reply.payload().get("cert");
      if (v && from_value(*v, c)) add(c);
    }
    stepped(r);
  });
}

void fetch_revocations(uint64_t offset = 0, int page = 0) {
  rpc::ask_background("PROFILE", "CERT_REVOKED", {Field::num("offset", offset)},
            [offset, page](Res r, waylink::Reply& reply) {
              if (r != Res::Ok) {
                stepped(r);
                return;
              }
              const waylink::Value* list = reply.payload().get("revs");
              size_t n = 0;
              if (list && list->type == waylink::Value::Array) {
                for (const auto& v : list->items) {
                  Cert c;
                  if (from_value(v, c)) add(c);
                  n++;
                }
              }
              if (reply.payload().flag("more") && n > 0 && page + 1 < 20) {
                fetch_revocations(offset + n, page + 1);
                return;
              }
              g_revs_at = millis() | 1;
              stepped(Res::Ok);
            });
}

bool due(uint32_t at, uint32_t every) { return at == 0 || millis() - at > every; }

// Someone Station had nothing for (no key yet: they haven't signed in on
// the portal since keys came in) is asked about again after a while.
const uint32_t kRetryMissingMs = 10UL * 60UL * 1000UL;
std::map<std::string, uint32_t> g_tried;  // username / id -> millis of last attempt

bool try_now(const std::string& key) {
  auto it = g_tried.find(key);
  return it == g_tried.end() || millis() - it->second > kRetryMissingMs;
}

// Starts one request's worth of work. False when there was nothing to do.
bool step() {
  if (g_cache.root.empty()) return fetch_root(), true;
  const std::string& me = account::username();
  if (!fresh(identity(me)) && try_now(lower(me))) {
    g_tried[lower(me)] = millis();
    return fetch_identity(""), true;
  }
  for (const auto& c : contacts::all()) {
    if (!fresh(identity(c.username)) && try_now(lower(c.username))) {
      g_tried[lower(c.username)] = millis();
      return fetch_identity(c.username), true;
    }
  }
  while (!g_unknown_ids.empty()) {
    std::string id = g_unknown_ids.back();
    g_unknown_ids.pop_back();
    if (identity_by_id(id) || !try_now(hex(id))) continue;
    g_tried[hex(id)] = millis();
    return fetch_identity("", id), true;
  }
  if (due(g_revs_at, kRefreshMs)) return fetch_revocations(), true;
  return false;
}

void flush_files() {
  if (g_wipe) {
    g_wipe = false;
    RNS::Utilities::OS::remove_file(kCertsPath);
    RNS::Utilities::OS::remove_file(kKeyPath);
    RNS::Utilities::OS::remove_file(kPubPath);
  }
  if (g_key_dirty) {
    g_key_dirty = false;
    RNS::Utilities::OS::write_file(kPubPath, bytes(g_pub));
    RNS::Utilities::OS::write_file(kKeyPath, bytes(g_key_file));
  }
  if (g_dirty) {
    g_dirty = false;
    save();
  }
}

}  // namespace

// -- public ---------------------------------------------------------------------

std::string identity_id_of(const std::string& public_key) { return wp::identity_id_of(public_key); }

void load() {
  // The per-device signing key of 2026-10-04 is replaced by the identity key.
  RNS::Utilities::OS::remove_file(kOldKeyPath);
  RNS::Utilities::OS::remove_file(kOldPubPath);
  g_cache.load(account::paired() ? store::read_lines(kCertsPath) : std::vector<std::string>{},
               account::username());
  RNS::Bytes pub, key;
  if (account::paired()) {
    RNS::Utilities::OS::read_file(kPubPath, pub);
    RNS::Utilities::OS::read_file(kKeyPath, key);
  }
  g_pub = pub.size() == 32 ? raw(pub) : "";
  g_key_file = raw(key);
  g_seed.clear();
  if (!g_pub.empty() && g_key_file.size() == 33 && g_key_file[0] == 'P') g_seed = g_key_file.substr(1);
  if (g_pub.empty()) g_key_file.clear();
  Serial.printf("certs: %u certificate(s), community key %s, identity key %s\n",
                static_cast<unsigned>(g_cache.certs.size()), g_cache.root.empty() ? "not yet" : "pinned",
                g_pub.empty() ? "none" : !g_seed.empty() ? "ready" : "locked");
}

bool self_test() {
  bool ok = wp::self_test();
  Serial.printf("certs: self-test %s\n", ok ? "ok" : "FAILED");
  return ok;
}

void loop() {
  flush_files();
  if (g_busy || !account::paired() || !net::station_known()) return;
  if (g_next_ms && static_cast<int32_t>(millis() - g_next_ms) < 0) return;
  g_idle = false;
  if (step()) {
    g_busy = true;
  } else {
    g_idle = true;
    g_next_ms = millis() + 60000;  // nothing to do; look again in a minute
    if (!g_next_ms) g_next_ms = 1;
  }
}

// Without Station there's nothing to wait for: work with what's cached.
bool idle() { return g_idle || !net::station_known(); }

void set_identity(const std::string& seed, const std::string& pin) {
  g_seed = seed;
  g_pub = public_of(seed);
  seal(pin);
  Serial.printf("certs: identity %s\n", hex(my_id()).c_str());
}

bool have_key() { return !g_pub.empty(); }
bool key_unlocked() { return !g_seed.empty(); }

uint32_t g_lock_gen = 0;  // bumped by lock(): an unlock finishing after it is dropped

void unlock(const std::string& pin) {
  if (!g_seed.empty()) return;
  if (g_key_file.size() < 1 + 16 + 4 + 32 || g_key_file[0] != 'W') return;
  // PBKDF2 (~1 s): on the crypto worker; the key is usable when it posts back.
  std::string file = g_key_file, pub = g_pub;
  uint32_t gen = g_lock_gen;
  tasks::run(tasks::Worker::Crypto, [file, pub, pin, gen] {
    std::string salt = file.substr(1, 16);
    uint32_t iters = 0;
    for (int k = 0; k < 4; k++) iters = (iters << 8) | static_cast<uint8_t>(file[17 + k]);
    std::string dk = pbkdf2(pin, salt, iters, 64);
    RNS::Cryptography::Token token(bytes(dk), RNS::Type::Cryptography::Token::MODE_AES_256_CBC);
    RNS::Bytes sealed = bytes(file.substr(21));
    if (!token.verify_hmac(sealed)) {
      Serial.println("certs: identity key didn't open with this PIN");
      return;
    }
    std::string seed = raw(token.decrypt(sealed));
    if (public_of(seed) != pub) {
      Serial.println("certs: identity key doesn't match its public half");
      return;
    }
    tasks::post([seed, pub, gen] {
      if (gen != g_lock_gen || g_pub != pub) return;  // locked again / signed out meanwhile
      g_seed = seed;
      Serial.println("certs: identity key unlocked");
    });
  });
}

void lock() {
  if (!account::has_pin()) return;  // nothing protects it anyway
  g_lock_gen++;
  std::fill(g_seed.begin(), g_seed.end(), '\0');
  g_seed.clear();
}

void rewrap(const std::string& pin) { seal(pin); }

std::string sign(const std::string& message) {
  if (g_seed.empty()) return "";
  RNS::Cryptography::Ed25519PrivateKey key(bytes(g_seed));
  return raw(key.sign(bytes(message)));
}

const std::string& identity_public() { return g_pub; }

bool can_sign() { return !g_seed.empty(); }

bool sign_dispatch(const std::string& oid, const std::string& conv, const std::string& body,
                   uint64_t t, std::string& sig, std::string& author_id) {
  if (g_seed.empty() || oid.size() != 16) return false;
  author_id = my_id();
  sig = sign(wp::dispatch_bytes(oid, account::username(), author_id, conv, body, t));
  return sig.size() == 64;
}

bool sign_receipt(const std::string& oid, const std::string& conv, const std::string& m, uint64_t t,
                  std::string& sig, std::string& author_id) {
  if (g_seed.empty() || oid.size() != 16 || m.size() != 16) return false;
  author_id = my_id();
  sig = sign(wp::receipt_bytes(oid, account::username(), author_id, conv, m, t));
  return sig.size() == 64;
}

std::string verify_receipt(const std::string& oid, const std::string& author, const std::string& id,
                           const std::string& conv, const std::string& m, uint64_t t, const std::string& sig) {
  if (!g_pub.empty() && my_id() == id) {  // our own receipts coming back to us
    if (oid != wp::receipt_oid(m, author)) return "invalid_payload";
    return wp::ed25519_ok(g_pub, sig, wp::receipt_bytes(oid, author, id, conv, m, t)) ? "" : "bad_signature";
  }
  return g_cache.verify_receipt(oid, author, id, conv, m, t, sig);
}

const Cert* identity(const std::string& username) { return g_cache.identity(username); }

const Cert* identity_by_id(const std::string& id) { return g_cache.identity_by_id(id); }

bool revoked(uint64_t serial) { return g_cache.revoked(serial); }

std::string owner_of(const std::string& id) {
  if (id.size() != 16) return "";
  if (!g_pub.empty() && my_id() == id) return account::username();
  std::string who = g_cache.owner_of(id);
  if (who.empty() && std::find(g_unknown_ids.begin(), g_unknown_ids.end(), id) == g_unknown_ids.end() &&
      g_unknown_ids.size() < 16)
    g_unknown_ids.push_back(id);  // look it up next time Station is in reach
  return who;
}

std::string verify_dispatch(const std::string& oid, const std::string& author, const std::string& id,
                            const std::string& conv, const std::string& body, uint64_t t,
                            const std::string& sig) {
  if (!g_pub.empty() && my_id() == id) {  // our own messages coming back to us
    if (oid.size() != 16) return "bad_signature";
    return wp::ed25519_ok(g_pub, sig, wp::dispatch_bytes(oid, author, id, conv, body, t)) ? "" : "bad_signature";
  }
  return g_cache.verify_dispatch(oid, author, id, conv, body, t, sig);
}

Status status() {
  Status s;
  s.root = !g_cache.root.empty();
  s.root_conflict = g_cache.root_conflict;
  const Cert* id = identity(account::username());
  s.mine = id && !g_pub.empty() && id->p == g_pub;
  s.key_differs = id && !g_pub.empty() && id->p != g_pub;
  if (s.mine) s.mine_until = id->x;
  for (const auto& c : contacts::all()) {
    s.contacts++;
    if (identity(c.username)) s.contacts_verified++;
  }
  return s;
}

void clear() {
  g_cache.root.clear();
  g_cache.root_conflict = false;
  g_cache.certs.clear();
  std::fill(g_seed.begin(), g_seed.end(), '\0');
  g_seed.clear();
  g_pub.clear();
  g_key_file.clear();
  g_unknown_ids.clear();
  g_tried.clear();
  g_revs_at = 0;
  g_dirty = g_key_dirty = false;
  g_wipe = true;
  flush_files();  // files only: no Station requests from here
}

}  // namespace certs
