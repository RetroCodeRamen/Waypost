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
#include "contacts.h"
#include "station_link.h"
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

// -- bytes helpers ----------------------------------------------------------------

std::string raw(const RNS::Bytes& b) { return std::string(reinterpret_cast<const char*>(b.data()), b.size()); }
RNS::Bytes bytes(const std::string& s) {
  return RNS::Bytes(reinterpret_cast<const uint8_t*>(s.data()), s.size());
}

std::string hex(const std::string& s) {
  static const char* d = "0123456789abcdef";
  std::string out;
  for (unsigned char c : s) {
    out += d[c >> 4];
    out += d[c & 15];
  }
  return out;
}

std::string unhex(const std::string& h) {
  std::string out;
  for (size_t i = 0; i + 1 < h.size(); i += 2) out += static_cast<char>(strtoul(h.substr(i, 2).c_str(), nullptr, 16));
  return out;
}

std::string u64be(uint64_t v) {
  std::string s(8, '\0');
  for (int i = 0; i < 8; i++) s[7 - i] = static_cast<char>((v >> (8 * i)) & 0xFF);
  return s;
}

void put(std::string& out, const char* name, const std::string& v) {
  out += name;
  out += ':';
  out += static_cast<char>((v.size() >> 8) & 0xFF);
  out += static_cast<char>(v.size() & 0xFF);
  out += v;
}

// Same bytes as server/services/identity/certs.py canonical_bytes().
bool canonical(const Cert& c, std::string& out) {
  out = kMagic;
  if (c.kind == "id") {
    if (c.i.size() != 16 || c.p.size() != 32) return false;
    put(out, "k", c.kind), put(out, "n", u64be(c.n)), put(out, "i", c.i), put(out, "u", c.u);
    put(out, "dn", c.dn), put(out, "p", c.p), put(out, "t", u64be(c.t)), put(out, "x", u64be(c.x));
  } else if (c.kind == "rev") {
    put(out, "k", c.kind), put(out, "n", u64be(c.n)), put(out, "r", u64be(c.r)), put(out, "t", u64be(c.t));
  } else {
    return false;
  }
  return true;
}

// Same bytes as server/services/identity/objects.py canonical_bytes() for
// kind dispatch.msg.
std::string dispatch_bytes(const std::string& oid, const std::string& user, const std::string& author_id,
                           const std::string& conv, const std::string& body, uint64_t t) {
  std::string out = "WAYPOST-OBJ-1\n";
  put(out, "k", "dispatch.msg"), put(out, "o", oid), put(out, "u", user), put(out, "a", author_id);
  put(out, "v", conv), put(out, "b", body), put(out, "t", u64be(t));
  return out;
}

bool ed25519_ok(const std::string& pub, const std::string& sig, const std::string& msg) {
  if (pub.size() != 32 || sig.size() != 64) return false;
  return RNS::Cryptography::Ed25519PublicKey::from_public_bytes(bytes(pub))->verify(bytes(sig), bytes(msg));
}

bool verify_with(const std::string& root, const Cert& c) {
  std::string msg;
  if (root.size() != 32 || !canonical(c, msg)) return false;
  if (!ed25519_ok(root, c.s, msg)) return false;
  // An id certificate's id must be its key's: SHA-256(p)[:16].
  return c.kind != "id" || identity_id_of(c.p) == c.i;
}

bool from_value(const waylink::Value& v, Cert& c) {
  if (v.type != waylink::Value::Map) return false;
  c.kind = v.text("k");
  c.n = v.uint("n");
  c.i = v.bytes("i");
  c.u = v.text("u");
  c.dn = v.text("dn");
  c.p = v.bytes("p");
  c.t = v.uint("t");
  c.x = v.uint("x");
  c.r = v.uint("r");
  c.s = v.bytes("s");
  return !c.kind.empty();
}

