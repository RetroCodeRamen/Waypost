// Identity key from username + password (server/services/identity/keys.py):
//   seed = scrypt(password, "waypost-identity-v1\n" + lower(username),
//                 N=4096, r=8, p=4, 32 bytes)  — ~4.4 s on a Scout
// scrypt needs N*r*128 bytes = 4 MiB of scratch, taken from PSRAM.
#pragma once

#include <cstddef>
#include <cstdint>
#include <string>

namespace kdf {

constexpr uint32_t kN = 4096;
constexpr uint32_t kR = 8;
constexpr uint32_t kP = 4;

// RFC 7914 scrypt. False if the scratch memory couldn't be allocated.
bool scrypt(const std::string& password, const std::string& salt, uint32_t N, uint32_t r,
            uint32_t p, uint8_t* out, size_t out_len);

// The 32-byte Ed25519 seed for this username + password ("" on failure).
std::string identity_seed(const std::string& username, const std::string& password);

}  // namespace kdf
