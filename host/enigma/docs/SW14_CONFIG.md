# SW14 Switch Panel Configuration

The SW14 board provides up to 14 illuminated switches with per-switch RGB LEDs.

Each board is configured by a JSON file that describes every switch's type,
default position, and per-state indicator behavior. That config is written
directly to non-volatile storage on the board itself; startup is near-instant
and the board operates correctly even if the host hasn't finished booting.
Each signal line includes hardware ESD protection.

The board has a connector for off-board 5V power to supply the switch
indicators independently of the USB regulator. External power should always be
used when LEDs are active; the onboard regulator can power the microcontroller
over USB alone for a single SW14, but for multiple, always use external power.
See the brightness guidance in the Color Specification section.

The `name` field in the JSON is the **panel name**. Multiple boards (of any mix
of types (SW14, QD04, AN08) can share the same panel name; the code generator
aggregates them into one logical class. A life support panel that spans two SW14
boards and one QD04 board can all be named `"LifeSupport"` and accessed as a
single `LifeSupport` object in generated code.

See [CONTROL_MAPPINGS.md](CONTROL_MAPPINGS.md) for how panel names map to
physical boards.

## File Structure

```json
{
  "name": "PanelName",
  "controls": [
    { ... }
  ]
}
```

## Control Properties

| Property | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `control_num` | int | Yes | | Hardware port (1-14) the switch is wired to |
| `name` | string | Yes | | Control identifier in generated code |
| `desc` | string | No | `""` | Human-readable description |
| `type` | string | Yes | | Logical switch type (see below) |
| `default_state` | int | No | `0` | State on boot and reset |
| `group` | int | No | `0` | Group number; 0 = independent |
| `enabled` | bool | No | `true` | `false` freezes the control: the firmware ignores its input and holds its state and LED (see [Disabling controls](#disabling-controls-enabled)) |
| `state_0` | object | Yes | | Center / off / neutral state config |
| `state_1` | object | Yes | | First active state config |
| `state_2` | object | No | `null` | Second active state (momoffmom only) |
| `schemes` | object | No | | Named alternate visual schemes (see [Schemes](#schemes)) |

### About `control_num`

Port number matches the hardware wiring, not a logical index. If you only have
switches on ports 1, 5, and 9, define only those three controls.

---

## Switch States

Every switch has up to three states regardless of the physical hardware:

| State | Meaning |
|-------|---------|
| `0` | Neither pole active: the center or "off" (non-conducting) state. |
| `1` | One pole active: pressed, flipped on, or held toward one end. |
| `2` | The other pole active: used only by the three-position type. |

Physical switches map onto these states according to the **logical type** you
configure. The firmware handles the logic; the hardware itself is just switches.

The three pins on the XH connector for each switch map directly to these states.
Looking down at the top of the PCB, from top to bottom: **state 1, common,
state 2**. For a two-state switch, only one signal pin is used; the other is
left unconnected.

---

## Logical Switch Types

The type you configure determines what the *firmware* does with the switch's
physical pole signals; it is not a description of the physical switch.

### toggle

**Physical hardware:** a pushbutton (single pole, momentary), the same hardware as
`button`. The firmware latches the state. Each press alternates between state 0
and state 1; the firmware remembers which it's in.

**Use for:** power switches, enable/disable toggles, settings that persist until
changed.

### button  *(aliases: momentary, pushbutton)*

**Physical hardware:** a pushbutton with one pole wired. Only one pole is
connected; the other is ignored. State 1 while held, state 0 on release. The
firmware does no latching.

**Use for:** fire buttons, confirm actions, anything that should only be active
while physically held.

### momoffmom  *(three-position)*

Designed for physical switches that have a position on each side of center
(rockers, levers, bat-handle toggles), whether or not the end positions are
momentary. Any of these work:

- Any 2- or 3-position rocker/toggle with spring return (both ends momentary, center stable)
- Any 2- or 3-position rocker/toggle with physical detents at all three positions
- Two separate axes of a digital joystick in "+" configuration, each wired to a different port
  and configured as the same `momoffmom` named composite control (this will not work for a
  joystick that can do NW/NE/SW/SE).


State 0 is center/neutral (neither pole active). State 1 is one end, state 2
is the other. When an end is released the firmware returns the control to state
0. When the physical switch has hard detents at the ends, "released" means the
switch is moved back to center.  A 3-position switch can be configured to report
only the poles by setting state 0 to report: false.

**Use for:** anything that needs 2-3 possible states, usually in the form of a
rocker, lever, or key switch.

### radio group

Any physical switch type but with firmware-level mutual exclusion inside a
group: only one member can be in a non-zero state at a time. When one turns on,
the others are automatically forced to state 0 by the firmware with no host code
involved.

Two things identify a radio group:

1. **`group` number** (same non-zero integer): used by the firmware for
   hardware-level mutual exclusion.
2. **`name`** (same string): used by the library for host-side cache
   consistency.

Both must match for radio exclusion to work end-to-end.

**Use for:** mode selectors, view selectors, any set of options where exactly
one must be active.

---

> [!NOTE]
> **Why momoffmom and pushbutton, not latching toggles?** In serial-play
> environments (arcades, escape rooms, convention demos), the game resets
> between sessions without any human intervention. Momentary switches are
> **physically stateless**: they spring back to neutral on their own. When the
> software resets, the hardware already matches. A latching toggle left in the
> "on" position needs someone to flip it back before the next session. Because
> Enigma can make a physically stateless switch behave stateful in firmware,
> this allows a software level reset to completely reset the game to initial
> state.

---

## State Configuration

Each `state_N` object sets what happens when the switch enters that state: what
the library reports and how the LED looks.

```json
"state_1": {
  "report": 1,
  "value": "armed",
  "hold_ms": 500,
  "colors": "#FFFF00,#000000",
  "mode": "blink",
  "period_ms": 500,
  "duty_cycle_ms": 400
}
```

### State properties

| Property | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `report` | int | No | `0` | `1` = library fires a change event when this state is entered; `0` = silent |
| `value` | string | No | `null` | String the library reports when this state is active (see below) |
| `colors` | string | No | `"#ff0000"` | One or two `#RRGGBB` colors, comma-separated |
| `mode` | string | No | `"solid"` | `"solid"`, `"blink"`, or `"fade"` (omit for solid) |
| `period_ms` | int | No | `1000` | Animation cycle length in milliseconds |
| `duty_cycle_ms` | int | No | `period_ms / 2` | How long the LED stays on the **first** color per cycle |
| `hold_ms` | int | No | `0` | Minimum time the LED stays in this state (milliseconds) |

If you define `state_1` but omit `state_2`, or vice versa, the library copies
whichever one you did define to the other. This applies to toggle, button, and
radio types (not momoffmom). It means a 2-state control wired to either pole
will behave predictably regardless of which of the two active-state keys appears
in the config.

### `report` and when to use `0`

`report: 1` tells the firmware to send a state-change notification when the
switch enters that state. The library receives it and makes `control.changed()`
return `True` on the next update.

`report: 0` is silent: the switch can still enter that state and the LED
changes accordingly, but the library doesn't fire a change event.

**Radio groups are the canonical case for `report: 0` on state 0.** When one
radio member turns on, the firmware automatically drives the others to state 0.
If those state 0 transitions all had `report: 1`, the library would receive a
flood of "this one turned off" events on every button press. With `report: 0`
on state 0, the library gets exactly one event (the member that turned on)
and infers the rest.

```json
"state_0": { "report": 0, "colors": "#111111" },
"state_1": { "report": 1, "value": "cruise", "colors": "#00aaff" }
```

Other uses for `report: 0`:
- The off state of a toggle, when only "on" is meaningful to game code
- Visual-only states (LED feedback with no logic consequence)

### The `value` string

When a state is entered and `report: 1`, the **library** maps the firmware's
integer state (0, 1, or 2) to this string and makes it available as
`control.value`. The firmware itself knows only the integer; the string is a
host-side concept.

```json
"state_1": { "value": "armed", ... },
"state_2": { "value": "safe", ... }
```

```python
if ArmSwitch.ArmPurge == ArmSwitch.ArmPurge.Values.ARMED:
    begin_purge_sequence()
```

> Use the generated identifier (`ArmPurge.ARMED`), not the string `"armed"`.
> A typo in a generated identifier crashes at startup; a typo in a string
> silently matches nothing.

### Hold time (`hold_ms`)

The LED stays in this state's appearance for at least `hold_ms` milliseconds,
even if the switch returns to neutral sooner. If the switch is held longer than
`hold_ms`, the LED changes immediately on release.

Useful for making brief button presses visually distinct and confirming that an
action registered.

---

## Default Animation Mode

`"mode": "solid"` is the default. Don't specify it; only declare `mode` when
using `"blink"` or `"fade"`.

## Animation Modes

### Solid

Static color. `period_ms` and `duty_cycle_ms` are ignored.

```json
"colors": "#00FF00"
```

### Blink

Alternates between the first color and the second (black if only one specified).

```json
"mode": "blink",
"colors": "#FF0000,#000000",
"period_ms": 500,
"duty_cycle_ms": 250
```

- `period_ms`: full on+off cycle length (default 1000 ms)
- `duty_cycle_ms`: time spent on the **first** color per cycle (default half of period)

### Fade

Smoothly crossfades between the two colors over the period.

```json
"mode": "fade",
"colors": "#00FF00,#FFFF00",
"period_ms": 3000,
"duty_cycle_ms": 2000
```

- `period_ms`: full fade cycle length (default 1000 ms)
- `duty_cycle_ms`: time biased toward the **first** color (default half of period;
  2000 out of 3000 means more time near the first color)

---

## Color Specification

One or two `#RRGGBB` values, comma-separated. Hex digits are case-insensitive:
`#FF0000` and `#ff0000` are identical.

```json
"colors": "#FF0000"           // single; second defaults to #000000
"colors": "#FF0000,#00FF00"   // two colors for blink/fade
```

### Perceived brightness: bare LEDs vs illuminated pushbuttons

A bare LED indicator (a pilot light or indicator lamp mounted above a lever or
key switch) appears significantly brighter than the LED inside an illuminated
pushbutton at the same color value. The pushbutton's translucent plastic cap
diffuses and attenuates the light considerably.

Because the cap swallows so much light, an illuminated pushbutton has to be
driven at or near full brightness to look congruous with a bare LED on the same
panel. A bare LED is the opposite: bright even at tiny values, so it gets driven
far lower.

So `#060606` (about 2% per channel) is a dim value used two ways: a comfortable
*lit* state on a bare LED, or a faint off/inactive glow inside a pushbutton cap.
`#202020` (about 13%) reads bright on a bare LED but only softly lit inside a cap.
Full-channel values like `#00ff00` are what a pushbutton needs to look fully lit
(hence the full-channel active states in the panel configs), and are blinding on
a bare LED.

If you're mixing bare LED indicators with illuminated pushbuttons on the same
panel, expect to set bare LED values at roughly a quarter to an eighth of the
equivalent pushbutton value to match perceived brightness.

### Common values

- `#000000`: LED off
- `#202020`: dim gray (visible but not bright; a safe inactive state for pushbuttons)
- `#060606`: very dim gray (used as the standard inactive state in most panel configs)
- `#FF0000`: red
- `#00FF00`: green

---

## Control Groups

### Radio groups

Radio buttons with the same `name` and the same non-zero `group` number form a
mutual-exclusion group. Pressing any member drives the others to state 0
automatically.

```json
{
  "control_num": 10,
  "type": "radio",
  "name": "DriveMode",
  "group": 1,
  "default_state": 1,
  "state_0": { "report": 0, "colors": "#111111" },
  "state_1": { "report": 1, "value": "impulse", "colors": "#0055ff" }
},
{
  "control_num": 11,
  "type": "radio",
  "name": "DriveMode",
  "group": 1,
  "state_0": { "report": 0, "colors": "#111111" },
  "state_1": { "report": 1, "value": "warp", "colors": "#ff8800" }
},
{
  "control_num": 12,
  "type": "radio",
  "name": "DriveMode",
  "group": 1,
  "state_0": { "report": 0, "colors": "#111111" },
  "state_1": { "report": 1, "value": "engage", "colors": "#aa00ff" }
}
```

`state_0` has `report: 0` on all members. When one member turns on, the library
gets one event (the activation) and not three "the others turned off" events.

### Composite controls

Like radio groups, multiple switches sharing the same name and group number
appear as one control in generated code. The difference is purpose: where radio
groups enforce exclusion, composite controls combine independent channels into a
single logical input.

A digital joystick is the typical use case. One momoffmom channel covers three
states (center, up, down). A second channel on the orthogonal axis covers three
more (center, left, right). Grouped together under one name, the library
presents a single control with five distinct values: center, up, down, left,
right. Each channel contributes its non-center state when active, and both
report center when the stick is released.

This works because a spring-centered joystick with cardinal directions can only
activate one axis at a time. It does not work for joysticks that allow diagonal
positions (NW, NE, SW, SE), where both axes are active simultaneously. The
library would see whichever channel reported last, not both at once.

```json
{
  "control_num": 5,
  "type": "momoffmom",
  "name": "NavJoystick",
  "group": 2,
  "state_0": { "report": 1, "value": "center" },
  "state_1": { "report": 1, "value": "up" },
  "state_2": { "report": 1, "value": "down" }
},
{
  "control_num": 6,
  "type": "momoffmom",
  "name": "NavJoystick",
  "group": 2,
  "state_0": { "report": 1, "value": "center" },
  "state_1": { "report": 1, "value": "left" },
  "state_2": { "report": 1, "value": "right" }
}
```

Game code reads a single `NavJoystick` control with values: `center`, `up`,
`down`, `left`, `right`.

---

## Schemes

A scheme is a named alternate visual configuration that can be swapped at
runtime without changing the switch's logical state. Additional schemes let you
restyle indicators to reflect system-wide conditions.

The top-level `state_0`/`state_1`/`state_2` you define on a control **are** its
default scheme, exposed in generated code as `<Panel>.<Control>.Schemes.DEFAULT`.
Named schemes below override those base states; switching a control back to
`DEFAULT` restores the top-level values.

A common use is a `DISABLED` scheme: define one that dims or greys a set of
controls' indicators, then activate it whenever the game should lock those
controls out. Pair it with `enabled: false` (see [Disabling
controls](#disabling-controls-enabled)) to freeze their input as well, so the
controls both look and behave as locked.

Scheme changes are transient. They apply only for the current session and are
returned to the default scheme when the game state resets. Schemes never need
to be explicitly restored in reset code.

For example: the default scheme shows a slow green fade for an active switch.
An `"urgent"` scheme switches it to a fast red blink when the system enters
an alarm state. Same switch, same game state, different visual.

```json
"schemes": {
  "urgent": {
    "state_0": { "colors": "#330000" },
    "state_1": { "colors": "#FF0000,#000000", "mode": "blink", "period_ms": 200 }
  }
}
```

Scheme names are exposed as generated identifiers on the control class. See
[CONTROL_MAPPINGS.md](CONTROL_MAPPINGS.md) for how to activate schemes from game code.

## Disabling controls (`enabled`)

Set `"enabled": false` on a control to freeze it. The firmware skips all state
processing for that control: physical input is ignored, and its reported state
and indicator stay exactly where they are. Controls default to `enabled: true`.

This is a *functional* lock, distinct from a scheme (which only changes
appearance). The two pair naturally: activate a `DISABLED` scheme to grey the
indicator and set `enabled: false` to lock the input, so a control is both dimmed
and inert while the game calls for it. Controls can also be enabled and disabled
at runtime from game code; see [CONTROL_MAPPINGS.md](CONTROL_MAPPINGS.md).

---

## Complete Examples

### Toggle (firmware-latched pushbutton)

```json
{
  "control_num": 2,
  "name": "Ignition",
  "desc": "Engine ignition",
  "type": "toggle",
  "state_0": {
    "report": 1,
    "value": "off",
    "colors": "#202020"
  },
  "state_1": {
    "report": 1,
    "value": "on",
    "colors": "#00FF00,#FFFF00",
    "mode": "fade",
    "period_ms": 3000
  }
}
```

### Three-position arm/safe switch

```json
{
  "control_num": 6,
  "type": "momoffmom",
  "name": "ArmPurge",
  "desc": "Arm purge system",
  "default_state": 2,
  "state_0": {
    "report": 0,
    "colors": "#202020"
  },
  "state_1": {
    "report": 1,
    "value": "armed",
    "colors": "#FFFF00,#000000",
    "mode": "blink",
    "period_ms": 750,
    "duty_cycle_ms": 600
  },
  "state_2": {
    "report": 1,
    "value": "safe",
    "colors": "#00FF00"
  }
}
```

`default_state: 2` means the board boots with this switch showing "safe."

### Action button with minimum-hold feedback

```json
{
  "control_num": 7,
  "type": "button",
  "name": "PurgeAM",
  "desc": "Purge antimatter",
  "state_0": {
    "report": 0,
    "colors": "#202020"
  },
  "state_1": {
    "report": 1,
    "value": "purge",
    "hold_ms": 1000,
    "colors": "#FF0000,#0000FF",
    "mode": "blink",
    "period_ms": 200
  }
}
```

Even a brief tap holds the fast red/blue blink for 1 second so the operator
knows the press registered.

### Radio group (mode selector)

See the DriveMode example in [Radio groups](#radio-groups) above.

---

## See Also

- [QD04_CONFIG.md](QD04_CONFIG.md): quadrature encoder board configuration
- [AN08_CONFIG.md](AN08_CONFIG.md): analog input board configuration
- [CONTROL_MAPPINGS.md](CONTROL_MAPPINGS.md): mapping physical boards to panel names