std::string lower(std::string s) {
  for (auto& ch : s) ch = static_cast<char>(tolower(static_cast<unsigned char>(ch)));
  return s;
}

// -- state ------------------------------------------------------------------------

std::string g_root;          // community public key (32 bytes), pinned
bool g_root_conflict = false;
std::vector<Cert> g_certs;   // verified id/rev certificates
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

uint64_t now_s() { return station_link::now_ms() / 1000ULL; }

bool current(const Cert& c) {
  if (revoked(c.n)) return false;
  uint64_t now = now_s();
  return now == 0 || now < c.x;  // clock unknown: trust until we know better
}

bool fresh(const Cert* c) {
  if (!c) return false;
  uint64_t now = now_s();
  return now == 0 || c->x > now + kRenewBeforeS;
}

void save() {
  std::string out = "#owner\t" + account::username() + "\n";
  if (!g_root.empty()) out += "root\t" + hex(g_root) + "\n";
  for (const auto& c : g_certs) {
    out += "c\t" + c.kind + "\t" + std::to_string(c.n) + "\t" + hex(c.i) + "\t" + store::escape(c.u) + "\t" +
           store::escape(c.dn) + "\t" + hex(c.p) + "\t" + std::to_string(c.t) + "\t" + std::to_string(c.x) +
           "\t" + std::to_string(c.r) + "\t" + hex(c.s) + "\n";
  }
  RNS::Utilities::OS::write_file(kCertsPath, RNS::Bytes(out));
}

// Keep the newest identity certificate per person and every revocation;
// drop what's been revoked.
void add(const Cert& c) {
  if (!verify_with(g_root, c)) {
    Serial.printf("certs: %s #%llu does not verify, ignored\n", c.kind.c_str(),
                  static_cast<unsigned long long>(c.n));
    return;
  }
  if (c.kind == "rev") {
    if (std::any_of(g_certs.begin(), g_certs.end(), [&](const Cert& x) { return x.kind == "rev" && x.n == c.n; }))
      return;
    g_certs.push_back(c);
    g_certs.erase(std::remove_if(g_certs.begin(), g_certs.end(),
                                 [&](const Cert& x) { return x.kind != "rev" && x.n == c.r; }),
                  g_certs.end());
  } else {
    g_certs.erase(std::remove_if(g_certs.begin(), g_certs.end(),
                                 [&](const Cert& x) { return x.kind == "id" && lower(x.u) == lower(c.u); }),
                  g_certs.end());
    g_certs.push_back(c);
  }
  Serial.printf("certs: verified %s %s #%llu\n", c.kind.c_str(), c.kind == "rev" ? "" : c.u.c_str(),
                static_cast<unsigned long long>(c.n));
  g_dirty = true;
}

// -- the identity key -------------------------------------------------------------

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
void seal(const std::string& pin) {
  if (g_seed.empty()) return;
  if (pin.empty()) {
    g_key_file = "P" + g_seed;
  } else {
    uint32_t start = millis();
    std::string salt = raw(RNS::Cryptography::random(16));
    std::string dk = pbkdf2(pin, salt, kPinIterations, 64);
    RNS::Cryptography::Token token(bytes(dk), RNS::Type::Cryptography::Token::MODE_AES_256_CBC);
    g_key_file = "W" + salt + u64be(kPinIterations).substr(4) + raw(token.encrypt(bytes(g_seed)));
    Serial.printf("certs: identity key sealed with the PIN (%lu ms)\n",
                  static_cast<unsigned long>(millis() - start));
  }
  g_key_dirty = true;
}

std::string public_of(const std::string& seed) {
  RNS::Cryptography::Ed25519PrivateKey key(bytes(seed));
  return raw(key.public_key()->public_bytes());
}

// -- talking to Station -----------------------------------------------------------

using Res = station_link::Result;

