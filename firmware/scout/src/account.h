// Who this Scout belongs to, and its optional PIN — persisted in flash.
//
// The username comes from Station (PAIR_REDEEM / WHOAMI), never typed in:
// Station decides which account a device is bound to. The PIN only guards
// the UI on this device; flash isn't encrypted (docs/security.md).
#pragma once

#include <string>

namespace account {

void load();  // call once after the filesystem is up (station_link::setup)

bool paired();
const std::string& username();
const std::string& display_name();
void set_user(const std::string& username, const std::string& display_name);
// Forget the account and the PIN (the radio identity is kept, so the same
// Scout can simply be paired again), and remember that Station still has to
// be told (PROFILE/UNPAIR) — until it is, the Scout must not re-adopt the
// account from WHOAMI.
void unpair();
bool unpair_pending();
void clear_unpair_pending();

bool has_pin();
void set_pin(const std::string& pin);
bool check_pin(const std::string& pin);
void clear_pin();
bool valid_pin_format(const std::string& pin);  // 4-8 digits

}  // namespace account
