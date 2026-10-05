#include "kdf.h"

#include <cctype>
#include <cstring>
#include <vector>

#include <Arduino.h>
#include <SHA256.h>
#include <esp_heap_caps.h>

namespace kdf {
namespace {

void pbkdf2_sha256(const uint8_t* pass, size_t pass_len, const uint8_t* salt, size_t salt_len,
                   uint32_t iterations, uint8_t* out, size_t out_len) {
  SHA256 sha;
  uint8_t u[32], t[32];
  for (uint32_t block = 1; out_len > 0; block++) {
    uint8_t be[4] = {static_cast<uint8_t>(block >> 24), static_cast<uint8_t>(block >> 16),
                     static_cast<uint8_t>(block >> 8), static_cast<uint8_t>(block)};
    sha.resetHMAC(pass, pass_len);
    sha.update(salt, salt_len);
    sha.update(be, 4);
    sha.finalizeHMAC(pass, pass_len, u, sizeof(u));
    memcpy(t, u, sizeof(t));
    for (uint32_t i = 1; i < iterations; i++) {
      sha.resetHMAC(pass, pass_len);
      sha.update(u, sizeof(u));
      sha.finalizeHMAC(pass, pass_len, u, sizeof(u));
      for (int j = 0; j < 32; j++) t[j] ^= u[j];
    }
    size_t n = out_len < 32 ? out_len : 32;
    memcpy(out, t, n);
    out += n;
    out_len -= n;
  }
}

inline uint32_t rotl(uint32_t a, int b) { return (a << b) | (a >> (32 - b)); }

void salsa20_8(uint32_t B[16]) {
  uint32_t x[16];
  memcpy(x, B, sizeof(x));
  for (int i = 0; i < 8; i += 2) {
    x[4] ^= rotl(x[0] + x[12], 7);   x[8] ^= rotl(x[4] + x[0], 9);
    x[12] ^= rotl(x[8] + x[4], 13);  x[0] ^= rotl(x[12] + x[8], 18);
    x[9] ^= rotl(x[5] + x[1], 7);    x[13] ^= rotl(x[9] + x[5], 9);
    x[1] ^= rotl(x[13] + x[9], 13);  x[5] ^= rotl(x[1] + x[13], 18);
    x[14] ^= rotl(x[10] + x[6], 7);  x[2] ^= rotl(x[14] + x[10], 9);
    x[6] ^= rotl(x[2] + x[14], 13);  x[10] ^= rotl(x[6] + x[2], 18);
    x[3] ^= rotl(x[15] + x[11], 7);  x[7] ^= rotl(x[3] + x[15], 9);
    x[11] ^= rotl(x[7] + x[3], 13);  x[15] ^= rotl(x[11] + x[7], 18);
    x[1] ^= rotl(x[0] + x[3], 7);    x[2] ^= rotl(x[1] + x[0], 9);
    x[3] ^= rotl(x[2] + x[1], 13);   x[0] ^= rotl(x[3] + x[2], 18);
    x[6] ^= rotl(x[5] + x[4], 7);    x[7] ^= rotl(x[6] + x[5], 9);
    x[4] ^= rotl(x[7] + x[6], 13);   x[5] ^= rotl(x[4] + x[7], 18);
    x[11] ^= rotl(x[10] + x[9], 7);  x[8] ^= rotl(x[11] + x[10], 9);
    x[9] ^= rotl(x[8] + x[11], 13);  x[10] ^= rotl(x[9] + x[8], 18);
    x[12] ^= rotl(x[15] + x[14], 7); x[13] ^= rotl(x[12] + x[15], 9);
    x[14] ^= rotl(x[13] + x[12], 13); x[15] ^= rotl(x[14] + x[13], 18);
  }
  for (int i = 0; i < 16; i++) B[i] += x[i];
}

// BlockMix with Salsa20/8: B (2r blocks of 16 words) -> Y, result in B.
void blockmix(uint32_t* B, uint32_t* Y, uint32_t r) {
  uint32_t X[16];
  memcpy(X, &B[(2 * r - 1) * 16], 64);
  for (uint32_t i = 0; i < 2 * r; i++) {
    for (int k = 0; k < 16; k++) X[k] ^= B[i * 16 + k];
    salsa20_8(X);
    // even blocks first, then odd
    uint32_t dst = (i & 1) ? (r + i / 2) : (i / 2);
    memcpy(&Y[dst * 16], X, 64);
  }
  memcpy(B, Y, 128 * r);
}

void romix(uint8_t* block, uint32_t N, uint32_t r, uint32_t* V, uint32_t* X, uint32_t* Y) {
  const uint32_t words = 32 * r;  // 128*r bytes
  for (uint32_t k = 0; k < words; k++) {
    const uint8_t* b = block + 4 * k;
    X[k] = b[0] | (b[1] << 8) | (b[2] << 16) | (static_cast<uint32_t>(b[3]) << 24);
  }
  for (uint32_t i = 0; i < N; i++) {
    memcpy(&V[i * words], X, words * 4);
    blockmix(X, Y, r);
    if ((i & 255) == 0) yield();
  }
  for (uint32_t i = 0; i < N; i++) {
    uint32_t j = X[(2 * r - 1) * 16] & (N - 1);
    for (uint32_t k = 0; k < words; k++) X[k] ^= V[j * words + k];
    blockmix(X, Y, r);
    if ((i & 255) == 0) yield();
  }
  for (uint32_t k = 0; k < words; k++) {
    uint8_t* b = block + 4 * k;
    b[0] = X[k];
    b[1] = X[k] >> 8;
    b[2] = X[k] >> 16;
    b[3] = X[k] >> 24;
  }
}

}  // namespace

bool scrypt(const std::string& password, const std::string& salt, uint32_t N, uint32_t r,
            uint32_t p, uint8_t* out, size_t out_len) {
  const size_t block_len = 128 * r;
  std::vector<uint8_t> B(block_len * p);
  pbkdf2_sha256(reinterpret_cast<const uint8_t*>(password.data()), password.size(),
                reinterpret_cast<const uint8_t*>(salt.data()), salt.size(), 1, B.data(), B.size());
  auto* V = static_cast<uint32_t*>(heap_caps_malloc(block_len * N, MALLOC_CAP_SPIRAM));
  if (!V) return false;
  std::vector<uint32_t> X(32 * r), Y(32 * r);
  for (uint32_t i = 0; i < p; i++) romix(&B[i * block_len], N, r, V, X.data(), Y.data());
  heap_caps_free(V);
  pbkdf2_sha256(reinterpret_cast<const uint8_t*>(password.data()), password.size(), B.data(), B.size(), 1,
                out, out_len);
  return true;
}

std::string identity_seed(const std::string& username, const std::string& password) {
  std::string user;
  size_t a = username.find_first_not_of(' '), b = username.find_last_not_of(' ');
  if (a != std::string::npos) user = username.substr(a, b - a + 1);
  for (auto& c : user) c = static_cast<char>(tolower(static_cast<unsigned char>(c)));
  std::string salt = "waypost-identity-v1\n" + user;
  uint8_t seed[32];
  if (!scrypt(password, salt, kN, kR, kP, seed, sizeof(seed))) return "";
  return std::string(reinterpret_cast<const char*>(seed), sizeof(seed));
}

}  // namespace kdf
