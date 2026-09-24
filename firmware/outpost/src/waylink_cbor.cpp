#include "waylink_cbor.h"

#ifdef ARDUINO
#include <esp_system.h>
#else
#include <cstdlib>
#endif

#include <cstdio>
#include <cstring>

namespace waylink {

namespace {

// -- Writer --

class CborWriter {
 public:
  explicit CborWriter(RNS::Bytes& out) : _out(out) {}

  void write_map_header(size_t n) { write_head(0xA0, n); }
  void write_array_header(size_t n) { write_head(0x80, n); }

  void write_text(const char* s) {
    size_t n = s ? strlen(s) : 0;
    write_head(0x60, n);
    if (n) _out.append(reinterpret_cast<const uint8_t*>(s), n);
  }
  void write_text(const std::string& s) {
    write_head(0x60, s.size());
    if (!s.empty()) _out.append(reinterpret_cast<const uint8_t*>(s.data()), s.size());
  }
  void write_uint(uint64_t v) { write_head(0x00, v); }
  void write_null() { _out.append(static_cast<uint8_t>(0xF6)); }

  // Text field that may be absent — matches Python's Optional[str] -> None.
  void write_opt_text(bool present, const std::string& s) {
    if (present) write_text(s);
    else write_null();
  }
  void write_opt_text(const char* s) {
    if (s) write_text(s);
    else write_null();
  }

 private:
  void write_head(uint8_t major_base, uint64_t n) {
    if (n < 24) {
      _out.append(static_cast<uint8_t>(major_base | n));
    } else if (n <= 0xFF) {
      _out.append(static_cast<uint8_t>(major_base | 24));
      _out.append(static_cast<uint8_t>(n));
    } else if (n <= 0xFFFF) {
      _out.append(static_cast<uint8_t>(major_base | 25));
      _out.append(static_cast<uint8_t>(n >> 8));
      _out.append(static_cast<uint8_t>(n));
    } else if (n <= 0xFFFFFFFFULL) {
      _out.append(static_cast<uint8_t>(major_base | 26));
      for (int shift = 24; shift >= 0; shift -= 8) {
        _out.append(static_cast<uint8_t>(n >> shift));
      }
    } else {
      _out.append(static_cast<uint8_t>(major_base | 27));
      for (int shift = 56; shift >= 0; shift -= 8) {
        _out.append(static_cast<uint8_t>(n >> shift));
      }
    }
  }

  RNS::Bytes& _out;
};

// -- Reader --

class CborReader {
 public:
  CborReader(const uint8_t* buf, size_t len) : _buf(buf), _len(len) {}

  bool read_head(uint8_t& major, uint64_t& val) {
    if (_pos >= _len) return false;
    uint8_t ib = _buf[_pos++];
    major = ib >> 5;
    uint8_t ai = ib & 0x1F;
    if (ai < 24) {
      val = ai;
      return true;
    }
    if (ai == 24) {
      if (_pos + 1 > _len) return false;
      val = _buf[_pos];
      _pos += 1;
      return true;
    }
    if (ai == 25) {
      if (_pos + 2 > _len) return false;
      val = (uint64_t(_buf[_pos]) << 8) | _buf[_pos + 1];
      _pos += 2;
      return true;
    }
    if (ai == 26) {
      if (_pos + 4 > _len) return false;
      val = 0;
      for (int i = 0; i < 4; i++) val = (val << 8) | _buf[_pos + i];
      _pos += 4;
      return true;
    }
    if (ai == 27) {
      if (_pos + 8 > _len) return false;
      val = 0;
      for (int i = 0; i < 8; i++) val = (val << 8) | _buf[_pos + i];
      _pos += 8;
      return true;
    }
    return false;  // indefinite length (ai==31) — unsupported, see header comment
  }

