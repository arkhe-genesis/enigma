# Thrustmaster T16000M Joystick Configuration

The Thrustmaster handler manages T16000M flight sticks, parsing axis, button, and hat switch data from HID reports.This obviously isn't a device in the Enigma family, but I wanted my game code to be
able to interact with it via the same coding conventions as my own boards.

> [!NOTE]
> My implementation does not incorporate the buttons present on the base of the stick;
> I carved the stick apart and kept only the stick part itself.

## File Structure

```json
{
  "name": "StickName",
  "side_switch": 0,
  "controls": [
    { ... }
  ]
}
```

`side_switch` (int, default `0`) is an optional board-level tag, historically used
to distinguish a port vs starboard stick sharing one config. It is currently
informational only; the handler no longer filters reports by it.

## Control Types

| Type | Description |
|------|-------------|
| `axis` | Analog axis (X, Y, Z twist, slider) |
| `button` | Digital button |
| `hat` | 8-way hat switch |

Every control type also accepts an optional **`enabled`** (bool, default `true`).
Setting `enabled: false` stops the control from being parsed out of HID reports,
so its reported value freezes. Controls can also be enabled and disabled at
runtime from game code.

## Axis Control

```json
{
  "control_num": 1,
  "name": "X",
  "desc": "X axis (left/right)",
  "type": "axis",
  "report_bytes": [3, 4],
  "deadzone": 0.05
}
```

### Axis Properties

| Property | Type | Description |
|----------|------|-------------|
| `control_num` | int | Control identifier (arbitrary, for your reference) |
| `name` | string | Axis name (used in generated code) |
| `desc` | string | Human-readable description |
| `type` | string | Must be `"axis"` |
| `report_bytes` | array | Byte indices in HID report; hardware specific, don't change |
| `report_byte` | int | Single byte index; hardware specific, don't change |
| `deadzone` | float | Center deadzone (0.0 - 1.0), default 0.0 |

**Important:** `report_byte`, `report_bytes`, and `bit` are hardware-specific and must match the T16000M HID report layout. Only `name`, `desc`, and `deadzone` should be modified.

### Single vs Double Byte Axes

The T16000M uses different precisions for different axes:
- X and Y: 16-bit (2 bytes); use `report_bytes: [low, high]`
- Z (twist): 8-bit (1 byte); use `report_byte: n`
- Slider: 8-bit (1 byte); use `report_byte: n`

## Button Control

```json
{
  "control_num": 4,
  "name": "Trigger",
  "desc": "Main trigger",
  "type": "button",
  "report_byte": 0,
  "bit": 0
}
```

### Button Properties

| Property | Type | Description |
|----------|------|-------------|
| `control_num` | int | Control identifier |
| `name` | string | Button name |
| `desc` | string | Human-readable description |
| `type` | string | Must be `"button"` |
| `report_byte` | int | Byte index in HID report |
| `bit` | int | Bit position within byte (0-7) |

## Hat Switch Control

```json
{
  "control_num": 8,
  "name": "Hat",
  "desc": "8-way hat switch",
  "type": "hat",
  "report_byte": 2
}
```

### Hat Properties

| Property | Type | Description |
|----------|------|-------------|
| `control_num` | int | Control identifier |
| `name` | string | Hat name |
| `desc` | string | Human-readable description |
| `type` | string | Must be `"hat"` |
| `report_byte` | int | Byte index in HID report |

### Hat Values

The hat reports 9 possible positions:

| Value | Direction |
|-------|-----------|
| 0 | North (up) |
| 1 | Northeast |
| 2 | East (right) |
| 3 | Southeast |
| 4 | South (down) |
| 5 | Southwest |
| 6 | West (left) |
| 7 | Northwest |
| 8 | Center (neutral) |

## T16000M HID Report Layout

The T16000M sends 64-byte HID reports. Relevant byte positions:

| Bytes | Content |
|-------|---------|
| 0 | Buttons 1-8 (bit-packed) |
| 1 | Buttons 9-16 (bit-packed) |
| 2 | Hat switch (0-8) |
| 3-4 | X axis (16-bit little-endian) |
| 5-6 | Y axis (16-bit little-endian) |
| 7 | Z axis / twist (8-bit) |
| 8 | Slider (8-bit) |

## Examples

### Complete Stick Configuration

```json
{
  "name": "PortStick",
  "controls": [
    {
      "control_num": 1,
      "name": "X",
      "desc": "X axis (left/right)",
      "type": "axis",
      "report_bytes": [3, 4],
      "deadzone": 0.05
    },
    {
      "control_num": 2,
      "name": "Y",
      "desc": "Y axis (forward/back)",
      "type": "axis",
      "report_bytes": [5, 6],
      "deadzone": 0.05
    },
    {
      "control_num": 3,
      "name": "Z",
      "desc": "Z axis (twist)",
      "type": "axis",
      "report_byte": 7,
      "deadzone": 0.02
    },
    {
      "control_num": 4,
      "name": "Trigger",
      "desc": "Trigger button",
      "type": "button",
      "report_byte": 0,
      "bit": 0
    },
    {
      "control_num": 5,
      "name": "ButtonRear",
      "desc": "Rear thumb button",
      "type": "button",
      "report_byte": 0,
      "bit": 1
    },
    {
      "control_num": 6,
      "name": "ButtonLeft",
      "desc": "Left thumb button",
      "type": "button",
      "report_byte": 0,
      "bit": 2
    },
    {
      "control_num": 7,
      "name": "ButtonRight",
      "desc": "Right thumb button",
      "type": "button",
      "report_byte": 0,
      "bit": 3
    },
    {
      "control_num": 8,
      "name": "Hat",
      "desc": "8-way hat switch",
      "type": "hat",
      "report_byte": 2
    }
  ]
}
```

### Slider Axis

```json
{
  "control_num": 9,
  "name": "Slider",
  "desc": "Throttle slider",
  "type": "axis",
  "report_byte": 8,
  "deadzone": 0.0
}
```

## Axis Output

Axes are normalized to the range **-1.0 to +1.0** with 0.0 at center.

## Deadzone Behavior

The deadzone creates a null zone around center that filters out accidental bumps and stick drift. Values inside the deadzone are reported as exactly 0.0; the range outside is smoothly rescaled to +/-1.0, so there's no abrupt jump at the threshold.

Typical values:
- `0.0`: No deadzone, full sensitivity
- `0.05`: 5% deadzone (typical for X/Y)
- `0.02`: 2% deadzone (typical for twist)

With a 10% deadzone:
- Raw 0.09 -> output 0.0 (inside deadzone)
- Raw 0.10 -> output 0.0 (at deadzone edge)
- Raw 0.55 -> output 0.5 (halfway between deadzone and max)
- Raw 1.0 -> output 1.0 (full deflection)

## See Also

- `configs/PortStick.json`: Port flight stick configuration
- `configs/StarboardStick.json`: Starboard flight stick configuration
- `enigma/boards/thrustmaster.py`: Thrustmaster handler implementation
