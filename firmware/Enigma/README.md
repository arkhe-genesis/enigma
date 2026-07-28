# Enigma firmware library

The Arduino sketch and per-board firmware. Open [`Enigma.ino`](Enigma.ino) in the
Arduino IDE (or build with your own toolchain) and flash the target board.

- [`Enigma.ino`](Enigma.ino): main sketch / entry point
- Per-board logic: `BoardSW14`, `BoardQD04`, `BoardAN08` (each `.cpp` + `.h`)
- Shared core: `Board`, `EnigmaHID`, `Config`, `EnigmaLogger`
- LEDs: `LEDManager`, `LEDAnimator`, `DialAnimator`

See the [firmware overview](../README.md) for build notes, and the
[HID wire protocol](../../host/enigma/docs/HID_PROTOCOL.md) these boards implement.