  bool read_text(std::string& out) {
    size_t save = _pos;
    uint8_t major;
    uint64_t val;
    if (!read_head(major, val) || major != 3) {
      _pos = save;
      return false;
    }
    if (_pos + val > _len) return false;
    out.assign(reinterpret_cast<const char*>(_buf + _pos), static_cast<size_t>(val));
    _pos += val;
    return true;
  }

  bool read_map_header(uint64_t& n) {
    size_t save = _pos;
    uint8_t major;
    if (!read_head(major, n) || major != 5) {
      _pos = save;
      return false;
    }
    return true;
  }

  bool read_array_header(uint64_t& n) {
    size_t save = _pos;
    uint8_t major;
    if (!read_head(major, n) || major != 4) {
      _pos = save;
      return false;
    }
    return true;
  }

  bool read_bool(bool& out) {
    if (_pos >= _len) return false;
    if (_buf[_pos] == 0xF4) {
      out = false;
      _pos++;
      return true;
    }
    if (_buf[_pos] == 0xF5) {
      out = true;
      _pos++;
      return true;
    }
    return false;
  }

  bool is_null() {
    if (_pos < _len && _buf[_pos] == 0xF6) {
      _pos++;
      return true;
    }
    return false;
  }

  // Consumes exactly one CBOR value of any type, recursing into
  // arrays/maps/tags. Used for envelope/payload fields this firmware
  // doesn't need (v, mid, src, dst, svc, op, flags, ts, ingested, ...).
  bool skip_value() {
    uint8_t major;
    uint64_t val;
    if (!read_head(major, val)) return false;
    switch (major) {
      case 0:
      case 1:
      case 7:  // uint / negative-int / simple-or-float: read_head already consumed it
        return true;
      case 2:
      case 3:  // byte string / text string
        if (_pos + val > _len) return false;
        _pos += val;
        return true;
      case 4:  // array
        for (uint64_t i = 0; i < val; i++)
          if (!skip_value()) return false;
        return true;
      case 5:  // map
        for (uint64_t i = 0; i < val; i++) {
          if (!skip_value()) return false;  // key
          if (!skip_value()) return false;  // value
        }
        return true;
      case 6:  // tag: number already consumed by read_head, skip tagged value
        return skip_value();
      default:
        return false;
    }
  }

  size_t pos() const { return _pos; }

