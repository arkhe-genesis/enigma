<!-- SPDX-License-Identifier: MIT -->
# Implementing a New Board Handler

A *board handler* is the host-side driver for one board variant. It parses that
board's JSON config, serializes config and state to the firmware's wire format,
and turns incoming reports back into control values. The library ships handlers
for SW14, QD04, AN08, and the two third-party inputs; adding support for a new
board type means writing one more handler and registering it.

The library picks the handler automatically: a board self-reports its variant
(the `CFG` resistor it reads on an ADC pin, surfaced in the `CONFIGREPORT`
message; see [HID_PROTOCOL.md](HID_PROTOCOL.md)), and the manager looks up the
handler registered for that variant id. You never wire a board to a handler by
hand.

This covers the **host** side only. A brand-new board also needs firmware that
speaks the protocol and a PCB; see [HID_PROTOCOL.md](HID_PROTOCOL.md) for the
wire format and the [hardware board family](../../../hardware/README.md) for the
variant ids and `CFG` values.

## The pieces

A handler module defines four classes and a registration call. `AN08` is the
smallest working example ([`enigma/boards/an08.py`](../boards/an08.py)); `SW14`
and `QD04` show the same shape with indicators and richer state.

```python
import struct
from .base import BoardVariantHandler, BoardConfig, ControlConfig, ControlState
from . import register_board_variant
from enigma.colors import print_error, print_warning   # sanctioned logging helpers


class MYBDControlState(ControlState):
    """One control's live value (what a report decodes to / a set encodes from)."""

class MYBDControlConfig(ControlConfig):
    """One control's configuration; to_setconfig_payload() serializes it."""
    def to_setconfig_payload(self):
        ...

class MYBDBoardConfig(BoardConfig):
    """The whole board's config; format_state_change() formats a change for logs."""

class MYBDHandler(BoardVariantHandler):
    VARIANT_ID = 5            # must match the board's CFG resistor / CONFIGREPORT
    TYPE_STR   = "MYBD"       # 4-char board type string

    def parse_config(self, config_data): ...
    def create_blank_config(self, control_num): ...
    def _pack_state(self, control_state): ...
    def _parse_state(self, state_data, control_num=None): ...
    # override set_indicator_scheme() only if the board has LEDs


register_board_variant(MYBDHandler.VARIANT_ID, MYBDHandler.TYPE_STR, MYBDHandler)
```

## Methods to implement

`BoardVariantHandler` provides the generic machinery (enable masks, scheme
push/pop, CRC, config send). A subclass overrides the variant-specific parts:

| Method | Responsibility | Needed |
|--------|----------------|--------|
| `parse_config(config_data)` | Turn the board's JSON into `ControlConfig` objects on a `BoardConfig`. | Always |
| `create_blank_config(control_num)` | Return a default config for one control (used when sending blanks). | Always |
| `_pack_state(control_state)` | Serialize a control value to the `SETSTATE` payload bytes. | If host sets state |
| `_parse_state(state_data, control_num=None)` | Decode a `REPORTSTATE` payload into a control value. | If board reports |
| `<ControlConfig>.to_setconfig_payload()` | Serialize a control's config to the `SETCONFIG` payload. | Always |
| `<BoardConfig>.format_state_change(...)` | Human-readable form of a change (logging / state stream). | Recommended |
| `set_indicator_scheme(scheme_name, control_name="")` | Apply an indicator scheme (`control_name=""` = all). | Only if the board has LEDs |

The base class's defaults handle the rest (`enable_all`/`disable_all`,
`send_enable_mask`, `push_scheme`/`pop_scheme`, `calculate_config_crc`,
`send_all_configs`, hardware-change tracking). A read-only board (like AN08) can
skip `_pack_state` and `set_indicator_scheme` entirely: the base no-ops them.

Your `_pack_state` / `_parse_state` / `to_setconfig_payload` byte layouts must
match the firmware's per-variant payloads exactly; those are specified in
[HID_PROTOCOL.md](HID_PROTOCOL.md#per-variant-payloads).

## Registration

The module-level `register_board_variant(variant_id, type_str, handler_class)`
call wires the handler into the lookup table. `variant_id` must match what the
board reports in `CONFIGREPORT` (which the firmware derives from the `CFG`
resistor), and `type_str` its 4-character type string.

For the call to run, the module must be imported. The built-in handlers are
imported by [`enigma/boards/__init__.py`](../boards/__init__.py); add your module
there (or import it from your application before `EnigmaManager.start()`).

## Third-party (commercial) HID devices

The same handler mechanism wraps off-the-shelf USB HID devices (joysticks,
keyboards, gamepads), which is how the Thrustmaster stick and G Pro keyboard are
supported. The difference is that a commercial device speaks its own HID report
format, not the Enigma protocol, so the handler:

- opens the device by USB `VID`/`PID` and reads its native reports (there is no
  `CONFIGREPORT` and no config resistor, so set `VARIANT_ID` to a sentinel such
  as `255`).
- parses the vendor's report bytes into control values (see the T.16000M report
  layout in [HID_PROTOCOL.md](HID_PROTOCOL.md#appendix-third-party-device-protocols)).
- treats the Enigma-only commands as no-ops where they don't apply (a stick has
  no indicators); an output-capable device sends the vendor's own commands
  instead (the G Pro's per-key RGB goes out through its `gpro_daemon`).

Reference: [`thrustmaster.py`](../boards/thrustmaster.py) (read-only joystick,
raw reports) and [`gpro.py`](../boards/gpro.py) (keyboard with RGB via a daemon).
Their config docs are [THRUSTMASTER_CONFIG.md](THRUSTMASTER_CONFIG.md) and
[GPRO_CONFIG.md](GPRO_CONFIG.md).

## Reference handlers

Read these in roughly increasing complexity:

- [`an08.py`](../boards/an08.py): read-only analog input, no indicators (simplest).
- [`sw14.py`](../boards/sw14.py): switches with per-state RGB indicator schemes.
- [`qd04.py`](../boards/qd04.py): encoders with absolute/incremental modes and LED rings.
- [`thrustmaster.py`](../boards/thrustmaster.py): a commercial joystick, read via raw HID reports.
- [`gpro.py`](../boards/gpro.py): a commercial keyboard with RGB, driven through a daemon.

See also [DEVICE_SPECS.md](DEVICE_SPECS.md) and [CONTROL_MAPPINGS.md](CONTROL_MAPPINGS.md)
for how a board's controls surface to application code once the handler exists.
