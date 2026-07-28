# Enigma Firmware

Microcontroller firmware for the Enigma control boards (C/C++, Arduino). A board
enumerates as a USB-HID device, reads its JSON config from non-volatile storage,
drives its indicator LEDs, and reports control-state changes to the host. The
config lives on the board, so it boots and runs correctly before the host is up.

## In this directory
- [`Enigma/`](Enigma/): the firmware library and main sketch (below)
- [`HID.ino`](HID.ino): standalone SW14 bring-up / test sketch
- [`listen.py`](listen.py): small host-side serial listener for debugging

## Inside [`Enigma/`](Enigma/)
- [`Enigma.ino`](Enigma/Enigma.ino): main sketch / entry point
- Per-board logic: [`BoardSW14`](Enigma/BoardSW14.cpp), [`BoardQD04`](Enigma/BoardQD04.cpp), [`BoardAN08`](Enigma/BoardAN08.cpp) (+ their `.h`)
- Shared core: [`Board`](Enigma/Board.cpp), [`EnigmaHID`](Enigma/EnigmaHID.cpp), [`Config`](Enigma/Config.cpp), [`EnigmaLogger`](Enigma/EnigmaLogger.cpp)
- LEDs: [`LEDManager`](Enigma/LEDManager.cpp), [`LEDAnimator`](Enigma/LEDAnimator.cpp), [`DialAnimator`](Enigma/DialAnimator.cpp)

## Building
Open [`Enigma/Enigma.ino`](Enigma/Enigma.ino) in the Arduino IDE (or build with
your own toolchain) and flash the target microcontroller. The firmware is MIT
licensed; see the repository root [`LICENSE`](../LICENSE).

## Elsewhere in the repo
- [Repository overview](../README.md): what Enigma is, top-level map
- [Host library](../host/README.md): the Python software that drives these boards
- [Board config docs](../host/enigma/docs/): the JSON each board reads (SW14 / QD04 / AN08 / ...)
- [Hardware](../hardware/): the PCB designs these run on
