#include "board.h"

#include <Arduino.h>
#include <SPI.h>
#include <Wire.h>

namespace board {

void bring_up() {
  pinMode(kPowerOn, OUTPUT);
  digitalWrite(kPowerOn, HIGH);
  // Every device on the shared SPI bus deselected before anyone talks.
  for (int cs : {kTftCs, kSdCs, kRadioCs}) {
    pinMode(cs, OUTPUT);
    digitalWrite(cs, HIGH);
  }
  pinMode(kSpiMiso, INPUT_PULLUP);  // never floats while nothing drives it
  SPI.begin(kSpiSck, kSpiMiso, kSpiMosi);
  Wire.begin(kI2cSda, kI2cScl);
  delay(500);  // the keyboard's own controller starts (LilyGO's examples wait 500 ms)
}

}  // namespace board
