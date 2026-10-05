// People this Scout can message — Station's directory (PROFILE/ROLL_LIST),
// cached in flash so the picker (and later direct Scout-to-Scout delivery)
// works with Station out of range.
#pragma once

#include <string>
#include <vector>

#include <functional>

#include "net.h"

namespace contacts {

struct Contact {
  std::string username;
  std::string name;
  std::string scout_dest;  // their Scout's destination hash, "" if none
};

void load();
// Forget cached contacts (the Scout was unpaired or changed account).
void clear();
const std::vector<Contact>& all();
const Contact* find(const std::string& username);
// Fetches the whole directory from Station (paged) and saves it; `done`
// runs on the UI task when it's finished (or failed).
void refresh(std::function<void(net::Result)> done);

}  // namespace contacts
