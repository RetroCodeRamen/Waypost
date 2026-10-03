// Vendored unmodified from attermann/microReticulum
// examples/common/lora_interface (Apache-2.0). BOARD_HELTEC_V3 branch in
// the .cpp already matches this project's Heltec V3 pin mapping exactly —
// see firmware/heltec/src/main.cpp for the independently-verified reference.
#pragma once

#include <microReticulum/Interface.h>
#include <microReticulum/Bytes.h>
#include <microReticulum/Type.h>

#ifdef ARDUINO
#include <SPI.h>
#include <RadioLib.h>
#endif

#include <stdint.h>

class LoRaInterface : public RNS::InterfaceImpl {

public:
	//z def get_address_for_if(name):
	//z def get_broadcast_for_if(name):

public:
	//p def __init__(self, owner, name, device=None, bindip=None, bindport=None, forwardip=None, forwardport=None):
	LoRaInterface(const char* name = "LoRaInterface");
	virtual ~LoRaInterface();

	virtual bool start();
	virtual void stop();
	virtual void loop();

	//virtual inline std::string toString() const { return "LoRaInterface[" + name() + "]"; }

private:
	virtual bool send_outgoing(const RNS::Bytes& data);
	void on_incoming(const RNS::Bytes& data);

public:
	// Split-packet protocol constants — bit-for-bit matched against real
	// RNode firmware's own over-the-air format (firmware/RNode_Firmware/
	// RNode_Firmware.ino's transmit()/Utilities.h's isSplitPacket()/
	// packetSequence()), not invented. Station's physical radio runs that
	// real firmware; a mismatched header layout here means any packet
	// needing more than one physical LoRa frame (~254 bytes packed) gets
	// silently corrupted on receive — this was the actual root cause of
	// "it worked once, then never again" for anything beyond a tiny
	// payload, found 2026-10-03 debugging Scout chat.
	static constexpr uint8_t HEADER_SPLIT     = 0x01;  // bit 0 — matches RNode's FLAG_SPLIT
	static constexpr uint8_t SEQ_UNSET        = 0xFF;  // sentinel: no split in progress (never transmitted)
	static constexpr int     LORA_MAX_PAYLOAD = 254;   // 255 - 1 header byte

private:
	//uint8_t buffer[Type::Reticulum::MTU] = {0};
	const uint8_t message_count = 0;
	RNS::Bytes buffer;

	uint8_t _rx_seq     = SEQ_UNSET;  // sequence of split RX in progress

	// Radio parameters (RadioLib units: MHz, kHz)
	const float frequency = 915.0;   // MHz
	const float bandwidth = 125.0;   // kHz
	const int   spreading = 8;
	const int   coding    = 5;
	const int   power     = 17;      // dBm

#ifdef ARDUINO
	Module*        _module      = nullptr;
	PhysicalLayer* _radio       = nullptr;
	int            _pa_mode_pin = -1;    // V4 FEM PA mode pin; -1 = not present
#endif

};
