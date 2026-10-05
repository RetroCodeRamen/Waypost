#include "wp_caps.h"

#include "waylink_cbor.h"

namespace wp {

RNS::Bytes caps_app_data(const std::string& marker, const Caps& caps) {
  waylink::Value v = waylink::Value::make_map();
  v.set("r", waylink::Value::of_uint(caps.role));
  v.set("s", waylink::Value::of_uint(caps.services));
  v.set("st", waylink::Value::of_uint(caps.station));
  if (!caps.name.empty()) v.set("n", waylink::Value::of_text(caps.name.substr(0, 24)));
  RNS::Bytes out(reinterpret_cast<const uint8_t*>(marker.data()), marker.size());
  out.append(static_cast<uint8_t>(0));
  out.append(waylink::encode_value(v));
  return out;
}

bool split_caps(const RNS::Bytes& app_data, std::string& marker, Caps& caps) {
  const uint8_t* d = app_data.data();
  size_t n = app_data.size(), nul = 0;
  while (nul < n && d[nul] != 0) nul++;
  marker.assign(reinterpret_cast<const char*>(d), nul);
  caps = Caps();
  if (nul + 1 >= n) return false;
  waylink::Value v;
  if (!waylink::parse(d + nul + 1, n - nul - 1, v)) return false;
  caps.role = static_cast<uint32_t>(v.uint("r"));
  caps.services = static_cast<uint32_t>(v.uint("s"));
  caps.station = static_cast<uint32_t>(v.uint("st"));
  caps.name = v.text("n").substr(0, 24);
  return true;
}

}  // namespace wp
