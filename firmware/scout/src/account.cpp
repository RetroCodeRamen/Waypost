#include "account.h"

#include <cctype>

#include <Arduino.h>
#include <microReticulum.h>

#include "certs.h"
#include "contacts.h"
#include "receipts.h"
#include "store.h"

namespace account {
namespace {

const char* const kUserPath = "/waypost_user";  // "username\ndisplay name"
const char* const kPinPath = "/waypost_pin";    // 16-byte salt + SHA-256(salt + pin)
const char* const kUnpairPath = "/waypost_unpair";  // exists = tell Station
constexpr size_t kSaltLen = 16;

std::string g_username;
std::string g_display_name;
RNS::Bytes g_pin_record;

RNS::Bytes pin_hash(const RNS::Bytes& salt, const std::string& pin) {
  RNS::Bytes data = salt;
  data.append(reinterpret_cast<const uint8_t*>(pin.data()), pin.size());
  return RNS::Identity::full_hash(data);  // SHA-256
}

void remove_file(const char* path) {
  RNS::Utilities::OS::remove_file(path);
}

}  // namespace

void load() {
  RNS::Bytes raw;
  if (RNS::Utilities::OS::read_file(kUserPath, raw) > 0) {
    std::string s(reinterpret_cast<const char*>(raw.data()), raw.size());
    size_t nl = s.find('\n');
    g_username = s.substr(0, nl);
    g_display_name = nl == std::string::npos ? g_username : s.substr(nl + 1);
  }
  RNS::Bytes pin;
  if (RNS::Utilities::OS::read_file(kPinPath, pin) == kSaltLen + 32) g_pin_record = pin;
  Serial.printf("account: %s, pin %s\n", g_username.empty() ? "(not paired)" : g_username.c_str(),
                has_pin() ? "set" : "not set");
}

bool paired() { return !g_username.empty(); }
const std::string& username() { return g_username; }
const std::string& display_name() { return g_display_name; }

void set_user(const std::string& username, const std::string& display_name) {
  // Contacts are the old account's directory (maybe from another Station).
  bool changed = username != g_username;
  if (changed) {
    contacts::clear();
    store::clear();  // its messages too
    receipts::clear();
  }
  g_username = username;
  // A different person on this Scout: new signing key, certificates fetched
  // afresh (after the username is set, so they're filed under it).
  if (changed) certs::clear();
  g_display_name = display_name.empty() ? username : display_name;
  std::string s = g_username + "\n" + g_display_name;
  RNS::Utilities::OS::write_file(kUserPath, RNS::Bytes(s));
}

void unpair() {
  contacts::clear();
  store::clear();
  receipts::clear();
  g_username.clear();
  g_display_name.clear();
  remove_file(kUserPath);
  clear_pin();
  certs::clear();  // signing key and certificates: re-pairing starts fresh
  RNS::Utilities::OS::write_file(kUnpairPath, RNS::Bytes("1"));
}

bool unpair_pending() { return RNS::Utilities::OS::file_exists(kUnpairPath); }

void clear_unpair_pending() { remove_file(kUnpairPath); }

bool has_pin() { return g_pin_record.size() == kSaltLen + 32; }

bool valid_pin_format(const std::string& pin) {
  if (pin.size() < 4 || pin.size() > 8) return false;
  for (char c : pin)
    if (!isdigit(static_cast<unsigned char>(c))) return false;
  return true;
}

void set_pin(const std::string& pin) {
  RNS::Bytes salt = RNS::Cryptography::random(kSaltLen);
  RNS::Bytes record = salt;
  record.append(pin_hash(salt, pin));
  g_pin_record = record;
  RNS::Utilities::OS::write_file(kPinPath, record);
  certs::rewrap(pin);  // the signing key is now sealed with this PIN
}

bool check_pin(const std::string& pin) {
  if (!has_pin()) return true;
  RNS::Bytes salt = g_pin_record.left(kSaltLen);
  bool ok = pin_hash(salt, pin) == g_pin_record.mid(kSaltLen);
  if (ok) certs::unlock(pin);  // the right PIN also opens the signing key
  return ok;
}

void clear_pin() {
  g_pin_record = RNS::Bytes();
  remove_file(kPinPath);
  certs::rewrap("");  // stored unsealed: nothing protects it without a PIN
}

}  // namespace account
