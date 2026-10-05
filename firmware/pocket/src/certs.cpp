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
const char* const kKeyPath = "/wp_sigkey";
const char* const kPubPath = "/wp_sigpub";

const char* const kMagic = "WAYPOST-CERT-1\n";
const char* const kIssueMagic = "WAYPOST-CERT-REQUEST-1\n";

const uint64_t kRenewBeforeS = 7ULL * 24 * 3600;  // matches Station's RENEW_BEFORE_SEC
const uint32_t kRefreshMs = 6UL * 3600UL * 1000UL;  // contacts' devices, revocations
const uint32_t kKdfIterations = 10000;

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
    if (c.i.size() != 16) return false;
    put(out, "k", c.kind), put(out, "n", u64be(c.n)), put(out, "i", c.i), put(out, "u", c.u);
    put(out, "dn", c.dn), put(out, "t", u64be(c.t)), put(out, "x", u64be(c.x));
  } else if (c.kind == "dev") {
    if (c.i.size() != 16 || c.p.size() != 32 || c.d.size() != 16) return false;
    put(out, "k", c.kind), put(out, "n", u64be(c.n)), put(out, "i", c.i), put(out, "u", c.u);
    put(out, "p", c.p), put(out, "d", c.d), put(out, "t", u64be(c.t)), put(out, "x", u64be(c.x));
  } else if (c.kind == "rev") {
    put(out, "k", c.kind), put(out, "n", u64be(c.n)), put(out, "r", u64be(c.r)), put(out, "t", u64be(c.t));
  } else {
    return false;
  }
  return true;
}

bool verify_with(const std::string& root, const Cert& c) {
  std::string msg;
  if (root.size() != 32 || c.s.size() != 64 || !canonical(c, msg)) return false;
  return RNS::Cryptography::Ed25519PublicKey::from_public_bytes(bytes(root))->verify(bytes(c.s), bytes(msg));
}

bool from_value(const waylink::Value& v, Cert& c) {
  if (v.type != waylink::Value::Map) return false;
  c.kind = v.text("k");
  c.n = v.uint("n");
  c.i = v.bytes("i");
  c.u = v.text("u");
  c.dn = v.text("dn");
  c.p = v.bytes("p");
  c.d = v.bytes("d");
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
std::vector<Cert> g_certs;   // verified id/dev/rev certificates
bool g_dirty = false;

std::string g_pub;           // signing public key
std::string g_priv;          // signing private key, only while unlocked
std::string g_key_file;      // /wp_sigkey as read (wrapped form)
bool g_key_dirty = false;
bool g_wipe = false;

std::map<std::string, uint32_t> g_devs_at;  // username -> millis of last CERT_DEV round
uint32_t g_revs_at = 0;
uint32_t g_next_ms = 0;

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
           store::escape(c.dn) + "\t" + hex(c.p) + "\t" + hex(c.d) + "\t" + std::to_string(c.t) + "\t" +
           std::to_string(c.x) + "\t" + std::to_string(c.r) + "\t" + hex(c.s) + "\n";
  }
  RNS::Utilities::OS::write_file(kCertsPath, RNS::Bytes(out));
}

// Keep one identity cert per person (newest), the given device set per
// person, and every revocation; drop what's been revoked.
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
    if (c.kind == "id") {
      g_certs.erase(std::remove_if(g_certs.begin(), g_certs.end(),
                                   [&](const Cert& x) { return x.kind == "id" && lower(x.u) == lower(c.u); }),
                    g_certs.end());
    } else {
      g_certs.erase(std::remove_if(g_certs.begin(), g_certs.end(),
                                   [&](const Cert& x) { return x.kind == "dev" && x.n == c.n; }),
                    g_certs.end());
    }
    g_certs.push_back(c);
  }
  Serial.printf("certs: verified %s %s #%llu\n", c.kind.c_str(), c.kind == "rev" ? "" : c.u.c_str(),
                static_cast<unsigned long long>(c.n));
  g_dirty = true;
}

