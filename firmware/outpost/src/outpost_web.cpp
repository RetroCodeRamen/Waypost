#include "outpost_web.h"

#include <algorithm>
#include <vector>

#include <Arduino.h>
#include <ArduinoJson.h>
#include <microReticulum.h>

#include "outpost_objects.h"
#include "web_assets.h"
#include "wp_objects.h"
#include "wp_sync.h"

namespace oweb {
namespace {

const size_t kMaxSessions = 12;
const uint32_t kSessionIdleMs = 12UL * 3600UL * 1000UL;
const uint32_t kNonceMs = 120000;

struct Session {
  std::string token;  // hex, the cookie
  std::string u;      // canonical username (Station's spelling when vouched)
  std::string pub;    // identity public key, 32 bytes
  std::string id;     // identity id, 16 bytes
  bool vouched;
  uint32_t last;
};

WebServer* g_srv = nullptr;
const std::string* g_node = nullptr;
std::vector<Session> g_sessions;
std::vector<std::pair<std::string, uint32_t>> g_nonces;  // hex -> expires (millis)

std::string random_hex(size_t n) { return wp::hex(wp::raw(RNS::Cryptography::random(n))); }

void send_json(int code, JsonDocument& doc, const String& extra_header = "") {
  String out;
  serializeJson(doc, out);
  if (extra_header.length()) g_srv->sendHeader("Set-Cookie", extra_header);
  g_srv->sendHeader("Cache-Control", "no-store");
  g_srv->send(code, "application/json", out);
}

void send_error(int code, const char* error) {
  JsonDocument doc;
  doc["error"] = error;
  send_json(code, doc);
}

Session* session() {
  if (!g_srv->hasHeader("Cookie")) return nullptr;
  String cookie = g_srv->header("Cookie");
  int at = cookie.indexOf("wps=");
  if (at < 0) return nullptr;
  std::string token(cookie.substring(at + 4, at + 4 + 32).c_str());
  for (auto& s : g_sessions) {
    if (s.token != token) continue;
    if (millis() - s.last > kSessionIdleMs) return nullptr;
    s.last = millis();
    return &s;
  }
  return nullptr;
}

bool parse_body(JsonDocument& doc) {
  return deserializeJson(doc, g_srv->arg("plain")) == DeserializationError::Ok;
}

void handle_asset() {
  String path = g_srv->uri();
  for (size_t i = 0; i < WEB_ASSET_COUNT; i++) {
    if (path != WEB_ASSETS[i].path) continue;
    g_srv->sendHeader("Content-Encoding", "gzip");
    g_srv->sendHeader("Cache-Control", "max-age=300");
    g_srv->send_P(200, WEB_ASSETS[i].type, reinterpret_cast<const char*>(WEB_ASSETS[i].data), WEB_ASSETS[i].len);
    return;
  }
  g_srv->send(404, "text/plain", "not found");
}

void handle_hello() {
  uint32_t now = millis();
  g_nonces.erase(std::remove_if(g_nonces.begin(), g_nonces.end(),
                                [&](const std::pair<std::string, uint32_t>& n) {
                                  return static_cast<int32_t>(now - n.second) > 0;
                                }),
                 g_nonces.end());
  if (g_nonces.size() >= 16) g_nonces.erase(g_nonces.begin());
  std::string nonce = random_hex(16);
  g_nonces.push_back({nonce, now + kNonceMs});
  JsonDocument doc;
  doc["node"] = g_node->c_str();
  doc["nonce"] = nonce.c_str();
  send_json(200, doc);
}

// The browser proves it holds the key worked out from username + password
// by signing a one-time challenge. A key Station vouches for under another
// name, or a different key for a name Station knows, is refused.
void handle_login() {
  JsonDocument in;
  if (!parse_body(in)) return send_error(400, "invalid_payload");
  std::string user = wp::lower(std::string(in["u"] | ""));
  std::string pub = wp::unhex(std::string(in["p"] | ""));
  std::string nonce = std::string(in["n"] | "");
  std::string sig = wp::unhex(std::string(in["s"] | ""));
  user.erase(0, user.find_first_not_of(' '));
  user.erase(user.find_last_not_of(' ') + 1);
  if (user.empty() || pub.size() != 32 || sig.size() != 64 || nonce.size() != 32)
    return send_error(400, "invalid_payload");
  auto it = std::find_if(g_nonces.begin(), g_nonces.end(),
                         [&](const std::pair<std::string, uint32_t>& n) { return n.first == nonce; });
  if (it == g_nonces.end() || static_cast<int32_t>(millis() - it->second) > 0) return send_error(400, "expired");
  g_nonces.erase(it);
  std::string msg = "WAYPOST-WEB-LOGIN-1\n" + *g_node + "\n" + wp::unhex(nonce);
  if (!wp::ed25519_ok(pub, sig, msg)) return send_error(400, "bad_signature");
  const wp::Cert* known = oobj::certs().identity(user);
  if (known && known->p != pub) return send_error(400, "wrong_password");

  Session s{random_hex(16), known ? known->u : user, pub, wp::identity_id_of(pub), known != nullptr, millis()};
  // One session per browser; the oldest idle one goes when full.
  if (g_sessions.size() >= kMaxSessions) {
    auto oldest = std::min_element(g_sessions.begin(), g_sessions.end(),
                                   [](const Session& a, const Session& b) { return a.last < b.last; });
    if (millis() - oldest->last < 10UL * 60UL * 1000UL) return send_error(503, "full");
    g_sessions.erase(oldest);
  }
  g_sessions.push_back(s);
  Serial.printf("web: %s signed in (%s), %u session(s)\n", s.u.c_str(), s.vouched ? "vouched" : "not vouched yet",
                static_cast<unsigned>(g_sessions.size()));
  JsonDocument out;
  out["ok"] = true;
  out["u"] = s.u.c_str();
  out["id"] = wp::hex(s.id).c_str();
  out["vouched"] = s.vouched;
  send_json(200, out, String("wps=") + s.token.c_str() + "; Path=/; HttpOnly; SameSite=Strict");
}

void handle_logout() {
  Session* s = session();
  if (s) {
    std::string token = s->token;
    g_sessions.erase(std::remove_if(g_sessions.begin(), g_sessions.end(),
                                    [&](const Session& x) { return x.token == token; }),
                     g_sessions.end());
  }
  JsonDocument out;
  out["ok"] = true;
  send_json(200, out, "wps=; Path=/; Max-Age=0");
}

void handle_me() {
  Session* s = session();
  if (!s) return send_error(401, "not_signed_in");
  JsonDocument out;
  out["u"] = s->u.c_str();
  out["id"] = wp::hex(s->id).c_str();
  out["vouched"] = s->vouched;
  send_json(200, out);
}

void handle_convs() {
  Session* s = session();
  if (!s) return send_error(401, "not_signed_in");
  JsonDocument out;
  JsonArray list = out["convs"].to<JsonArray>();
  for (const auto& c : oobj::conversations_for(s->u)) {
    JsonObject o = list.add<JsonObject>();
    o["id"] = c.id.c_str();
    o["with"] = c.with.c_str();
    o["t"] = c.last_t;
    o["n"] = c.count;
  }
  send_json(200, out);
}

bool party_to(const Session& s, const std::string& conv) {
  if (conv.compare(0, 3, "dm:") != 0) return false;  // direct messages (rooms later)
  auto p = wp::parties(s.u, conv);
  return p.size() == 3 && (p[1] == wp::lower(s.u) || p[2] == wp::lower(s.u));
}

void handle_msgs() {
  Session* s = session();
  if (!s) return send_error(401, "not_signed_in");
  std::string conv(g_srv->arg("c").c_str());
  if (!party_to(*s, conv)) return send_error(403, "not_a_member");
  JsonDocument out;
  JsonArray list = out["msgs"].to<JsonArray>();
  std::vector<std::string> delivered;
  for (const auto& m : oobj::messages(conv, 50, &delivered)) {
    JsonObject o = list.add<JsonObject>();
    o["o"] = wp::hex(m.o).c_str();
    o["u"] = m.u.c_str();
    o["b"] = m.b.c_str();
    o["t"] = m.t;
    if (std::find(delivered.begin(), delivered.end(), m.o) != delivered.end()) o["d"] = true;
  }
  out["max"] = wp::max_signed_body(s->u, conv);
  send_json(200, out);
}

// A message signed in the browser: checked against the session's key,
// then kept and delivered like anything else that arrives.
void handle_send() {
  Session* s = session();
  if (!s) return send_error(401, "not_signed_in");
  JsonDocument in;
  if (!parse_body(in)) return send_error(400, "invalid_payload");
  wp::Obj obj{wp::unhex(std::string(in["o"] | "")), s->u, s->id, std::string(in["v"] | ""),
              std::string(in["b"] | ""), wp::unhex(std::string(in["s"] | "")), in["t"] | 0ULL};
  if (obj.o.size() != 16 || obj.s.size() != 64 || obj.b.empty()) return send_error(400, "invalid_payload");
  if (!party_to(*s, obj.v)) return send_error(403, "not_a_member");
  if (obj.b.size() > wp::max_signed_body(s->u, obj.v)) return send_error(400, "too_long");
  if (obj.t < 1) obj.t = 1;
  if (!wp::ed25519_ok(s->pub, obj.s, wp::dispatch_bytes(obj.o, obj.u, obj.a, obj.v, obj.b, obj.t)))
    return send_error(400, "bad_signature");
  std::string err = oobj::add_local(obj);
  if (!err.empty()) return send_error(400, err.c_str());
  Serial.printf("web: %s wrote to %s (%u bytes)\n", s->u.c_str(), obj.v.c_str(), static_cast<unsigned>(obj.b.size()));
  JsonDocument out;
  out["ok"] = true;
  send_json(200, out);
}

}  // namespace

void setup(WebServer& server, const std::string* node) {
  g_srv = &server;
  g_node = node;
  const char* headers[] = {"Cookie"};
  server.collectHeaders(headers, 1);
  for (size_t i = 0; i < WEB_ASSET_COUNT; i++) server.on(WEB_ASSETS[i].path, HTTP_GET, handle_asset);
  server.on("/api/hello", HTTP_GET, handle_hello);
  server.on("/api/login", HTTP_POST, handle_login);
  server.on("/api/logout", HTTP_POST, handle_logout);
  server.on("/api/me", HTTP_GET, handle_me);
  server.on("/api/convs", HTTP_GET, handle_convs);
  server.on("/api/msgs", HTTP_GET, handle_msgs);
  server.on("/api/send", HTTP_POST, handle_send);
}

size_t sessions() { return g_sessions.size(); }

}  // namespace oweb
