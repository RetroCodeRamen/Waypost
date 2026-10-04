// People this Scout can message — Station's directory (PROFILE/ROLL_LIST),
// cached in flash so the picker (and later direct Scout-to-Scout delivery)
// works with Station out of range.
#pragma once

#include <string>
#include <vector>

#include "station_link.h"

namespace contacts {

struct Contact {
  std::string username;
  std::string name;
  std::string scout_dest;  // their Scout's destination hash, "" if none
};

void load();
const std::vector<Contact>& all();
const Contact* find(const std::string& username);
// Fetches the whole directory from Station (paged) and saves it.
station_link::Result refresh();

}  // namespace contacts
