// LilyGO T-Deck board pins — from Xinyuan-LilyGO/T-Deck examples/UnitTest/utilities.h (MIT).
#pragma once

#define BOARD_POWERON 10

#define BOARD_I2C_SDA 18
#define BOARD_I2C_SCL 8

#define BOARD_TFT_CS 12
#define BOARD_TFT_DC 11
#define BOARD_TFT_BACKLIGHT 42

#define BOARD_SPI_MOSI 41
#define BOARD_SPI_MISO 38
#define BOARD_SPI_SCK 40

#define RADIO_CS_PIN 9
#define RADIO_BUSY_PIN 13
#define RADIO_RST_PIN 17
#define RADIO_DIO1_PIN 45

#define BOARD_BOOT_PIN 0

#ifndef RADIO_FREQ
#define RADIO_FREQ 915.0
#endif

#ifndef RADIO_BANDWIDTH
#define RADIO_BANDWIDTH 125.0
#endif

#ifndef RADIO_SF
#define RADIO_SF 8
#endif

#ifndef RADIO_CR
#define RADIO_CR 5
#endif

#ifndef RADIO_TX_POWER
#define RADIO_TX_POWER 14
#endif
