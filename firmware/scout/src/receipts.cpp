#include "receipts.h"

#include <algorithm>

#include <Arduino.h>
#include <microReticulum.h>

#include "account.h"
#include "certs.h"
#include "net.h"
#include "store.h"
#include "sync.h"
#include "wp_objects.h"

namespace receipts {
namespace {

const char* const kPath = "/wp_rcpts";
const size_t kMax = 300;  // newest kept

std::vector<Receipt> g_all;
bool g_dirty = false;

std::string owner_line() { return "#owner\t" + account::username(); }

void save() {
  std::string out = owner_line() + "\n";
  for (const auto& r : g_all)
    out += wp::hex(r.oid) + "\t" + wp::hex(r.m) + "\t" + store::escape(r.conv) + "\t" + store::escape(r.user) +
           "\t" + wp::hex(r.author_id) + "\t" + std::to_string(r.t) + "\t" + wp::hex(r.sig) + "\n";
  RNS::Utilities::OS::write_file(kPath, RNS::Bytes(out));
}

void keep(const Receipt& r) {
  g_all.push_back(r);
  if (g_all.size() > kMax) g_all.erase(g_all.begin(), g_all.end() - kMax);
  g_dirty = true;
}

}  // namespace

void load() {
  g_all.clear();
  auto lines = store::read_lines(kPath);
  if (lines.empty() || lines[0] != owner_line()) return;  // another person's, or none
  for (size_t i = 1; i < lines.size(); i++) {
    auto f = store::split_tabs(lines[i]);
    if (f.size() < 7) continue;
    Receipt r{wp::unhex(f[0]), wp::unhex(f[1]), store::unescape(f[2]), store::unescape(f[3]),
              wp::unhex(f[4]), wp::unhex(f[6]), strtoull(f[5].c_str(), nullptr, 10)};
    if (r.oid.size() == 16 && r.m.size() == 16) g_all.push_back(r);
  }
  Serial.printf("receipts: %u\n", static_cast<unsigned>(g_all.size()));
}

void loop() {
  // Sign what waited for the key (a few per frame: Ed25519 takes a moment).
  if (certs::can_sign()) {
    int signed_now = 0;
    for (auto& r : g_all) {
      if (!r.sig.empty() || wp::lower(r.user) != wp::lower(account::username())) continue;
      if (!certs::sign_receipt(r.oid, r.conv, r.m, r.t, r.sig, r.author_id)) break;
      g_dirty = true;
      if (++signed_now >= 2) break;
    }
    if (signed_now) peersync::hurry();  // the sender's Scout may be in range
  }
  if (g_dirty) {
    g_dirty = false;
    save();
  }
}

void clear() {
  g_all.clear();
  g_dirty = false;
  RNS::Utilities::OS::remove_file(kPath);
}

void message_arrived(const std::string& conv, const std::string& message_id_hex) {
  if (message_id_hex.size() != 32 || !account::paired()) return;
  std::string m = wp::unhex(message_id_hex);
  std::string oid = wp::receipt_oid(m, account::username());
  if (find(oid)) return;
  uint64_t now = net::now_ms() / 1000;
  Receipt r{oid, m, conv, account::username(), "", "", now ? now : 1};
  keep(r);  // signed in loop(), now if the key is open, else at unlock
}

bool add(const Receipt& r) {
  if (find(r.oid)) return false;
  keep(r);
  return true;
}

const std::vector<Receipt>& all() { return g_all; }

const Receipt* find(const std::string& oid) {
  for (const auto& r : g_all)
    if (r.oid == oid) return &r;
  return nullptr;
}

bool delivered(const std::string& message_id_hex) {
  if (message_id_hex.size() != 32) return false;
  std::string m = wp::unhex(message_id_hex), me = wp::lower(account::username());
  return std::any_of(g_all.begin(), g_all.end(), [&](const Receipt& r) {
    return r.m == m && !r.sig.empty() && wp::lower(r.user) != me;
  });
}

}  // namespace receipts