void set_devices(const std::string& username, const std::vector<Cert>& devs) {
  g_certs.erase(std::remove_if(g_certs.begin(), g_certs.end(),
                               [&](const Cert& x) { return x.kind == "dev" && lower(x.u) == lower(username); }),
                g_certs.end());
  for (const auto& c : devs) add(c);
  g_dirty = true;
}

// -- the signing key ------------------------------------------------------------

// PBKDF2-HMAC-SHA256 (RFC 8018). A short PIN is guessable by anyone who reads
// the flash however slow this is; it stops casual reading, not a lab.
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

// /wp_sigkey: "P" + private key (no PIN), or
//             "W" + salt(16) + iterations(4, BE) + Token(AES-256-CBC + HMAC)
void wrap(const std::string& pin) {
  if (g_priv.empty()) return;
  if (pin.empty()) {
    g_key_file = "P" + g_priv;
  } else {
    uint32_t start = millis();
    std::string salt = raw(RNS::Cryptography::random(16));
    std::string dk = pbkdf2(pin, salt, kKdfIterations, 64);
    RNS::Cryptography::Token token(bytes(dk), RNS::Type::Cryptography::Token::MODE_AES_256_CBC);
    g_key_file = "W" + salt + u64be(kKdfIterations).substr(4) + raw(token.encrypt(bytes(g_priv)));
    Serial.printf("certs: signing key wrapped with the PIN (%lu ms)\n",
                  static_cast<unsigned long>(millis() - start));
  }
  g_key_dirty = true;
}

void generate(const std::string& pin) {
  auto key = RNS::Cryptography::Ed25519PrivateKey::generate();
  g_priv = raw(key->private_bytes());
  g_pub = raw(key->public_key()->public_bytes());
  wrap(pin);
  Serial.printf("certs: new signing key %s\n", hex(g_pub).substr(0, 16).c_str());
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
    // for anyone. Unpair + pair again to accept a new Station.
    g_root_conflict = true;
    Serial.println("certs: Station offered a DIFFERENT community key - kept the pinned one");
  }
  return Res::Ok;
}

Res fetch_cert(const char* op, const std::vector<Field>& f, Cert& out, bool* more = nullptr) {
  waylink::Reply reply;
  Res r = station_link::request("PROFILE", op, f, reply);
  if (r != Res::Ok) return r;
  if (more) *more = reply.payload().flag("more");
  const waylink::Value* v = reply.payload().get("cert");
  if (!v || !from_value(*v, out)) return Res::Error;
  return Res::Ok;
}

Res issue_mine() {
  RNS::Bytes pk = station_link::identity_public_key();
  if (pk.size() != 64) return Res::NotReady;
  std::string msg = std::string(kIssueMagic) + station_link::node_id() + "\n" + g_pub;
  std::string sig = raw(station_link::identity_sign(bytes(msg)));
  Cert c;
  Res r = fetch_cert("CERT_ISSUE", {Field::bytes("pk", raw(pk)), Field::bytes("spk", g_pub), Field::bytes("sig", sig)}, c);
  if (r == Res::Ok) add(c);
  return r;
}

Res fetch_identity(const std::string& username) {
  Cert c;
  std::vector<Field> f;
  if (!username.empty()) f.push_back(Field::text("u", username));
  Res r = fetch_cert("CERT_GET", f, c);
  if (r == Res::Ok) add(c);
  return r;
}

Res fetch_devices(const std::string& username) {
  std::vector<Cert> devs;
  for (uint64_t i = 0; i < 8; i++) {
    waylink::Reply reply;
    Res r = station_link::request("PROFILE", "CERT_DEV", {Field::text("u", username), Field::num("i", i)}, reply);
    if (r != Res::Ok) return r;
    Cert c;
    const waylink::Value* v = reply.payload().get("cert");
    if (v && from_value(*v, c)) devs.push_back(c);
    if (!reply.payload().flag("more")) break;
  }
  set_devices(username, devs);
  g_devs_at[lower(username)] = millis() | 1;
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

const Cert* my_device() {
  for (const Cert* c : devices(account::username()))
    if (c->p == g_pub) return c;
  return nullptr;
}

// One request's worth of work. Returns false when there was nothing to do.
bool step(Res& r) {
  if (g_root.empty()) return r = fetch_root(), true;
  if (!g_pub.empty() && !fresh(my_device())) return r = issue_mine(), true;
  const std::string& me = account::username();
  if (!fresh(identity(me))) return r = fetch_identity(""), true;
  for (const auto& c : contacts::all()) {
    if (!fresh(identity(c.username))) return r = fetch_identity(c.username), true;
    if (due(g_devs_at[lower(c.username)], kRefreshMs)) return r = fetch_devices(c.username), true;
  }
  if (due(g_revs_at, kRefreshMs)) return r = fetch_revocations(), true;
  return false;
}

}  // namespace

