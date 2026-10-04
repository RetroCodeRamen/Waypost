#include "contacts.h"

#include <Arduino.h>
#include <microReticulum.h>

#include "account.h"

namespace contacts {
namespace {

const char* const kPath = "/waypost_contacts";  // "#owner\t<user>", then "user\tname\tdest" lines
std::vector<Contact> g_contacts;

void save() {
  std::string out = "#owner\t" + account::username() + "\n";
  for (const auto& c : g_contacts) out += c.username + "\t" + c.name + "\t" + c.scout_dest + "\n";
  RNS::Utilities::OS::write_file(kPath, RNS::Bytes(out));
}

}  // namespace

void load() {
  g_contacts.clear();
  RNS::Bytes raw;
  if (RNS::Utilities::OS::read_file(kPath, raw) == 0) return;
  std::string s(reinterpret_cast<const char*>(raw.data()), raw.size());
  // Another account's directory (or a file from before owners were
  // recorded) is stale: drop it and let the picker fetch afresh.
  std::string owner = "#owner\t" + account::username() + "\n";
  if (s.compare(0, owner.size(), owner) != 0) {
    Serial.println("contacts: cache belongs to another account, discarded");
    clear();
    return;
  }
  size_t pos = owner.size();
  while (pos < s.size()) {
    size_t nl = s.find('\n', pos);
    std::string line = s.substr(pos, nl == std::string::npos ? std::string::npos : nl - pos);
    pos = nl == std::string::npos ? s.size() : nl + 1;
    size_t t1 = line.find('\t');
    size_t t2 = t1 == std::string::npos ? t1 : line.find('\t', t1 + 1);
    if (t1 == std::string::npos || t2 == std::string::npos) continue;
    g_contacts.push_back({line.substr(0, t1), line.substr(t1 + 1, t2 - t1 - 1), line.substr(t2 + 1)});
  }
  Serial.printf("contacts: %u cached\n", static_cast<unsigned>(g_contacts.size()));
}

const std::vector<Contact>& all() { return g_contacts; }

void clear() {
  g_contacts.clear();
  RNS::Utilities::OS::remove_file(kPath);
}

const Contact* find(const std::string& username) {
  for (const auto& c : g_contacts)
    if (c.username == username) return &c;
  return nullptr;
}

station_link::Result refresh() {
  std::vector<Contact> fresh;
  uint64_t offset = 0;
  for (int page = 0; page < 20; page++) {
    waylink::Reply reply;
    auto r = station_link::request("PROFILE", "ROLL_LIST", {waylink::Field::num("offset", offset)}, reply);
    if (r != station_link::Result::Ok) return r;
    const waylink::Value* people = reply.payload().get("people");
    size_t n = 0;
    if (people && people->type == waylink::Value::Array) {
      for (const auto& p : people->items) {
        fresh.push_back({p.text("u"), p.text("n", p.text("u")), p.text("d")});
        n++;
      }
    }
    offset += n;
    if (!reply.payload().flag("more") || n == 0) break;
  }
  g_contacts = fresh;
  save();
  return station_link::Result::Ok;
}

}  // namespace contacts