Res fetch_root() {
  waylink::Reply reply;
  Res r = station_link::request("PROFILE", "CERT_ROOT", {}, reply);
  if (r != Res::Ok) return r;
  std::string pk = reply.payload().bytes("pk");
  if (pk.size() != 32) return Res::Error;
  if (g_root.empty()) {
    g_root = pk;
    g_dirty = true;
    Serial.printf("certs: community key pinned %s\n", hex(pk).substr(0, 16).c_str());
  } else if (pk != g_root) {
    // Never silently trust a new root: that would let any Station vouch
    // for anyone. Sign out + in again to accept a new Station.
    g_root_conflict = true;
    Serial.println("certs: Station offered a DIFFERENT community key - kept the pinned one");
  }
  return Res::Ok;
}

// CERT_GET by username ("" = me) or identity id. A person Station has no
// key for yet ("no_identity_yet") isn't an error worth retrying soon.
Res fetch_identity(const std::string& username, const std::string& id = "") {
  waylink::Reply reply;
  std::vector<Field> f;
  if (!id.empty()) f.push_back(Field::bytes("i", id));
  else if (!username.empty()) f.push_back(Field::text("u", username));
  Res r = station_link::request("PROFILE", "CERT_GET", f, reply);
  if (r == Res::Error) return Res::Ok;  // unknown / no key yet: nothing to cache
  if (r != Res::Ok) return r;
  Cert c;
  const waylink::Value* v = reply.payload().get("cert");
  if (v && from_value(*v, c)) add(c);
  return Res::Ok;
}