// -- public ---------------------------------------------------------------------

void load() {
  g_root.clear();
  g_certs.clear();
  auto lines = store::read_lines(kCertsPath);
  bool mine = account::paired() && !lines.empty() && lines[0] == "#owner\t" + account::username();
  if (mine) {
    for (size_t k = 1; k < lines.size(); k++) {
      auto f = store::split_tabs(lines[k]);
      if (f.size() == 2 && f[0] == "root") g_root = unhex(f[1]);
      if (f.size() < 12 || f[0] != "c") continue;
      Cert c;
      c.kind = f[1];
      c.n = strtoull(f[2].c_str(), nullptr, 10);
      c.i = unhex(f[3]);
      c.u = store::unescape(f[4]);
      c.dn = store::unescape(f[5]);
      c.p = unhex(f[6]);
      c.d = unhex(f[7]);
      c.t = strtoull(f[8].c_str(), nullptr, 10);
      c.x = strtoull(f[9].c_str(), nullptr, 10);
      c.r = strtoull(f[10].c_str(), nullptr, 10);
      c.s = unhex(f[11]);
      if (verify_with(g_root, c)) g_certs.push_back(c);
    }
  }
  RNS::Bytes pub, key;
  if (account::paired()) {
    RNS::Utilities::OS::read_file(kPubPath, pub);
    RNS::Utilities::OS::read_file(kKeyPath, key);
  }
  g_pub = pub.size() == 32 ? raw(pub) : "";
  g_key_file = raw(key);
  g_priv.clear();
  if (!g_pub.empty() && g_key_file.size() == 33 && g_key_file[0] == 'P') g_priv = g_key_file.substr(1);
  if (g_pub.empty()) g_key_file.clear();
  Serial.printf("certs: %u certificate(s), community key %s, signing key %s\n",
                static_cast<unsigned>(g_certs.size()), g_root.empty() ? "not yet" : "pinned",
                g_pub.empty() ? "none" : !g_priv.empty() ? "ready" : "locked");
}

bool self_test() {
  // server/tests/test_identity_certs.py test_pinned_vector
  std::string seed;
  for (int k = 0; k < 32; k++) seed += static_cast<char>(k);
  RNS::Cryptography::Ed25519PrivateKey key(bytes(seed));
  Cert c;
  c.kind = "dev";
  c.n = 7;
  for (int k = 0; k < 16; k++) c.i += static_cast<char>(k);
  c.u = "aj";
  for (int k = 32; k < 64; k++) c.p += static_cast<char>(k);
  for (int k = 64; k < 80; k++) c.d += static_cast<char>(k);
  c.t = 1790000000;
  c.x = 1792592000;
  c.s = unhex(
      "d28a4d7bccc832b97d1e63ec0082f293cdc75d2c6d0534ae8d0d525427e5f53c"
      "ecb30dd2c141c76893a0512195bd67d8b221cd8fda9234da007df8ac98abbd03");
  std::string pub = raw(key.public_key()->public_bytes());
  std::string msg;
  canonical(c, msg);
  bool ok = hex(pub) == "03a107bff3ce10be1d70dd18e74bc09967e4d6309ba50d5f1ddc8664125531b8" &&
            raw(key.sign(bytes(msg))) == c.s && verify_with(pub, c);
  Cert bad = c;
  bad.u = "bob";
  ok = ok && !verify_with(pub, bad);
  Serial.printf("certs: self-test %s\n", ok ? "ok" : "FAILED");
  return ok;
}

