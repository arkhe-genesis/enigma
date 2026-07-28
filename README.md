# Enigma

A framework for building physical interactive consoles: installations where an
operator works a panel of real switches, knobs, indicators, and screens. It handles input, state, audio, and displays:

- **Control surfaces**: custom USB-HID boards for switches, rotary encoders,
  and analog inputs, each control paired with an addressable-LED indicator.
  The board automatically manages all indicator animation and state management
  without host interaction.
- **State**: one coherent application state kept in sync via "Spec Vars" across multiple
  independent HID devices and displays, so every panel, sound, and display reacts to the same
  source of truth.
- **Audio and haptics**: a layered, multi-channel sound engine: independently
  volume-controlled classes (music, voice, ambient, effects, alerts), a priority
  voice-callout queue, and event- or threshold-driven playback. The same engine
  optionally drives haptic transducers alongside the speakers.
- **Displays**: optional, and anything that can hold a socket open: a local
  game-engine screen (Unity, Unreal, Godot), a browser page, an LED matrix, or a
  small networked screen on a Raspberry Pi across the room. Application state is
  serialized and published over WebSocket to any number of them (or none), each
  subscribing to only the values it needs.

Enigma is the framework the [Halcyon Dawn](https://madgoatlabs.com) physical
starship-bridge simulator is built on. It is published here as a complete,
reusable reference: the host library, the board firmware, and the PCB designs.

While building it explicitly for use in my simulator frame, I also kept in mind
somewhat broader needs, such as designing electronic escape room puzzles, arcade
games, and so on. The expanded list of future boards includes functionality
useful for those ventures, even if the Halcyon Dawn project didn't use them.


> **Status: published as-is, for reference and reuse. Not actively maintained.**
> Issues and pull requests are unlikely to be reviewed, and Issues are disabled.
> New boards may be added occasionally, but there is no support commitment.
> Fork freely; that is what the license is for.

> **Platform: built and tested only on macOS Tahoe (Apple Silicon).** No testing
> has been done on other platforms, and none is planned. It may or may not work
> elsewhere; that is left to you.

## Layout

- **[`host/`](host/)**: Python library + tools, the software that drives the boards `[MIT]`
  - [`enigma/`](host/enigma/): the importable library, with [`docs/`](host/enigma/docs/), [`audio/`](host/enigma/audio/), and [`boards/`](host/enigma/boards/)
  - [`examples/`](host/examples/): runnable end-to-end examples, [`engine-sw/`](host/examples/engine-sw/) (no hardware) and [`engine-full/`](host/examples/engine-full/) (real boards)
- **[`firmware/`](firmware/)**: C/C++ microcontroller firmware for the boards (Arduino) `[MIT]`
- **[`hardware/`](hardware/)**: PCB designs (schematic + layout + fabrication outputs) `[CERN-OHL-S-2.0]`
  - one directory per board: [`sw14/`](hardware/sw14/), [`qd04/`](hardware/qd04/), [`an08/`](hardware/an08/), plus the support boards
- **[`LICENSES/`](LICENSES/)**: full license texts; source files carry SPDX identifiers

## The boards

Three boards are implemented today. The rest are planned: their variant IDs are
already reserved in the firmware's board-variant enum, and they share the same
wire protocol and framing (see the [HID protocol reference](host/enigma/docs/HID_PROTOCOL.md)).

| Board | Purpose                                           | Status      | Config | Hardware |
|-------|---------------------------------------------------|-------------|--------|----------|
| SW14  | 14-channel illuminated switch / button input      | Implemented | [SW14_CONFIG.md](host/enigma/docs/SW14_CONFIG.md) | [`hardware/sw14/`](hardware/sw14/) |
| QD04  | 4-channel quadrature rotary encoder input         | Implemented | [QD04_CONFIG.md](host/enigma/docs/QD04_CONFIG.md) | [`hardware/qd04/`](hardware/qd04/) |
| AN08  | 8-channel analog input                            | Implemented | [AN08_CONFIG.md](host/enigma/docs/AN08_CONFIG.md) | [`hardware/an08/`](hardware/an08/) |
| BM16  | 16 illuminated pushbuttons                        | Deprecated  |        |          |
| UD08  | 8 incremental up/down counters with OLED displays | Planned     |        |          |
| SC16  | 16-channel servo output controller                | Planned     |        |          |
| DC04  | 4 animated LCD displays                           | Planned     |        |          |
| RL16  | 16-channel relay output                           | Planned     |        |          |
| LC04  | 4 WS2812 LED strings, up to 256 elements each     | Planned     |        |          |
| AU04  | 4 dual-channel audio soundclip players            | Planned     |        |          |
| AC08  | 8-channel buffered analog output                  | Planned     |        |          |
| MO04  | 4 bidirectional PWM motor-bridge controllers      | Planned     |        |          |

Each implemented board is a USB-HID device; the host library enumerates them,
applies a JSON config (control names, LED schemes, thresholds), reads state
changes, and drives per-control indicator LEDs.

> [!NOTE]
> **On "HID."** These are *technically* not HID devices, in the sense that they
> communicate exclusively through vendor reports in both directions. That is
> obviously necessary for the outbound host->board case, but the original
> protocol also included serial report IDs and reliable ACK behavior that did not
> wind up being very important in the final implementation. As such, the protocol
> could be brought in line with standard HID behavior if one were interested. See the
> [HID protocol reference](host/enigma/docs/HID_PROTOCOL.md) for the wire format.

## Install (host library)

```
cd host
pip install .
```

Then see the [examples](#examples) below for a runnable end-to-end walkthrough.

## Examples

Both examples drive the same `PortEngineSpec` onto the same web display; they
differ only in where the values come from.

- [`host/examples/engine-sw/`](host/examples/engine-sw/): the **output** side, no
  hardware. A Python app that defines a spec and publishes values, its JSON board
  and display config, a Flask display that renders them in a browser, and a Unity
  receiver. A synthetic device animates the values, and an interactive controls page
  lets you drive them by hand. The smallest full "state to screen" slice of Enigma.
- [`host/examples/engine-full/`](host/examples/engine-full/): the **input+output**
  side. The same spec and display, now driven by real Enigma boards (an AN08 pot,
  an SW14 switch panel, a QD04 encoder) read through a generated panel. Shows
  control-to-spec reading, LED schemes, and runtime enable/disable off the spec state.

## Documentation

Full documentation lives in [`host/enigma/docs/`](host/enigma/docs/):

- **[Design guide](host/enigma/docs/DESIGN_GUIDE.md)**: architecture and core concepts
- **[Code generation](host/enigma/docs/CODE_GENERATION.md)**: the config-to-code/docs generators and `mk.sh`
- **Board configuration**: [SW14](host/enigma/docs/SW14_CONFIG.md) (switches), [QD04](host/enigma/docs/QD04_CONFIG.md) (encoders), [AN08](host/enigma/docs/AN08_CONFIG.md) (analog); plus [GPRO keyboard](host/enigma/docs/GPRO_CONFIG.md) and [Thrustmaster stick](host/enigma/docs/THRUSTMASTER_CONFIG.md)
- **Controls and specs**: [control mappings](host/enigma/docs/CONTROL_MAPPINGS.md), [device specs](host/enigma/docs/DEVICE_SPECS.md)
- **Audio**: [audio system configuration](host/enigma/docs/AUDIO_CONFIG.md)
- **Displays**: [display development](host/enigma/docs/DISPLAY_CONFIG.md), [WebSocket protocol](host/enigma/docs/DISPLAY_WEBSOCKET_PROTOCOL.md)
- **Wire protocol**: [HID protocol](host/enigma/docs/HID_PROTOCOL.md): board frame format, opcodes, per-variant payloads
- **API reference**: [Manager](host/enigma/docs/api/MANAGER_CLASS.md), [DisplayManager](host/enigma/docs/api/DISPLAY_MANAGER.md), [Panel](host/enigma/docs/api/PANEL_CLASS.md), [Device](host/enigma/docs/api/DEVICE_CLASS.md), [Control](host/enigma/docs/api/CONTROL_CLASS.md), [Audio](host/enigma/docs/api/AUDIO_CLASS.md)

## Firmware

[`firmware/`](firmware/) is Arduino/C++ for the board microcontrollers. Open the relevant
sketch (e.g. [`firmware/Enigma/Enigma.ino`](firmware/Enigma/Enigma.ino)) in the Arduino IDE or build with
your toolchain of choice.

## Hardware

`hardware/<board>/` holds each board's design. See [`hardware/README.md`](hardware/README.md).

## License

This repository is multi-licensed:

- **Software** ([`host/`](host/), [`firmware/`](firmware/)) is licensed under the **MIT License** (see
  [`LICENSE`](LICENSE)).
- **Hardware** ([`hardware/`](hardware/)) is licensed under the **CERN Open Hardware Licence
  Version 2 - Strongly Reciprocal (CERN-OHL-S-2.0)** (see [`hardware/LICENSE`](hardware/LICENSE)).

Full license texts are in [`LICENSES/`](LICENSES/). Source files carry SPDX identifiers.

Copyright (c) 2026 Kevin Kelm (https://madgoatlabs.com)