Res fetch_revocations() {
  uint64_t offset = 0;
  for (int page = 0; page < 20; page++) {
    waylink::Reply reply;
    Res r = station_link::request("PROFILE", "CERT_REVOKED", {Field::num("offset", offset)}, reply);
    if (r != Res::Ok) return r;
    const waylink::Value* list = reply.payload().get("revs");
    size_t n = 0;
    if (list && list->type == waylink::Value::Array) {
      for (const auto& v : list->items) {
        Cert c;
        if (from_value(v, c)) add(c);
        n++;
      }
    }
    offset += n;
    if (!reply.payload().flag("more") || n == 0) break;
  }
  g_revs_at = millis() | 1;
  return Res::Ok;
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

// One request's worth of work. Returns false when there was nothing to do.
bool step(Res& r) {
  if (g_root.empty()) return r = fetch_root(), true;
  const std::string& me = account::username();
  if (!fresh(identity(me)) && try_now(lower(me))) {
    g_tried[lower(me)] = millis();
    return r = fetch_identity(""), true;
  }
  for (const auto& c : contacts::all()) {
    if (!fresh(identity(c.username)) && try_now(lower(c.username))) {
      g_tried[lower(c.username)] = millis();
      return r = fetch_identity(c.username), true;
    }
  }
  while (!g_unknown_ids.empty()) {
    std::string id = g_unknown_ids.back();
    g_unknown_ids.pop_back();
    if (identity_by_id(id) || !try_now(hex(id))) continue;
    g_tried[hex(id)] = millis();
    return r = fetch_identity("", id), true;
  }
  if (due(g_revs_at, kRefreshMs)) return r = fetch_revocations(), true;
  return false;
}

void flush_files() {
  if (!store::files_safe()) return;
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

std::string identity_id_of(const std::string& public_key) {
  return raw(RNS::Identity::full_hash(bytes(public_key))).substr(0, 16);
}

void load() {
  g_root.clear();
  g_certs.clear();
  // The per-device signing key of 2026-10-04 is replaced by the identity key.
  RNS::Utilities::OS::remove_file(kOldKeyPath);
  RNS::Utilities::OS::remove_file(kOldPubPath);
  auto lines = store::read_lines(kCertsPath);
  bool mine = account::paired() && !lines.empty() && lines[0] == "#owner\t" + account::username();
  if (mine) {
    for (size_t k = 1; k < lines.size(); k++) {
      auto f = store::split_tabs(lines[k]);
      if (f.size() == 2 && f[0] == "root") g_root = unhex(f[1]);
      if (f.size() < 11 || f[0] != "c") continue;
      Cert c;
      c.kind = f[1];
      c.n = strtoull(f[2].c_str(), nullptr, 10);
      c.i = unhex(f[3]);
      c.u = store::unescape(f[4]);
      c.dn = store::unescape(f[5]);
      c.p = unhex(f[6]);
      c.t = strtoull(f[7].c_str(), nullptr, 10);
      c.x = strtoull(f[8].c_str(), nullptr, 10);
      c.r = strtoull(f[9].c_str(), nullptr, 10);
      c.s = unhex(f[10]);
      if (verify_with(g_root, c)) g_certs.push_back(c);  // old formats simply don't verify
    }
  }
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
                static_cast<unsigned>(g_certs.size()), g_root.empty() ? "not yet" : "pinned",
                g_pub.empty() ? "none" : !g_seed.empty() ? "ready" : "locked");
}

bool self_test() {
  // server/tests/test_identity_certs.py test_pinned_vector
  std::string seed;
  for (int k = 0; k < 32; k++) seed += static_cast<char>(k);
  RNS::Cryptography::Ed25519PrivateKey key(bytes(seed));
  Cert c;
  c.kind = "id";
  c.n = 7;
  for (int k = 0; k < 16; k++) c.i += static_cast<char>(k);
  c.u = "aj";
  c.dn = "AJ";
  for (int k = 32; k < 64; k++) c.p += static_cast<char>(k);
  c.t = 1790000000;
  c.x = 1792592000;
  c.s = unhex(
      "324aa31e6a2464e5564dbd9104bd140eaeb306dc52badaf0adfcd3152407f402"
      "b2546d77e98676476409d3d5d3c49511a744e8a65564b0978e14ab10885b1804");
  std::string pub = raw(key.public_key()->public_bytes());
  std::string msg;
  canonical(c, msg);
  bool ok = hex(pub) == "03a107bff3ce10be1d70dd18e74bc09967e4d6309ba50d5f1ddc8664125531b8" &&
            raw(key.sign(bytes(msg))) == c.s && ed25519_ok(pub, c.s, msg);
  Cert bad = c;
  bad.u = "bob";
  canonical(bad, msg);
  ok = ok && !ed25519_ok(pub, c.s, msg);
  // test_signed_messages.py test_pinned_object_vector
  std::string oid, author;
  for (int k = 0; k < 16; k++) oid += static_cast<char>(k);
  for (int k = 16; k < 32; k++) author += static_cast<char>(k);
  ok = ok && hex(raw(key.sign(bytes(dispatch_bytes(oid, "aj", author, "dm:aj:bob", "hello", 1790000000))))) ==
                 "05619c34b899c57d550f7faa3676f1b35bd12a2e9bb089d2c4e791624747f433"
                 "7b714cb9caf2e1ad73583e7ba1d33e70dc0d1831835e29a5118777965795c40f";
  Serial.printf("certs: self-test %s\n", ok ? "ok" : "FAILED");
  return ok;
}

void loop() {
  flush_files();
  if (!account::paired() || !station_link::station_known()) return;
  if (g_next_ms && static_cast<int32_t>(millis() - g_next_ms) < 0) return;
  Res r = Res::Ok;
  g_idle = false;
  if (!step(r)) {
    g_idle = true;
    g_next_ms = millis() + 60000;  // nothing to do; look again in a minute
  } else if (r == Res::Ok) {
    g_next_ms = millis() + 1500;  // keep going, without hogging the radio
  } else {
    Serial.printf("certs: Station request failed (%s), retry in 1 min\n", station_link::describe(r));
    g_next_ms = millis() + 60000;
  }
  if (!g_next_ms) g_next_ms = 1;
}

// Without Station there's nothing to wait for: work with what's cached.
bool idle() { return g_idle || !station_link::station_known(); }

void set_identity(const std::string& seed, const std::string& pin) {
  g_seed = seed;
  g_pub = public_of(seed);
  seal(pin);
  Serial.printf("certs: identity %s\n", hex(identity_id_of(g_pub)).c_str());
}

bool have_key() { return !g_pub.empty(); }
bool key_unlocked() { return !g_seed.empty(); }

void unlock(const std::string& pin) {
  if (!g_seed.empty()) return;
  if (g_key_file.size() < 1 + 16 + 4 + 32 || g_key_file[0] != 'W') return;
  std::string salt = g_key_file.substr(1, 16);
  uint32_t iters = 0;
  for (int k = 0; k < 4; k++) iters = (iters << 8) | static_cast<uint8_t>(g_key_file[17 + k]);
  std::string dk = pbkdf2(pin, salt, iters, 64);
  RNS::Cryptography::Token token(bytes(dk), RNS::Type::Cryptography::Token::MODE_AES_256_CBC);
  RNS::Bytes sealed = bytes(g_key_file.substr(21));
  if (!token.verify_hmac(sealed)) {
    Serial.println("certs: identity key didn't open with this PIN");
    return;
  }
  std::string seed = raw(token.decrypt(sealed));
  if (public_of(seed) != g_pub) {
    Serial.println("certs: identity key doesn't match its public half");
    return;
  }
  g_seed = seed;
}

void lock() {
  if (!account::has_pin()) return;  // nothing protects it anyway
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
  author_id = identity_id_of(g_pub);
  sig = sign(dispatch_bytes(oid, account::username(), author_id, conv, body, t));
  return sig.size() == 64;
}

const Cert* identity(const std::string& username) {
  for (const auto& c : g_certs)
    if (c.kind == "id" && lower(c.u) == lower(username) && current(c)) return &c;
  return nullptr;
}

const Cert* identity_by_id(const std::string& id) {
  for (const auto& c : g_certs)
    if (c.kind == "id" && c.i == id && current(c)) return &c;
  return nullptr;
}

bool revoked(uint64_t serial) {
  return std::any_of(g_certs.begin(), g_certs.end(),
                     [&](const Cert& c) { return c.kind == "rev" && c.r == serial; });
}

std::string owner_of(const std::string& id) {
  if (id.size() != 16) return "";
  if (!g_pub.empty() && identity_id_of(g_pub) == id) return account::username();
  if (const Cert* c = identity_by_id(id)) return c->u;
  if (std::find(g_unknown_ids.begin(), g_unknown_ids.end(), id) == g_unknown_ids.end() &&
      g_unknown_ids.size() < 16)
    g_unknown_ids.push_back(id);  // look it up next time Station is in reach
  return "";
}

std::string verify_dispatch(const std::string& oid, const std::string& author, const std::string& id,
                            const std::string& conv, const std::string& body, uint64_t t,
                            const std::string& sig) {
  std::string pub;
  if (!g_pub.empty() && identity_id_of(g_pub) == id) {
    pub = g_pub;  // our own messages coming back to us
  } else {
    const Cert* c = nullptr;
    for (const auto& x : g_certs)
      if (x.kind == "id" && x.i == id) c = &x;
    if (!c) return "unknown_identity";
    if (revoked(c->n)) return "identity_revoked";
    if (!current(*c)) return "certificate_expired";
    if (lower(c->u) != lower(author)) return "bad_signature";
    pub = c->p;
  }
  if (oid.size() != 16) return "bad_signature";
  return ed25519_ok(pub, sig, dispatch_bytes(oid, author, id, conv, body, t)) ? "" : "bad_signature";
}

Status status() {
  Status s;
  s.root = !g_root.empty();
  s.root_conflict = g_root_conflict;
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
  g_root.clear();
  g_root_conflict = false;
  g_certs.clear();
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
