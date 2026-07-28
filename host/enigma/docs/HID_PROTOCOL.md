<!-- SPDX-License-Identifier: MIT -->
# Enigma HID Protocol

This document describes the wire protocol for **Enigma-family boards**, custom
hardware designed and built for this project. The library also drives two
third-party devices (Thrustmaster T.16000M joystick and Logitech G Pro keyboard)
whose protocols are documented in the [appendix](#appendix-third-party-device-protocols)
for reference; they do not use the Enigma protocol.

> [!NOTE]
> **USB identifiers.** Enigma boards enumerate with Espressif's default USB
> identifiers, `VID 0x303A` / `PID 0x1001` (defined as `ENIGMA_VID` / `ENIGMA_PID`
> in [`manager.py`](../manager.py)). `0x303A` is Espressif's own USB-IF-registered
> vendor ID and `0x1001` is the default product ID shipped with ESP-IDF's USB
> examples; no application-specific identifier was ever reserved for this project.
> The host matches boards on this VID/PID pair, so any other ESP32-S3 device left
> on the ESP-IDF defaults would also match. A production release would reserve its
> own PID (Espressif allocates them free under `0x303A`) or an independent VID
> from USB-IF.

Every table below lists **payload offsets**: byte 0 of a payload is wire byte 5
(the first byte after the opcode and sequence number). All multi-byte integers
are little-endian.

---

## Enigma-Family Boards

The board family is defined by the `BoardVariant` enum in the firmware
([`Board.h`](../../../firmware/Enigma/Board.h)). Three variants are implemented
today; the remainder are planned and, by design, reuse the same 64-byte framing,
sequence numbering, and identity / liveness / config machinery. Only the
implemented variants have documented per-variant payloads (see
[Per-Variant Payloads](#per-variant-payloads)); the planned rows below reserve
their variant IDs and type strings.

| Variant ID | Type string | Status | Description |
|-----------|-------------|--------|-------------|
| 1 | `SW14` | Implemented | 14 illuminated toggle / momentary / radio switches with RGB indicators |
| 2 | `BM16` | Deprecated | 16 illuminated pushbuttons |
| 3 | `AN08` | Implemented | 8-channel 10-bit ADC (knobs, sliders) |
| 4 | `QD04` | Implemented | 4 quadrature encoder knobs with per-key LED rings |
| 5 | `UD08` | Planned | 8 incremental up/down counters with OLED displays |
| 6 | `SC16` | Planned | 16-channel servo output controller |
| 7 | `DC04` | Planned | 4 animated LCD displays |
| 8 | `RL16` | Planned | 16-channel relay output |
| 9 | `LC04` | Planned | 4 WS2812 LED strings, up to 256 elements each |
| 10 | `AU04` | Planned | 4 dual-channel audio soundclip players |
| 11 | `AC08` | Planned | 8-channel buffered analog output |
| 12 | `MO04` | Planned | 4 bidirectional PWM motor-bridge controllers |

Boards are addressed 0-15 via physical DIP switches. The library identifies a
board by the string `<TYPE>-<addr02d>`, e.g. `SW14-03`.

> [!NOTE]
> **Hotplugging is supported.** The host re-enumerates the USB bus on every poll
> tick, so boards can be attached or removed while the application is running. A
> newly connected board is discovered, configured against its stored CRC, and
> brought online automatically; a removed board is dropped from the roster. No
> restart is needed. The host also attempts to reopen its device handles after a
> system sleep/wake (but see the known issue below).

> [!NOTE]
> **Known issue: macOS sleep/wake.** After the Mac sleeps and wakes, the boards
> sometimes fail to re-enumerate cleanly, and the host does not pick them back up.
> Physically unplugging and reconnecting the USB-C ports brings them back. The
> root cause has not been investigated. In practice this rarely matters: an
> always-on game installation is not usually put to sleep, so the case seldom
> comes up.

### Why vendor reports

Enigma boards use **HID vendor-defined reports** (usage page `0xFF`) rather than
standard keyboard, mouse, or gamepad reports. Standard HID usage pages have no
semantics for commands like "write an RGB animation config to NVM" or "report
an encoder position in absolute or incremental mode." Vendor reports give the
firmware complete freedom to define the packet layout, enable bidirectional
command/response framing, and support the per-control configurability that makes
the boards useful as sim hardware. The tradeoff is that no generic HID driver
understands them; the library is the only thing that knows how to talk to them.

---

## Frame Format

Every report in both directions is exactly **64 bytes**, zero-padded.

| Wire bytes | Field | Type | Notes |
|-----------|-------|------|-------|
| 0 | opcode | uint8 | command or response code |
| 1-4 | sequence number | uint32 LE | wraps at `0xFFFFFFFF`, restarts at 1 |
| 5-63 | payload | bytes | command-specific, zero-padded |

The host assigns sequence numbers when sending commands. Responses echo the
sequence number of the command they answer.

---

## Host -> Device Commands

| Opcode | Name | Brief | Response |
|--------|------|-------|----------|
| `0x01` | `RESET` | Reset states and indicators to stored config; sync timebase | `ACK` |
| `0x02` | `GETCONFIG` | Request CONFIGREPORT | `CONFIGREPORT` |
| `0x03` | `SETCONFIG` | Write per-control config to NVM | `ACK` |
| `0x04` | `SETSTATE` | Set the current value of a control | `ACK` |
| `0x05` | `GETSTATE` | Request current state of a control | `REPORTSTATE` |
| `0x06` | `SETINDICATOR` | Update indicator appearance without touching NVM | none |
| `0x07` | `SETBRIGHTNESS` | Set global LED brightness | `ACK` |
| `0x08` | `STATUS` | Liveness ping | `ACK` |
| `0x0D` | `SETLOGLEVEL` | Control device-side log verbosity | `ACK` |
| `0x0E` | `SETBLANKING` | Blank / unblank all indicators | `ACK` |
| `0x0F` | `PULSE` | *Disabled; see note below* | none |
| `0x10` | `ENABLE` | Enable or disable individual controls by bitmask | none |

### 0x01 RESET

Applies stored NVM config to all controls and resets their states. `timebase_ms`
synchronizes animation timers across boards so blinking patterns stay
phase-coherent.

| Offset | Field | Type | Notes |
|--------|-------|------|-------|
| 0-3 | timebase_ms | uint32 LE | shared animation timebase |

### 0x02 GETCONFIG

No payload. Response: `CONFIGREPORT`.

### 0x03 SETCONFIG

Writes configuration for one control to NVM. Payload is variant-specific; see
[per-variant payloads](#per-variant-payloads). Config writes are infrequent;
typically only on first connect when the board's stored CRC does not match the
host's computed config CRC.

### 0x04 SETSTATE

Sets the current value of a control and updates its indicator.

| Offset | Field | Type | Notes |
|--------|-------|------|-------|
| 0 | control_num | uint8 | 1-based |
| 1+ | state_data | variant-specific | see per-variant payloads |

### 0x05 GETSTATE

| Offset | Field | Type | Notes |
|--------|-------|------|-------|
| 0 | control_num | uint8 | 1-based |

Response: `REPORTSTATE`.

### 0x06 SETINDICATOR

Updates the visual appearance of a control's indicator across all states without
touching NVM and without changing the control's logical state. Used for runtime
scheme changes.

| Offset | Field | Type | Notes |
|--------|-------|------|-------|
| 0 | control_num | uint8 | 1-based |
| 1+ | indicator_data | variant-specific | see per-variant payloads |

No response.

### 0x07 SETBRIGHTNESS

| Offset | Field | Type | Notes |
|--------|-------|------|-------|
| 0 | brightness | uint8 | 0=off, 255=full |

Applies to all LED outputs on the board.

### 0x08 STATUS

No payload. Response: `ACK`. Used as a liveness check.

### 0x0D SETLOGLEVEL

| Offset | Field | Type | Notes |
|--------|-------|------|-------|
| 0 | level | uint8 | 0=error, 1=warning, 2=info, 3=debug |

### 0x0E SETBLANKING

Overrides all indicator outputs. Useful for "lights out" mode and in-game
disruption effects.

| Offset | Field | Type | Notes |
|--------|-------|------|-------|
| 0 | mode | uint8 | 0=off, 1=on, 2=disruption |
| 1 | duration_tenths | uint8 | DISRUPTION only: wind-down duration in tenths of a second |

**Disruption mode** flickers all indicators at increasing off state before going fully
blank. `duration_tenths` controls how long the wind-down phase lasts.

### 0x0F PULSE

> [!WARNING]
> **PULSE is disabled.** At maximum brightness, the combined current draw of all
> LEDs on SW14 and QD04 boards exceeds what the onboard LDO can supply, causing
> a brownout. The command is accepted but is a no-op for all Enigma boards.

### 0x10 ENABLE

Enables or disables individual control channels. Disabled controls do not
generate `REPORTSTATE` messages.

| Offset | Field | Type | Notes |
|--------|-------|------|-------|
| 0-1 | mask | uint16 LE | bit N-1 corresponds to control N; 1=enabled, 0=disabled |

No response.

---

## Device -> Host Responses

| Opcode | Name | Brief |
|--------|------|-------|
| `0x09` | `REPORTSTATE` | Spontaneous state-change notification |
| `0x0A` | `ACK` | Response to a command |
| `0x0B` | `CONFIGREPORT` | Board identity and NVM CRC |
| `0x0C` | `LOGMSG` | Device log message |

### 0x09 REPORTSTATE

Sent whenever an enabled control changes state. The host does **not** ACK this
message.

| Offset | Field | Type | Notes |
|--------|-------|------|-------|
| 0 | control_num | uint8 | 1-based |
| 1+ | state_data | variant-specific | see per-variant payloads |

### 0x0A ACK

| Offset | Field | Type | Notes |
|--------|-------|------|-------|
| 0 | status | uint8 | 0=ok, 1+=error |
| 1-56 | text | 56 bytes | null-padded ASCII error message |

Multi-line error text is split across multiple ACK messages; the host accumulates
chunks until a `\n` byte is seen.

### 0x0B CONFIGREPORT

| Offset | Field | Type | Notes |
|--------|-------|------|-------|
| 0-3 | board_type | 4 bytes ASCII | e.g. "SW14" |
| 4 | protocol_version | uint8 | |
| 5 | hw_version | uint8 | |
| 6 | sw_version | uint8 | |
| 7 | variant | uint8 | see variant table above |
| 8 | address | uint8 | 0-15 |
| 9-12 | crc32 | uint32 LE | CRC of all NVM config data |

The host compares `crc32` against its own computed CRC to decide whether to
upload a fresh config via `SETCONFIG`.

### 0x0C LOGMSG

| Offset | Field | Type | Notes |
|--------|-------|------|-------|
| 0 | level | uint8 | 0=error, 1=warning, 2=info, 3=debug |
| 1-58 | text | 58 bytes | null-padded ASCII chunk |

Chunks accumulate on the host until a `\n` byte is seen, then printed as a
single line.

---

## Variant Behavior

The three implemented variants share one protocol but differ in what they can be told to do
and what they report back. This section summarizes those differences; the exact
byte layouts follow in [Per-Variant Payloads](#per-variant-payloads).

### Standardized across all variants

The framing and the identity / liveness / config machinery are identical on every
board, regardless of variant:

- **Frame format** is always 64 bytes: opcode, sequence number, payload.
- **`REPORTSTATE` envelope** is uniform: opcode `0x09`, byte 0 is always
  `control_num`. Only the `state_data` that follows byte 0 is variant-specific.
- **`ACK`, `CONFIGREPORT`, and `LOGMSG`** have the same layout on every board.
- **Identity, liveness, and enable** commands (`GETCONFIG` / `CONFIGREPORT`,
  `STATUS`, `RESET`, `SETLOGLEVEL`, `ENABLE`) behave identically everywhere.

In other words, a generic host can enumerate any board, read its identity, check
its CRC, ping it, and mask its channels without knowing the variant. Only
`SETCONFIG`, `SETSTATE`, `SETINDICATOR`, and the `state_data` tail of
`REPORTSTATE` require variant-specific handling.

### Command support by variant

Boards with no indicators or actuation (AN08) accept the actuation commands but
treat them as no-ops.

| Command | SW14 | QD04 | AN08 |
|---------|------|------|------|
| `RESET` | yes | yes | yes |
| `GETCONFIG` / `CONFIGREPORT` | yes | yes | yes |
| `SETCONFIG` | yes | yes | yes |
| `GETSTATE` | yes | yes | yes |
| `STATUS` | yes | yes | yes |
| `ENABLE` | yes | yes | yes |
| `REPORTSTATE` | yes | yes | yes |
| `SETSTATE` | yes | yes | no-op |
| `SETINDICATOR` | yes | yes | no-op |
| `SETBRIGHTNESS` | yes | yes | no-op |
| `SETBLANKING` | yes | yes | no-op |

### Configuration differences

`SETCONFIG` is the most variant-specific command. Payload size and content
reflect what each board actually has to configure:

| Aspect | SW14 | QD04 | AN08 |
|--------|------|------|------|
| Payload size | 46 bytes (fixed) | variable (base + mode-dependent tail) | 10 bytes (fixed) |
| Indicator config | 3 per-state RGB blocks | dial ring, overlay, blend mode | none |
| Reporting toggle | per-state `report` byte | `button_reports` byte | `enabled` byte |
| Input conditioning | none | count mode (absolute / incremental), A/B reverse | min/max mV, deadband, gamma, invert |

### Reporting differences

Every board reports through `REPORTSTATE`, but what triggers a report, the shape
of the `state_data`, and how you silence a channel all differ:

| Aspect | SW14 | QD04 | AN08 |
|--------|------|------|------|
| Report fires when | a switch enters a state whose `report` byte is 1 | position changes, or a button changes while `button_reports` is 1 | raw reading moves more than `deadband` counts |
| `state_data` | `value` (uint8, 0-2) | absolute: position + button; incremental: delta + button | `raw` (uint16, 0-1023) |
| Absolute vs relative | not applicable | selectable per control (`mode_flags` bit 3) | absolute only |
| Silence a channel | set the state's `report` to 0, or clear its `ENABLE` mask bit | set `button_reports` to 0 (button only), or clear its `ENABLE` mask bit | set `enabled` to 0, raise `deadband`, or clear its `ENABLE` mask bit |

`ENABLE` is the one silencing mechanism common to all three: clearing a control's
mask bit stops its `REPORTSTATE` traffic regardless of variant.

---

## Per-Variant Payloads

### SW14

14 illuminated toggle / momentary / radio switches. Each control has up to
three states with independent RGB indicator configurations.

**Switch types:**

| Value | Name | States |
|-------|------|--------|
| 0 | mom-off-mom | 3 (momentary-on / off / momentary-on) |
| 1 | momentary | 2 (pressed / released) |
| 2 | toggle | 2 (on / off) |
| 3 | radio | 2 (on / off, mutually exclusive within group) |

Radio buttons share a group number (1-14). When any member turns on the firmware
automatically turns the others off; no host intervention needed.

**SETCONFIG payload (46 bytes):**

| Offset | Field | Type | Notes |
|--------|-------|------|-------|
| 0 | control_num | uint8 | 1-based |
| 1 | switch_type | uint8 | see switch types above |
| 2 | default_state | uint8 | 0-2 |
| 3 | group | uint8 | 0=no group, 1-14=radio group |
| 4-17 | state_0_cfg | 14 bytes | per-state config (below) |
| 18-31 | state_1_cfg | 14 bytes | per-state config |
| 32-45 | state_2_cfg | 14 bytes | per-state config |

All three state configs are always present, even for types that only use two
states.

**Per-state config (14 bytes):**

| Offset | Field | Type | Notes |
|--------|-------|------|-------|
| 0 | report | uint8 | 1=send REPORTSTATE when entering this state, 0=silent |
| 1-3 | color1 | 3 bytes | RGB |
| 4-6 | color2 | 3 bytes | RGB, alternating color for blink/fade |
| 7 | mode | uint8 | 0=solid, 1=blink, 2=fade |
| 8-9 | period_ms | uint16 LE | animation cycle period |
| 10-11 | duty_ms | uint16 LE | on-time within each cycle (<= period_ms) |
| 12-13 | hold_ms | uint16 LE | minimum hold before next transition |

**SETSTATE payload:**

| Offset | Field | Type | Notes |
|--------|-------|------|-------|
| 0 | value | uint8 | 0-2 |

**SETINDICATOR payload (39 bytes after control_num):**

Three consecutive per-state indicator blocks (13 bytes each). Same layout as the
per-state config above but without the `report` byte:

| Offset | Field | Type | Notes |
|--------|-------|------|-------|
| 0-2 | color1 | 3 bytes | RGB |
| 3-5 | color2 | 3 bytes | RGB |
| 6 | mode | uint8 | 0=solid, 1=blink, 2=fade |
| 7-8 | period_ms | uint16 LE | |
| 9-10 | duty_ms | uint16 LE | |
| 11-12 | hold_ms | uint16 LE | |

**REPORTSTATE payload:**

| Offset | Field | Type | Notes |
|--------|-------|------|-------|
| 0 | value | uint8 | 0-2 |

---

### QD04

4 quadrature encoder knobs with multi-LED rings and integrated push buttons.

**SETCONFIG payload:**

| Offset | Field | Type | Notes |
|--------|-------|------|-------|
| 0 | control_num | uint8 | 1-based |
| 1 | num_leds | uint8 | physical LED count in ring; sent as 10 in incremental mode |
| 2 | button_mode | uint8 | 0=momentary, 1=toggle |
| 3 | button_reports | uint8 | 1=send REPORTSTATE on button changes, 0=silent |
| 4+ | dial_cfg | variable | dial config (below) |

**Dial config base (11 bytes):**

| Offset | Field | Type | Notes |
|--------|-------|------|-------|
| 0 | mode_flags | uint8 bitset | see bitset table below |
| 1 | active_render | uint8 | 0-5, see render table below |
| 2-5 | overlay_argb | 4 bytes | A + R + G + B |
| 6 | anim_mode | uint8 | 0=solid, 1=blink, 2=fade |
| 7-8 | anim_period_ms | uint16 LE | |
| 9-10 | anim_duty_ms | uint16 LE | |

**`mode_flags` bitset:**

| Bit | Meaning |
|-----|---------|
| 0 | Background: 0=gradient, 1=ranged/multi-zone |
| 1 | Active region: 0=bar, 1=tick (single LED) |
| 2 | A/B wiring reversed |
| 3 | Count mode: 0=absolute, 1=incremental (LEDs not driven) |

**`active_render` (blend mode for the active LED region):**

| Value | Mode |
|-------|------|
| 0 | Brighten (inactive at 25%, active at 100%) |
| 1 | Replace (active shows overlay color, ignores ring color) |
| 2 | Additive (ring + overlay, clamped at 255) |
| 3 | Multiply (ring x overlay / 255) |
| 4 | Screen (255 - ((255-ring) x (255-overlay) / 255)) |
| 5 | Alpha-blend (lerp from ring to overlay using overlay alpha) |

Alpha in `overlay_argb` is only meaningful for mode 5; set to `0xFF` otherwise.

**Mode-specific tail** follows the dial config base. For gradient background
(mode_flags bit 0 = 0):

| Offset | Field | Type | Notes |
|--------|-------|------|-------|
| 0-2 | start_rgb | 3 bytes | ring color at position 0 |
| 3-5 | end_rgb | 3 bytes | ring color at full scale |

For ranged / multi-zone background (mode_flags bit 0 = 1):

| Offset | Field | Type | Notes |
|--------|-------|------|-------|
| 0 | num_zones | uint8 | 1-12 |
| 1+ | zones | 4 bytes each | one block per zone (below) |

Each zone block (4 bytes):

| Offset | Field | Type | Notes |
|--------|-------|------|-------|
| 0 | threshold | uint8 | 1-based LED position where zone starts |
| 1-3 | color_rgb | 3 bytes | zone color |

**SETSTATE payload:**

| Offset | Field | Type | Notes |
|--------|-------|------|-------|
| 0 | position | uint8 | 0 to num_leds-1 |
| 1 | button | uint8 | 0=released, 1=pressed |

**REPORTSTATE payload (absolute mode):**

| Offset | Field | Type | Notes |
|--------|-------|------|-------|
| 0 | position | uint8 | |
| 1 | button | uint8 | |

**REPORTSTATE payload (incremental mode):**

| Offset | Field | Type | Notes |
|--------|-------|------|-------|
| 0 | delta | int8 | negative=counter-clockwise, positive=clockwise |
| 1 | button | uint8 | |

---

### AN08

8-channel 10-bit ADC for analog knobs and sliders. Read-only: `SETSTATE`,
`SETINDICATOR`, `SETBLANKING`, and `SETBRIGHTNESS` are no-ops on this board.

**SETCONFIG payload (10 bytes):**

| Offset | Field | Type | Notes |
|--------|-------|------|-------|
| 0 | control_num | uint8 | 1-based |
| 1-2 | sensor_min_mv | uint16 LE | minimum input voltage in millivolts |
| 3-4 | sensor_max_mv | uint16 LE | maximum input voltage in millivolts |
| 5 | deadband | uint8 | minimum raw ADC change before reporting, default 2 |
| 6-7 | gamma_x1000 | uint16 LE | linearity: 1000=linear, <1000=log, >1000=exp |
| 8 | invert | uint8 | 0=normal, 1=invert ADC reading |
| 9 | enabled | uint8 | 0=channel disabled, 1=enabled |

Voltages are packed as integer millivolts; the firmware converts to ADC counts
using its known reference voltage. `gamma_x1000` range is approximately
100-65535.

**REPORTSTATE payload:**

| Offset | Field | Type | Notes |
|--------|-------|------|-------|
| 0-1 | raw | uint16 LE | 0-1023, post-pipeline ADC reading |

---

## Appendix: Third-Party Device Protocols

The library supports two third-party input devices alongside Enigma boards.
Neither uses the Enigma protocol. Their wire formats are documented here for
reference; this information took significant research to track down and is not
well-documented publicly.

---

### Thrustmaster T.16000M

**VID `0x044F`, PID `0xB10A`**

A standard USB HID joystick. The library reads raw reports directly without any
command exchange. The side switch on the base identifies which stick instance
(port or starboard) a device maps to; the library reads this from the first
report received after connection.

**Report layout (8 bytes):**

| Bytes | Field | Notes |
|-------|-------|-------|
| 0 | Button bitset A | bit 0=trigger, bit 1=rear, bit 2=left-side, bit 3=right-side |
| 1 | Button bitset B | reserved |
| 2 | Hat + side switch | bit 5=right-stick flag; low 4 bits = hat direction |
| 3-4 | X axis | uint16, center=8192; mapped to -1.0...+1.0 |
| 5-6 | Y axis | uint16, center=8192; mapped to -1.0...+1.0 |
| 7 | Z axis (twist) | uint8, center=128; mapped to -1.0...+1.0 |

**Hat encoding (low 4 bits of byte 2):**

| Nibble | Direction |
|--------|-----------|
| `0x0` | N |
| `0x1` | NE |
| `0x2` | E |
| `0x3` | SE |
| `0x4` | S |
| `0x5` | SW |
| `0x6` | W |
| `0x7` | NW |
| `0xF` | center |

The library converts hat direction to a bitset on the host side: bit 0=N,
bit 1=E, bit 2=S, bit 3=W. Diagonal positions set two bits simultaneously.

> [!NOTE]
> **The side switch drives inside/outside button mapping.** The T.16000M is an
> ambidextrous stick, so a matched pair reads as mirror images: the two thumb
> buttons that flank the stick are on opposite physical sides depending on which
> hand the stick is set up for. The side switch (byte 2, bit 5) reports that
> setting, and the library reads it from the first report after connection to
> decide which of the two side buttons is `ButtonInside` (toward ship center) and
> which is `ButtonOutside` (toward the exterior). Game code then refers to the
> buttons by those semantic names and gets consistent behavior across the port
> and starboard sticks without caring about the raw bit assignment.

---

### Logitech G Pro Keyboard

**VID `0x046D`, PID `0xC339`**

The G Pro uses Logitech's proprietary USB HID protocol. The library does **not**
speak to the keyboard over USB directly; it connects to a local **`gpro_daemon`**
process via a Unix socket (`/tmp/gpro_daemon.sock`), which holds the USB handle
and exposes a simplified interface. If the daemon is not running, the keyboard
is silently unavailable.

The RGB commands go to the keyboard's vendor control interface (HID usage page
`0xFF43`); key events come from its standard keyboard interface. This protocol
was reverse-engineered; it is not published by Logitech, and the full RGB feature
set is larger than what is documented here.

#### Daemon socket framing

Everything the library sends the daemon is one message:

| Bytes | Field | Notes |
|-------|-------|-------|
| 0 | size | HID report length that follows: `20` or `64` only |
| 1..size | data | the HID output report, zero-padded to `size` |

The daemon validates `size` (rejects anything but 20 or 64), then writes exactly
`size` bytes to the RGB interface with `hid_write`. Each write draws a short
response report from the keyboard, which the daemon reads and discards. From the
library's side the calls are fire-and-forget.

#### RGB output reports

Three report types drive per-key color. All are zero-padded to their stated
length.

**Set keys (64-byte report)** carries up to 14 key colors:

| Offset | Field | Notes |
|--------|-------|-------|
| 0-7 | header | fixed bytes `12 FF 0C 3A 00 01 00 0E` |
| 8+ | key blocks | up to 14 blocks of 4 bytes: `key_id, R, G, B` |

`key_id` is the standard USB HID keyboard usage code for the key (page `0x07`:
`A`=`0x04`, `1`=`0x1E`, `SPACE`=`0x2C`, `LSHIFT`=`0xE1`, and so on; the full set
the library addresses is listed in [GPRO_CONFIG.md](GPRO_CONFIG.md)).

**Commit (20-byte report)** latches the colors staged by the set-keys reports:

| Offset | Field | Notes |
|--------|-------|-------|
| 0-7 | header | fixed bytes `11 FF 0C 3A 00 01 00 0E` |

**Finalize (20-byte report)** applies the committed frame to the LEDs:

| Offset | Field | Notes |
|--------|-------|-------|
| 0-3 | header | fixed bytes `11 FF 0C 5A` |

#### Update sequence

To repaint the keyboard, the library:

1. Splits the target key list into batches of 14 and sends one **set-keys** report
   per batch (a short inter-packet delay, ~5 ms, keeps the keyboard from dropping
   packets).
2. Sends one **commit** (~10 ms settle).
3. Sends one **finalize**.

A whole-keyboard refresh is therefore several set-keys reports followed by a
single commit and finalize.

#### Logo / native effects

The circular logo is a separate lighting zone driven by Logitech's native-effect
command rather than the per-key protocol:

| Offset | Field | Notes |
|--------|-------|-------|
| 0-3 | header | fixed bytes `11 FF 0D 3C` |
| 4 | zone | `0x01` = logo |
| 5 | effect | `0x00` = off (solid/other effect IDs exist but are unused) |
| 6-8 | R, G, B | effect color |

The daemon issues `11 FF 0D 3C 01 00 00 00 00` at startup to kill the logo so it
does not glow independently of the key field.

#### Key events (keyboard -> host)

Key presses flow the other way: the daemon forwards each keyboard input report to
the library over the socket as a `0xFF` marker byte followed by the 8-byte
standard HID keyboard report (modifier byte, reserved byte, up to six usage
codes). The `0xFF` marker distinguishes an inbound key event from an RGB
response.