 private:
  const uint8_t* _buf;
  size_t _len;
  size_t _pos = 0;
};

}  // namespace

RNS::Bytes encode_board_sync_request(
    const char* src,
    const char* dst,
    const std::string& mid,
    const std::string& rid,
    uint32_t ttl,
    const char* display_name,
    const std::vector<OutgoingNote>& notes) {
  RNS::Bytes out;
  CborWriter w(out);

  // Envelope: v, mid, rid, src, dst, svc, op, flags, ts, ttl, payload
  w.write_map_header(11);
  w.write_text("v");
  w.write_uint(1);  // shared/protocol/envelope.py PROTOCOL_VERSION
  w.write_text("mid");
  w.write_text(mid);
  w.write_text("rid");
  w.write_text(rid);
  w.write_text("src");
  w.write_text(src);
  w.write_text("dst");
  w.write_text(dst);
  w.write_text("svc");
  w.write_text("CORKBOARD");
  w.write_text("op");
  w.write_text("BOARD_SYNC");
  w.write_text("flags");
  w.write_uint(1);  // Flags.REQUEST
  w.write_text("ts");
  w.write_uint(0);  // Outpost has no RTC in this slice; Station doesn't rely on it
  w.write_text("ttl");
  w.write_uint(ttl);
  w.write_text("payload");

  // payload: {display_name, notes}
  w.write_map_header(2);
  w.write_text("display_name");
  w.write_opt_text(display_name);
  w.write_text("notes");
  w.write_array_header(notes.size());
  for (const auto& n : notes) {
    w.write_map_header(4);
    w.write_text("id");
    w.write_text(n.id);
    w.write_text("body");
    w.write_text(n.body);
    w.write_text("signature");
    w.write_opt_text(n.has_signature, n.signature);
    w.write_text("created_at");
    w.write_null();  // no RTC on-device; Station defaults it server-side
  }

  return out;
}

RNS::Bytes encode_outpost_claim_request(
    const char* src,
    const char* dst,
    const std::string& mid,
    const std::string& rid,
    uint32_t ttl,
    const std::string& code,
    const std::string& own_transport_dest,
    const char* display_name) {
  RNS::Bytes out;
  CborWriter w(out);

  w.write_map_header(11);
  w.write_text("v");
  w.write_uint(1);
  w.write_text("mid");
  w.write_text(mid);
  w.write_text("rid");
  w.write_text(rid);
  w.write_text("src");
  w.write_text(src);
  w.write_text("dst");
  w.write_text(dst);
  w.write_text("svc");
  w.write_text("CORKBOARD");
  w.write_text("op");
  w.write_text("OUTPOST_CLAIM");
  w.write_text("flags");
  w.write_uint(1);  // Flags.REQUEST
  w.write_text("ts");
  w.write_uint(0);
  w.write_text("ttl");
  w.write_uint(ttl);
  w.write_text("payload");

  w.write_map_header(3);
  w.write_text("code");
  w.write_text(code);
  w.write_text("transport_dest");
  w.write_text(own_transport_dest);
  w.write_text("display_name");
  w.write_opt_text(display_name);

  return out;
}

std::string new_hex_id() {
  uint8_t raw[8];
#ifdef ARDUINO
  esp_fill_random(raw, sizeof(raw));
#else
  for (auto& b : raw) b = static_cast<uint8_t>(rand() & 0xFF);
#endif
  char hex[17];
  for (int i = 0; i < 8; i++) snprintf(hex + i * 2, 3, "%02x", raw[i]);
  return std::string(hex, 16);
}

bool decode_sync_reply(const uint8_t* data, size_t len, SyncReplyResult& result) {
  CborReader r(data, len);

  uint64_t n = 0;
  if (!r.read_map_header(n)) return false;

  for (uint64_t i = 0; i < n; i++) {
    std::string key;
    if (!r.read_text(key)) return false;

    if (key == "rid") {
      if (!r.read_text(result.rid)) return false;
      continue;
    }

    if (key == "payload") {
      if (r.is_null()) continue;
      uint64_t m = 0;
      if (!r.read_map_header(m)) return false;
      for (uint64_t j = 0; j < m; j++) {
        std::string pkey;
        if (!r.read_text(pkey)) return false;

        if (pkey == "ok") {
          if (!r.read_bool(result.ok)) return false;
        } else if (pkey == "error") {
          if (r.is_null()) continue;
          if (!r.read_text(result.error_msg)) return false;
          result.error = true;
        } else if (pkey == "pending") {
          uint64_t p = 0;
          if (!r.read_array_header(p)) return false;
          for (uint64_t k = 0; k < p; k++) {
            uint64_t q = 0;
            if (!r.read_map_header(q)) return false;
            PendingNote note;
            for (uint64_t l = 0; l < q; l++) {
              std::string nkey;
              if (!r.read_text(nkey)) return false;
              if (nkey == "id") {
                if (!r.read_text(note.id)) return false;
              } else if (nkey == "body") {
                if (!r.read_text(note.body)) return false;
              } else if (nkey == "signature") {
                if (r.is_null()) continue;
                if (!r.read_text(note.signature)) return false;
                note.has_signature = true;
              } else {
                if (!r.skip_value()) return false;
              }
            }
            if (!note.id.empty() && !note.body.empty()) {
              result.pending.push_back(std::move(note));
            }
          }
        } else {
          if (!r.skip_value()) return false;
        }
      }
      continue;
    }

    // Any other envelope field (v, mid, src, dst, svc, op, flags, ts, ttl, ...)
    if (!r.skip_value()) return false;
  }

  result.parsed = true;
  return true;
}

}  // namespace waylink
