// The Outpost's Wi-Fi Dispatch page (/msg): people sign in with their
// Waypost username + password — the key is worked out in their browser
// (web/wpcrypto.js), so the password never reaches the Outpost — and
// exchange signed messages with anyone: Scouts nearby, Station, other
// Outposts. Each browser gets its own session, so several people can be
// signed in on one Outpost at once.
#pragma once

#include <string>

#include <WebServer.h>

namespace oweb {

// Register routes; call before server.begin(). `node` is this Outpost's id.
void setup(WebServer& server, const std::string* node);
size_t sessions();

}  // namespace oweb
