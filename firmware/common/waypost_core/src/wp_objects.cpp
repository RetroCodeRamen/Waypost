#include "wp_objects.h"

#include <algorithm>
#include <cctype>
#include <cstdlib>

#include <microReticulum.h>
#include <microReticulum/Cryptography/Ed25519.h>

namespace wp {

// -- bytes ----------------------------------------------------------------------

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

std::string lower(std::string s) {
  for (auto& ch : s) ch = static_cast<char>(tolower(static_cast<unsigned char>(ch)));
  return s;
}

std::string escape(const std::string& s) {
  std::string out;
  for (char c : s) {
    if (c == '\\') out += "\\\\";
    else if (c == '\t') out += "\\t";
    else if (c == '\n') out += "\\n";
    else out += c;
  }
  return out;
}

std::string unescape(const std::string& s) {
  std::string out;
  for (size_t i = 0; i < s.size(); i++) {
    if (s[i] == '\\' && i + 1 < s.size()) {
      char n = s[++i];
      out += n == 't' ? '\t' : n == 'n' ? '\n' : n;
    } else {
      out += s[i];
    }
  }
  return out;
}

std::vector<std::string> split_tabs(const std::string& line) {
  std::vector<std::string> f;
  size_t start = 0;
  while (true) {
    size_t t = line.find('\t', start);
    f.push_back(line.substr(start, t == std::string::npos ? std::string::npos : t - start));
    if (t == std::string::npos) break;
    start = t + 1;
  }
  return f;
}

std::string dm_id(const std::string& a, const std::string& b) {
  std::string x = lower(a), y = lower(b);
  return x < y ? "dm:" + x + ":" + y : "dm:" + y + ":" + x;
}

// -- crypto -------------------------------------------------------------------------

bool ed25519_ok(const std::string& pub, const std::string& sig, const std::string& msg) {
  if (pub.size() != 32 || sig.size() != 64) return false;
  return RNS::Cryptography::Ed25519PublicKey::from_public_bytes(bytes(pub))->verify(bytes(sig), bytes(msg));
}

std::string identity_id_of(const std::string& public_key) {
  return raw(RNS::Identity::full_hash(bytes(public_key))).substr(0, 16);
}

// -- canonical bytes ----------------------------------------------------------------

namespace {

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

}  // namespace

// server/services/identity/certs.py canonical_bytes()
bool canonical(const Cert& c, std::string& out) {
  out = "WAYPOST-CERT-1\n";
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

// server/services/identity/objects.py canonical_bytes(), kind dispatch.msg
std::string dispatch_bytes(const std::string& oid, const std::string& user, const std::string& author_id,
                           const std::string& conv, const std::string& body, uint64_t t) {
  std::string out = "WAYPOST-OBJ-1\n";
  put(out, "k", "dispatch.msg"), put(out, "o", oid), put(out, "u", user), put(out, "a", author_id);
  put(out, "v", conv), put(out, "b", body), put(out, "t", u64be(t));
  return out;
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

// -- the cache --------------------------------------------------------------------------

bool CertCache::offer_root(const std::string& pk) {
  if (pk.size() != 32) return false;
  if (root.empty()) {
    root = pk;
    return true;
  }
  if (pk != root) {
    // Never silently trust a new root: that would let any Station vouch
    // for anyone. Signing out (Scout) / reflashing (Outpost) starts fresh.
    root_conflict = true;
    return false;
  }
  return true;
}

bool CertCache::verify(const Cert& c) const {
  std::string msg;
  if (root.size() != 32 || !canonical(c, msg) || !ed25519_ok(root, c.s, msg)) return false;
  return c.kind != "id" || identity_id_of(c.p) == c.i;  // an id must be its key's
}

bool CertCache::add(const Cert& c) {
  if (!verify(c)) return false;
  if (c.kind == "rev") {
    if (std::any_of(certs.begin(), certs.end(), [&](const Cert& x) { return x.kind == "rev" && x.n == c.n; }))
      return true;
    certs.push_back(c);
    certs.erase(std::remove_if(certs.begin(), certs.end(),
                               [&](const Cert& x) { return x.kind != "rev" && x.n == c.r; }),
                certs.end());
  } else {
    certs.erase(std::remove_if(certs.begin(), certs.end(),
                               [&](const Cert& x) { return x.kind == "id" && lower(x.u) == lower(c.u); }),
                certs.end());
    certs.push_back(c);
  }
  return true;
}

bool CertCache::revoked(uint64_t serial) const {
  return std::any_of(certs.begin(), certs.end(), [&](const Cert& c) { return c.kind == "rev" && c.r == serial; });
}

bool CertCache::current(const Cert& c) const {
  if (revoked(c.n)) return false;
  uint64_t now = _now ? _now() : 0;
  return now == 0 || now < c.x;  // clock unknown: trust until we know better
}

bool CertCache::fresh(const Cert* c, uint64_t renew_before_s) const {
  if (!c) return false;
  uint64_t now = _now ? _now() : 0;
  return now == 0 || c->x > now + renew_before_s;
}

const Cert* CertCache::identity(const std::string& username) const {
  for (const auto& c : certs)
    if (c.kind == "id" && lower(c.u) == lower(username) && current(c)) return &c;
  return nullptr;
}

const Cert* CertCache::identity_by_id(const std::string& id) const {
  for (const auto& c : certs)
    if (c.kind == "id" && c.i == id && current(c)) return &c;
  return nullptr;
}

std::string CertCache::owner_of(const std::string& id) const {
  const Cert* c = identity_by_id(id);
  return c ? c->u : "";
}

std::string CertCache::verify_dispatch(const std::string& oid, const std::string& author, const std::string& id,
                                       const std::string& conv, const std::string& body, uint64_t t,
                                       const std::string& sig) const {
  const Cert* c = nullptr;
  for (const auto& x : certs)
    if (x.kind == "id" && x.i == id) c = &x;
  if (!c) return "unknown_identity";
  if (revoked(c->n)) return "identity_revoked";
  if (!current(*c)) return "certificate_expired";
  if (lower(c->u) != lower(author) || oid.size() != 16) return "bad_signature";
  return ed25519_ok(c->p, sig, dispatch_bytes(oid, author, id, conv, body, t)) ? "" : "bad_signature";
}

std::string CertCache::serialize(const std::string& owner) const {
  std::string out = "#owner\t" + owner + "\n";
  if (!root.empty()) out += "root\t" + hex(root) + "\n";
  for (const auto& c : certs) {
    out += "c\t" + c.kind + "\t" + std::to_string(c.n) + "\t" + hex(c.i) + "\t" + escape(c.u) + "\t" +
           escape(c.dn) + "\t" + hex(c.p) + "\t" + std::to_string(c.t) + "\t" + std::to_string(c.x) + "\t" +
           std::to_string(c.r) + "\t" + hex(c.s) + "\n";
  }
  return out;
}

void CertCache::load(const std::vector<std::string>& lines, const std::string& owner) {
  root.clear();
  certs.clear();
  if (lines.empty() || lines[0] != "#owner\t" + owner) return;
  for (size_t k = 1; k < lines.size(); k++) {
    auto f = split_tabs(lines[k]);
    if (f.size() == 2 && f[0] == "root") root = unhex(f[1]);
    if (f.size() < 11 || f[0] != "c") continue;
    Cert c;
    c.kind = f[1];
    c.n = strtoull(f[2].c_str(), nullptr, 10);
    c.i = unhex(f[3]);
    c.u = unescape(f[4]);
    c.dn = unescape(f[5]);
    c.p = unhex(f[6]);
    c.t = strtoull(f[7].c_str(), nullptr, 10);
    c.x = strtoull(f[8].c_str(), nullptr, 10);
    c.r = strtoull(f[9].c_str(), nullptr, 10);
    c.s = unhex(f[10]);
    if (verify(c)) certs.push_back(c);  // older formats simply don't verify
  }
}

// -- pinned vectors -----------------------------------------------------------------------

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
  return ok;
}

}  // namespace wp