namespace {
void flush_files() {
  if (store::files_safe()) {
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
}
}  // namespace

void loop() {
  flush_files();
  if (!account::paired()) return;
  // Without a PIN the key can be made right away; with one it's made at the
  // next unlock (it has to be wrapped with the PIN).
  if (g_pub.empty() && !account::has_pin()) generate("");
  if (!station_link::station_known()) return;
  if (g_next_ms && static_cast<int32_t>(millis() - g_next_ms) < 0) return;
  Res r = Res::Ok;
  if (!step(r)) {
    g_next_ms = millis() + 60000;  // nothing to do; look again in a minute
  } else if (r == Res::Ok) {
    g_next_ms = millis() + 1500;  // keep going, without hogging the radio
  } else {
    Serial.printf("certs: Station request failed (%s), retry in 1 min\n", station_link::describe(r));
    g_next_ms = millis() + 60000;
  }
  if (!g_next_ms) g_next_ms = 1;
}

bool have_key() { return !g_pub.empty(); }
bool key_unlocked() { return !g_priv.empty(); }

void unlock(const std::string& pin) {
  if (!g_priv.empty()) return;
  if (g_pub.empty()) {
    if (account::paired()) generate(account::has_pin() ? pin : "");
    return;
  }
  if (g_key_file.size() < 1 + 16 + 4 + 32 || g_key_file[0] != 'W') return;
  std::string salt = g_key_file.substr(1, 16);
  uint32_t iters = 0;
  for (int k = 0; k < 4; k++) iters = (iters << 8) | static_cast<uint8_t>(g_key_file[17 + k]);
  std::string dk = pbkdf2(pin, salt, iters, 64);
  RNS::Cryptography::Token token(bytes(dk), RNS::Type::Cryptography::Token::MODE_AES_256_CBC);
  RNS::Bytes sealed = bytes(g_key_file.substr(21));
  if (!token.verify_hmac(sealed)) {
    Serial.println("certs: signing key didn't open with this PIN");
    return;
  }
  std::string priv = raw(token.decrypt(sealed));
  RNS::Cryptography::Ed25519PrivateKey key(bytes(priv));
  if (raw(key.public_key()->public_bytes()) != g_pub) {
    Serial.println("certs: signing key doesn't match its public half");
    return;
  }
  g_priv = priv;
}

void lock() {
  if (!account::has_pin()) return;  // nothing protects it anyway
  std::fill(g_priv.begin(), g_priv.end(), '\0');
  g_priv.clear();
}

void rewrap(const std::string& pin) {
  if (g_priv.empty()) {
    if (g_pub.empty() && account::paired()) generate(pin);
    return;
  }
  wrap(pin);
}

std::string sign(const std::string& message) {
  if (g_priv.empty()) return "";
  RNS::Cryptography::Ed25519PrivateKey key(bytes(g_priv));
  return raw(key.sign(bytes(message)));
}

const std::string& signing_public() { return g_pub; }

const Cert* identity(const std::string& username) {
  for (const auto& c : g_certs)
    if (c.kind == "id" && lower(c.u) == lower(username) && current(c)) return &c;
  return nullptr;
}

std::vector<const Cert*> devices(const std::string& username) {
  std::vector<const Cert*> out;
  for (const auto& c : g_certs)
    if (c.kind == "dev" && lower(c.u) == lower(username) && current(c)) out.push_back(&c);
  return out;
}

bool revoked(uint64_t serial) {
  return std::any_of(g_certs.begin(), g_certs.end(),
                     [&](const Cert& c) { return c.kind == "rev" && c.r == serial; });
}

Status status() {
  Status s;
  s.root = !g_root.empty();
  s.root_conflict = g_root_conflict;
  const Cert* id = identity(account::username());
  const Cert* dev = my_device();
  s.mine = id && dev;
  if (s.mine) s.mine_until = std::min(id->x, dev->x);
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
  std::fill(g_priv.begin(), g_priv.end(), '\0');
  g_priv.clear();
  g_pub.clear();
  g_key_file.clear();
  g_devs_at.clear();
  g_revs_at = 0;
  g_dirty = g_key_dirty = false;
  g_wipe = true;
  flush_files();  // files only: no Station requests from here
}

}  // namespace certs
