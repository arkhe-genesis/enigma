# Enigma Documentation

Reference documentation for the Enigma host library. New here? Start with the
design guide, then the config format for whatever board you're wiring.

## Start here
- [Design guide](DESIGN_GUIDE.md): architecture and core concepts
- [Code generation](CODE_GENERATION.md): turning JSON configs into code + reference docs (and `mk.sh`)
- [Control mappings](CONTROL_MAPPINGS.md): how panel names map to physical boards

## Board configuration
Each board type is described by a JSON config:
- [SW14](SW14_CONFIG.md): switch / button panels
- [QD04](QD04_CONFIG.md): quadrature rotary encoders
- [AN08](AN08_CONFIG.md): analog inputs
- [GPRO](GPRO_CONFIG.md): keyboard (Logitech G Pro)
- [Thrustmaster](THRUSTMASTER_CONFIG.md): T16000M flight stick

## Wire protocols
- [HID protocol](HID_PROTOCOL.md): the board wire protocol (frame format, opcodes, per-variant payloads)

## Extending
- [Implementing a new board handler](NEW_BOARD_HANDLER.md): the host-side driver for a new board variant

## Devices, audio, displays
- [Device specs](DEVICE_SPECS.md): simulator device state (`Spec`) definitions
- [Audio system](AUDIO_CONFIG.md): audio library configuration
- [Audio usage](../audio/USAGE.md): playing sounds at runtime (the audio API in practice)
- [Display development](DISPLAY_CONFIG.md): companion WebSocket displays
- [Display WebSocket protocol](DISPLAY_WEBSOCKET_PROTOCOL.md): the wire protocol

## API reference
- [Manager class](api/MANAGER_CLASS.md): the console orchestrator: lifecycle plus console-wide operations the app calls via `get_manager()`
- [DisplayManager class](api/DISPLAY_MANAGER.md): publish spec values to displays and receive events back from them
- [Panel class](api/PANEL_CLASS.md): for code that maintains a panel's visible and interactivity state
- [Device class](api/DEVICE_CLASS.md): for 'business logic' pertaining to a discrete [sub]system in the game.
- [Control class](api/CONTROL_CLASS.md): generated control interface classes for devices and panels to consume.
- [Audio class](api/AUDIO_CLASS.md): generated audio calls for devices and panels to drive.

## Elsewhere in the repo
- [Repository overview](../../../README.md): what Enigma is, top-level map
- [Host library](../../README.md): the Python package these docs describe
- [Example](../../examples/engine-sw/): end-to-end panel: publisher + display + Unity receiver
- [Firmware](../../../firmware/): the C/C++ that runs on the boards
- [Hardware](../../../hardware/): the PCB designs
