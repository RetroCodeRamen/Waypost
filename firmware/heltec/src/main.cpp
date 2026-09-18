/*
 * Waypost Heltec USB↔LoRa bridge
 *
 * Host framing (115200 8N1):
 *   'W' 'P' | uint32 BE length | payload bytes
 *
 * Special host payloads (ASCII):
 *   "ECHO"  — echo frame on USB
 *   "STAT"  — status text frame
 *
 * Otherwise payload is sent over LoRa; inbound LoRa is framed to USB.
 */

#include <Arduino.h>
#include <SPI.h>
#include <RadioLib.h>

#if defined(WAYPOST_HELTEC_V3)
  static const int PIN_LORA_NSS = 8;
  static const int PIN_LORA_SCK = 9;
  static const int PIN_LORA_MOSI = 10;
  static const int PIN_LORA_MISO = 11;
  static const int PIN_LORA_RST = 12;
  static const int PIN_LORA_BUSY = 13;
  static const int PIN_LORA_DIO1 = 14;
  static const int PIN_VEXT = 36;
  SX1262 radio = new Module(PIN_LORA_NSS, PIN_LORA_DIO1, PIN_LORA_RST, PIN_LORA_BUSY);
#elif defined(WAYPOST_HELTEC_V2)
  static const int PIN_LORA_NSS = 18;
  static const int PIN_LORA_RST = 14;
  static const int PIN_LORA_DIO0 = 26;
  SX1276 radio = new Module(PIN_LORA_NSS, PIN_LORA_DIO0, PIN_LORA_RST, RADIOLIB_NC);
#else
  #error "Select heltec_wifi_lora_32_V3 or V2 env in platformio.ini"
#endif

static const uint8_t MAGIC0 = 'W';
static const uint8_t MAGIC1 = 'P';
static const size_t MAX_FRAME = 250;  // SX1262 practical max; Dispatch MSG_* ~216B CBOR

static uint32_t rx_air = 0;
static uint32_t tx_air = 0;
static uint32_t rx_usb = 0;
static float last_rssi = 0;
static bool radio_ok = false;
volatile bool lora_flag = false;

static uint8_t ser_buf[MAX_FRAME + 8];
static size_t ser_len = 0;
static uint8_t lora_buf[MAX_FRAME];

#if defined(ESP8266) || defined(ESP32)
  IRAM_ATTR
#endif
void on_lora_irq() {
  lora_flag = true;
}

static void host_write_frame(const uint8_t *data, size_t len) {
  if (len > MAX_FRAME) return;
  Serial.write(MAGIC0);
  Serial.write(MAGIC1);
  uint32_t n = (uint32_t)len;
  Serial.write((n >> 24) & 0xff);
  Serial.write((n >> 16) & 0xff);
  Serial.write((n >> 8) & 0xff);
  Serial.write(n & 0xff);
  Serial.write(data, len);
}

static void host_write_text(const char *s) {
  host_write_frame(reinterpret_cast<const uint8_t *>(s), strlen(s));
}

static void arm_receive() {
  lora_flag = false;
  radio.startReceive();
}

static void handle_host_payload(const uint8_t *data, size_t len) {
  rx_usb++;

  if (len == 4 && memcmp(data, "ECHO", 4) == 0) {
    host_write_frame(data, len);
    return;
  }
  if (len == 4 && memcmp(data, "STAT", 4) == 0) {
    char msg[96];
    snprintf(msg, sizeof(msg),
             "WAYPOST radio=%s rx_air=%lu tx_air=%lu rx_usb=%lu rssi=%.1f",
             radio_ok ? "ok" : "fail",
             (unsigned long)rx_air,
             (unsigned long)tx_air,
             (unsigned long)rx_usb,
             (double)last_rssi);
    host_write_text(msg);
    return;
  }

  if (!radio_ok) {
    host_write_text("WAYPOST_RADIO_DOWN");
    return;
  }

  int16_t st = radio.transmit(const_cast<uint8_t *>(data), len);
  if (st == RADIOLIB_ERR_NONE) {
    tx_air++;
  } else {
    char msg[48];
    snprintf(msg, sizeof(msg), "WAYPOST_TX_ERR %d", (int)st);
    host_write_text(msg);
  }
  arm_receive();
}

static void try_parse_host() {
  while (ser_len >= 6) {
    if (ser_buf[0] != MAGIC0 || ser_buf[1] != MAGIC1) {
      memmove(ser_buf, ser_buf + 1, --ser_len);
      continue;
    }
    uint32_t n = ((uint32_t)ser_buf[2] << 24) | ((uint32_t)ser_buf[3] << 16) |
                 ((uint32_t)ser_buf[4] << 8) | (uint32_t)ser_buf[5];
    if (n == 0 || n > MAX_FRAME) {
      memmove(ser_buf, ser_buf + 1, --ser_len);
      continue;
    }
    if (ser_len < 6 + n) return;
    handle_host_payload(ser_buf + 6, n);
    size_t total = 6 + n;
    memmove(ser_buf, ser_buf + total, ser_len - total);
    ser_len -= total;
  }
}

void setup() {
  Serial.begin(115200);
  delay(400);

#if defined(WAYPOST_HELTEC_V3)
  pinMode(PIN_VEXT, OUTPUT);
  digitalWrite(PIN_VEXT, LOW);
  delay(80);
  SPI.begin(PIN_LORA_SCK, PIN_LORA_MISO, PIN_LORA_MOSI, PIN_LORA_NSS);
#endif

  int16_t st = radio.begin(915.0);
  if (st == RADIOLIB_ERR_NONE) {
    radio_ok = true;
    radio.setOutputPower(14);
    radio.setSpreadingFactor(7);
    radio.setBandwidth(125.0);
    radio.setCodingRate(5);
    radio.setPreambleLength(8);
    radio.setCRC(true);
    radio.setDio1Action(on_lora_irq);
    arm_receive();
    Serial.println("WAYPOST_BRIDGE_READY");
  } else {
    radio_ok = false;
    Serial.print("WAYPOST_RADIO_FAIL ");
    Serial.println(st);
  }
}

void loop() {
  while (Serial.available()) {
    if (ser_len >= sizeof(ser_buf)) ser_len = 0;
    ser_buf[ser_len++] = (uint8_t)Serial.read();
    try_parse_host();
  }

  if (radio_ok && lora_flag) {
    lora_flag = false;
    size_t len = radio.getPacketLength();
    if (len == 0 || len > MAX_FRAME) {
      arm_receive();
      return;
    }
    int16_t st = radio.readData(lora_buf, len);
    if (st == RADIOLIB_ERR_NONE) {
      rx_air++;
      last_rssi = radio.getRSSI();
      host_write_frame(lora_buf, len);
    }
    arm_receive();
  }
}
