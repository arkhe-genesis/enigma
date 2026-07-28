<!-- SPDX-License-Identifier: MIT -->
# enigma (host library)

The Python side of Enigma: it enumerates the USB-HID boards, applies JSON configs
(control names, LED schemes, thresholds), reads control-state changes, drives
indicator LEDs, and publishes state to companion displays over WebSocket.

## Install

```
pip install .
```

That pulls the core runtime dependencies: `hid` and `pyusb` (USB-HID access) and
`python-socketio[asyncio_client]` (which brings in `aiohttp`) for the WebSocket
client that publishes spec values to displays.

Two optional extras add subsystem-specific dependencies, installed only if you
ask for them:

| Command | Adds | For |
|---------|------|-----|
| `pip install .[audio]` | `pyaudio`, `soundfile`, `pydub` | audio playback (music, voice, ambient, alerts) |
| `pip install .[display]` | `flask`, `flask-socketio` | the Flask companion-display server |
| `pip install .[audio,display]` | both of the above | audio + displays |

The audio packages have native prerequisites (PyAudio needs PortAudio), so they
are kept out of the base install for anyone who only wants control-surface and
display functionality.

## How it works

`EnigmaManager` owns the boards and the displays. You hand it a `ConfigManager`
pointed at your JSON config directory; it reads the configs, brings up every
connected board, and from then on each `update()` tick polls hardware, runs your
device logic, drives the indicator LEDs, and pushes changed spec values to any
connected displays.

For a runnable end-to-end version, see [`examples/engine-sw/`](examples/engine-sw/).

## Package layout

| Module | What it is | Interface reference |
|--------|-----------|---------------------|
| `enigma/manager.py` | `EnigmaManager`: top-level orchestrator for boards + displays | [Manager](enigma/docs/api/MANAGER_CLASS.md) |
| `enigma/config.py` | `ConfigManager`: loads and validates the JSON configs | [ConfigManager](enigma/docs/api/MANAGER_CLASS.md#configmanager) |
| `enigma/device.py` | spec / published-value base classes (the shared state model) | [Device](enigma/docs/api/DEVICE_CLASS.md), [specs](enigma/docs/DEVICE_SPECS.md) |
| `enigma/panelmanager.py` | panel/control lifecycle across boards | [Panel](enigma/docs/api/PANEL_CLASS.md) |
| `enigma/displaymanager.py` | WebSocket display publishing + inbound events | [DisplayManager](enigma/docs/api/DISPLAY_MANAGER.md) |
| `enigma/hid_protocol.py` | the board wire protocol | [HID protocol](enigma/docs/HID_PROTOCOL.md) |
| `enigma/colors.py` | `print_error` / `print_warning` / brightness helpers | - |
| `enigma/boards/` | per-board drivers: SW14, QD04, AN08, plus Thrustmaster and G Pro | [New board handler](enigma/docs/NEW_BOARD_HANDLER.md) |
| `enigma/audio/` | the layered audio engine (optional `[audio]` extra) | [Audio](enigma/docs/api/AUDIO_CLASS.md), [usage](enigma/audio/USAGE.md) |
| `enigma/tools/` | code generators and command-line utilities (below) | [Code generation](enigma/docs/CODE_GENERATION.md) |
| `enigma/docs/` | full documentation | [docs index](enigma/docs/) |

The generated control classes (`EngineControl` etc.) aren't a module here: they
are produced from the configs; their interface is the [Control](enigma/docs/api/CONTROL_CLASS.md)
reference.

## Code generation

The Spec, control, and audio classes your code imports are generated from the
JSON configs. Regenerate after editing any config:

```
./mk.sh
```

[`mk.sh`](mk.sh) is a convenience wrapper over the three generators in
[`enigma/tools/`](enigma/tools/); see [CODE_GENERATION.md](enigma/docs/CODE_GENERATION.md)
for what each one does and the switches they take. The generators emit both
Python code and reference docs.

## Command-line tools

In [`enigma/tools/`](enigma/tools/):

- `enigma_cli.py`: inspect and exercise connected boards from a shell
- `hid_monitor.py`: watch raw HID traffic to and from a board
- `generate_controls.py` / `generate_devices.py` / `generate_audio.py`: the code generators (`mk.sh` runs all three)
- `gpro-daemon-*.sh`: build, install, and manage the G Pro keyboard daemon

## Documentation

Full reference documentation lives in [`enigma/docs/`](enigma/docs/). Start with
the [design guide](enigma/docs/DESIGN_GUIDE.md), then:

- Board configuration: [SW14](enigma/docs/SW14_CONFIG.md), [QD04](enigma/docs/QD04_CONFIG.md), [AN08](enigma/docs/AN08_CONFIG.md)
- [Device specs](enigma/docs/DEVICE_SPECS.md) and [control mappings](enigma/docs/CONTROL_MAPPINGS.md)
- [Audio configuration](enigma/docs/AUDIO_CONFIG.md) and [audio usage](enigma/audio/USAGE.md)
- Displays: [development](enigma/docs/DISPLAY_CONFIG.md), [WebSocket protocol](enigma/docs/DISPLAY_WEBSOCKET_PROTOCOL.md)
- [HID wire protocol](enigma/docs/HID_PROTOCOL.md)
- API reference: [Manager](enigma/docs/api/MANAGER_CLASS.md), [Panel](enigma/docs/api/PANEL_CLASS.md), [Device](enigma/docs/api/DEVICE_CLASS.md), [Control](enigma/docs/api/CONTROL_CLASS.md), [Audio](enigma/docs/api/AUDIO_CLASS.md)

## Example

[`examples/engine-sw/`](examples/engine-sw/) is a complete end-to-end slice: a Python
app that defines a spec and publishes values, its JSON board and display config,
a Flask browser display, and a Unity receiver. See [examples/](examples/).

## Elsewhere in the repo

- [Repository overview](../README.md): what Enigma is, top-level map
- [Firmware](../firmware/): the C/C++ that runs on the boards
- [Hardware](../hardware/): the PCB designs

## License

MIT; see the repository root [`LICENSE`](../LICENSE). Source files carry SPDX
identifiers.
