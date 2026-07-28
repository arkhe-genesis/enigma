# QD04 Quadrature Encoder Board Configuration

The QD04 board provides up to 4 quadrature encoders with integrated LED rings. The 4-channel limit reflects the number of RMT TX channels the ESP32S3 supports. Daisy-chaining the rings from one encoder to the next would allow more channels per board, but each encoder having its own dedicated chain simplifies wiring and keeps the serial signal clean. Keep encoder leads under 30 cm; longer runs degrade the WS2812 signal and cause dropped or corrupted LED frames.

The board supports encoders with integrated pushbuttons, though buttons are not required. When present, the button is useful for snapping the encoder value to one or more meaningful defaults without turning the knob. A volume control where one press mutes and another restores the previous level is a good example, as is a parameter knob that resets to its nominal value on press.

Each board is configured by a JSON file describing every encoder's behavior and
display. That config is written to non-volatile storage on the board; startup
is near-instant and the board runs correctly before the host has finished
booting. Each signal line includes hardware ESD protection.

The board has a connector for off-board 5V power to supply the LED rings
independently of the USB regulator. External power should always be used when
LEDs are active; the onboard regulator can power the microcontroller over USB
alone, but LED current will damage it if drawn through it. Even with external
power connected, keep color values low. A ring of 23 LEDs at high brightness
draws more current than most power supplies expect, and the display will be
uncomfortably bright in any case. See the color guidance in the Overlay Color
section below.

The `name` field is the **panel name**. Multiple boards of any type can share
the same name; the code generator aggregates them into one logical class. See
[CONTROL_MAPPINGS.md](CONTROL_MAPPINGS.md) for how panel names map to physical
boards.

> [!NOTE]
> **Why rotary encoders?** For the same reason SW14 uses momoffmom switches:
> rotary encoders are **physically stateless**. Unlike a potentiometer, an encoder
> has no fixed home position; it reports movement relative to wherever it is right
> now. When the software resets, the firmware position counter resets to match.
> No human needs to turn the knob back to "12 o'clock" between games. This makes
> encoders well-suited to serial-play environments where unattended resets must
> leave the hardware in a predictable state.

## File Structure

```json
{
  "name": "ConfigName",
  "controls": [
    { ... }
  ]
}
```

## Control Properties

| Property | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `control_num` | int | Yes | | Hardware port (1-4) the encoder is connected to |
| `name` | string | Yes | | Control identifier used in generated code |
| `desc` | string | No | `""` | Human-readable description |
| `num_leds` | int | Yes | | Number of LEDs in the ring (1-255) |
| `button_mode` | string | No | `"momentary"` | `"toggle"` or `"momentary"` |
| `button_reports` | int | No | `1` | 0 = no button reports, 1 = send reports |
| `min_value` | float | Yes | | Minimum logical value |
| `max_value` | float | Yes | | Maximum logical value |
| `default_value` | float | No | midpoint of min/max | Value on boot and reset |
| `default_button` | int | No | `0` | Button state on boot and reset; `0` = released, `1` = pressed |
| `count_mode` | string | No | `"absolute"` | `"absolute"` or `"incremental"` |
| `units` | string | No | `""` | Unit label shown on displays (e.g. `"%"`, `"degC"`) |
| `wrap` | bool | No | `false` | Whether value wraps at min/max |
| `reverse` | bool | No | `false` | Reverse A/B encoder sense |
| `dial` | object | No | dim red gradient | LED display configuration (see below) |
| `acceleration` | object | No | | Speed-based multiplier (incremental mode only) |
| `enabled` | bool | No | `true` | `false` freezes the control: the firmware ignores its input and holds its value and LEDs (see [Disabling controls](#disabling-controls-enabled)) |
| `schemes` | object | No | | Named alternate display schemes (see [Schemes](#schemes)) |

### About `control_num`

The `control_num` is the physical port number (1-4) on the QD04 board where the encoder is connected. This matches the hardware wiring, not a logical index. If you only have encoders on ports 1 and 3, you only define controls 1 and 3.

## Count Mode

At the hardware level, a quadrature encoder outputs two signals (A and B) that
toggle as the shaft turns. The phase relationship between them encodes both
direction and movement: A leads B for clockwise, B leads A for counter-clockwise.
The QD04 firmware counts these transitions. What differs between modes is what
it does with that count.

### Absolute Mode (default)

The firmware maintains an internal position counter clamped to `[0, num_leds]`.
Every time the encoder moves, the counter increments or decrements, and the new
absolute position is reported to the library. The library always knows exactly where
the dial is.

**Hardware fit:** Low-PPR encoders (PPR: pulses per revolution; typically 24 or fewer)
where the step resolution is close enough to the LED count that each detent moves
the indicator one position. The LED ring gives meaningful visual feedback of the
current value.

**Typical use:** 23-LED dials for parameter knobs (pressure, power, temperature)
where the operator can read the current value off the ring at a glance. 23 was
chosen because that is how many LEDs fit around the physical dial used in this
project.

**On reset:** The firmware position counter is set to `default_value` (the
configured default position). Since there is no physical index marker, the display
and the knob's physical position may not agree after a reset if the knob was
moved during the previous session, but from the game's perspective the value is
consistent and known.

### Incremental Mode

The firmware does not track absolute position. Instead, it reports each movement
as a signed delta: how many steps were taken and in which direction. The library
accumulates these deltas and owns the current value entirely.

**Hardware fit:** High-PPR encoders (combination lock dials, precision instrument
knobs, optical encoders) where the physical resolution is far greater than any
practical LED count. There is nothing useful to display on the ring (it is not
driven in this mode), and the value range the encoder controls may be arbitrarily
large or fine.

**Typical use:** Any control where positions do not correspond to specific LEDs,
there are many counts around the dial, or the value range is large enough that
acceleration (fast spin = large jumps, slow spin = fine steps) is needed to
traverse it without tedium.

**On reset:** The library-side accumulated value resets to `default_value`. The
physical shaft position is ignored.

> [!NOTE]
> **No index pulse support.** Some high-PPR encoders include a third channel (Z
> or index) that pulses once per revolution at a fixed home position, useful for
> establishing an absolute reference after startup. The QD04 firmware does not
> currently read or act on the index channel. If your encoder has one, leave it
> unconnected.

In incremental mode, `num_leds` sets the resolution: how many steps it takes to
traverse from `min_value` to `max_value` at 1:1 speed. Higher values give finer
control. Since the LED ring is **not driven** in incremental mode, `num_leds` has
no upper limit (e.g. `"num_leds": 1000` gives 0.001 resolution across a 0-1
range). In Halcyon Dawn, 100PPR dials were used to tune the FTL's spatial phase
balace controls. They did not have LED rings at all and their values were updated
on the nearby LCD screen.

## Dial Configuration

The `dial` object controls how the LED ring displays the current value. The display is composed of two layers:
1. **Background**: The base colors of all LEDs
2. **Active region**: LEDs that represent the current position, rendered on top

```json
"dial": {
  "background_mode": "gradient",
  "start_color": "#000030",
  "end_color": "#060000",
  "active_mode": "bar",
  "active_render": "alpha",
  "overlay_color": "#40141414",
  "animation": {
    "mode": "solid"
  }
}
```

### Dial Property Summary

| Property | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `background_mode` | string | No | `"gradient"` | `"gradient"` or `"ranged"` |
| `start_color` | string | No | `"#0000FF"` | Start color for gradient mode (firmware default is full brightness; use a dim value in practice) |
| `end_color` | string | No | `"#FF0000"` | End color for gradient mode (same caveat) |
| `zones` | array | No | `[]` | Zone definitions for ranged mode |
| `active_mode` | string | No | `"bar"` | `"bar"` or `"tick"` |
| `active_render` | string | No | `"brighten"` | Blend mode (see below) |
| `overlay_color` | string | No | `"#FFFFFF"` | Color for active region (firmware default is full white; use a dim value in practice) |
| `animation` | object | No | `{}` | Animation settings |

If `dial` is omitted entirely, you get a dim red gradient (10-30% brightness) with bar mode and screen blending: this indicates an unconfigured control while staying within safe power limits. The `num_leds` property on the control itself is still required to set the LED count.

## Background Mode

The background is the base color of all LEDs before the active position is rendered.

### Gradient Mode

Creates a smooth color transition across all LEDs from `start_color` (LED 0) to `end_color` (last LED).

```json
"background_mode": "gradient",
"start_color": "#000030",
"end_color": "#060000"
```

**Use for:** Continuous values where position along a spectrum matters (velocity, temperature, throttle).

### Ranged Mode

Divides the LED ring into discrete color zones. Each zone's color indicates a different operating region.

```json
"background_mode": "ranged",
"zones": [
  {"threshold": 4,  "color": "#060000"},
  {"threshold": 8,  "color": "#060600"},
  {"threshold": 14, "color": "#000600"},
  {"threshold": 18, "color": "#060600"},
  {"threshold": 23, "color": "#060000"}
]
```

**The `threshold` value is an LED number (0 to num_leds-1).** LEDs from the previous threshold (or 0) up to this threshold use this color. In the example above:
- LEDs 0-3: dim red (danger low)
- LEDs 4-7: dim yellow (warning low)
- LEDs 8-13: dim green (nominal)
- LEDs 14-17: dim yellow (warning high)
- LEDs 18-22: dim red (danger high)

**Use for:** Parameters with distinct operating regions (pressure gauges, levels with safe/warning/danger zones).

## Active Mode (Bar vs Tick)

```json
"active_mode": "bar"
```

This determines **which LEDs** are considered "active" based on the current position.

| Value | Description |
|-------|-------------|
| `"bar"` | All LEDs from 0 up to and including the current position are active (default) |
| `"tick"` | Only the single LED at the current position is active |

### Bar Mode (default)

Creates a "fill" effect like a progress bar.

**Use for:** Values that represent a quantity or level (throttle, volume, charge level).

### Tick Mode

Creates a "needle" effect like a traditional gauge.

**Use for:** Values where you're selecting a point on a scale (frequency tuning, balance controls).

## Active Render Mode

```json
"active_render": "brighten"
```

This determines **how** active LEDs are visually rendered over the background. This is completely independent of bar/tick mode; it's about the visual blending, not which LEDs are affected.

| Value | Description |
|-------|-------------|
| `"brighten"` | Increase brightness while preserving background color (default) |
| `"replace"` | Replace background with overlay color |
| `"alpha"` | Blend overlay over background using alpha channel |
| `"additive"` | Add overlay RGB to background |
| `"multiply"` | Multiply background by overlay |
| `"screen"` | Inverse multiply (lightens) |

### Brighten (default)

Increases the brightness of active LEDs while preserving their background color. The `overlay_color` brightness determines how much to brighten.

**Use for:** Subtle position indication that doesn't obscure background color information.

### Replace

Completely replaces the background color with `overlay_color` for active LEDs.

**Use for:** Strong, unambiguous position indication where background color isn't important in the active region.

### Alpha

Blends `overlay_color` over the background using the alpha channel. An overlay of `#40141414` (25% dim white) will lighten active LEDs while showing background color through.

**Use for:** Position indication that still shows background color zones (e.g., see whether you're in the yellow warning zone while highlighting current position).

### Additive

Adds `overlay_color` RGB values to the background. Can create bright, saturated colors but may clip to white.

**Use for:** Glowing, energetic effects.

### Multiply

Multiplies background color by `overlay_color`. Useful for darkening or tinting.

**Use for:** Subdued effects, darkening active regions.

### Screen

Inverse of multiply; lightens the image. `Screen(A, B) = 1 - (1-A)(1-B)`

**Use for:** Brightening effects that won't clip to white as easily as additive.

## Overlay Color and Alpha

All color values are case-insensitive: `#FF0000` and `#ff0000` are identical.

A ring of 23 WS2812 LEDs running at full brightness is extremely bright and
draws significant current. Keep color values well below maximum. The
`LifeSupportKnobs1.json` config in this project uses zone colors like `#060000`
(red, ~2% brightness) and `#000600` (green, ~2%), with an overlay of `#141414`
(~8% white). At these levels the display is clearly readable in a dim room
without being painful to look at directly.

Running LEDs near full brightness risks pulling more current than the onboard
USB regulator can supply. See the power supply note in this document.

The `overlay_color` can be specified as:
- `#RRGGBB`: RGB only, alpha defaults to 255 (fully opaque)
- `#AARRGGBB`: Alpha + RGB (note: alpha is first, not last)

For alpha blend mode, the alpha channel controls opacity. Using `#141414` (dim white, ~8% brightness) as the color:
- `#FF141414`: Fully opaque dim white
- `#80141414`: 50% blend (half background, half dim white)
- `#40141414`: 25% blend (mostly background with a faint tint)
- `#00141414`: Fully transparent (no effect)

Avoid full white (`#FFFFFF`) as the RGB component even at low alpha; across 23 LEDs the result is still uncomfortably bright.

## Animation

Animation affects only the active LEDs (the position indicator), not the background. The background remains static while the active region animates.

```json
"animation": {
  "mode": "blink",
  "period_ms": 500,
  "duty_cycle_ms": 250
}
```

### Solid Mode

No animation: static display. This is the default and most common mode.

When using solid mode, `period_ms` and `duty_cycle_ms` are ignored.

### Blink Mode

The active LEDs alternate between showing the overlay and showing the background (overlay off).
- `period_ms`: Total cycle time (default: 1000ms)
- `duty_cycle_ms`: How long the overlay is visible (default: half of period_ms)

**Use for:** Drawing attention to warnings or alerts.

### Fade Mode

The active LEDs smoothly fade the overlay in and out over the period.
- `period_ms`: Total fade cycle time (default: 1000ms)
- `duty_cycle_ms`: Biases time spent with overlay visible vs hidden (default: half of period_ms)

A duty cycle of 750ms with period 1000ms means the overlay spends more time visible than hidden.

**Use for:** Gentle "breathing" effect on the position indicator, pulsing current value.

In my own panels I use animation mode as a signal of interactivity. When a dial is under autopilot control I set the tick to solid; the value is moving but the operator isn't driving it. When control returns to the operator I switch to a slow fade, which reads as an invitation to turn the knob. Schemes make this easy to swap at runtime without touching the underlying dial config.

## Schemes

A scheme is a named alternate display configuration that swaps at runtime without
changing the encoder's value. The top-level display settings you define on a
control (`dial`, background, colors, animation, and so on) **are** its default
scheme, exposed in generated code as `<Panel>.<Control>.Schemes.DEFAULT`. Named
schemes under `schemes` override those base settings; switching a control back to
`DEFAULT` restores them.

A common use is a `DISABLED` scheme: define one that dims or greys a set of dials,
then activate it whenever the game should lock those controls out. Pair it with
`enabled: false` (see [Disabling controls](#disabling-controls-enabled)) to freeze
the encoders as well, so the dials both look and behave as locked. Setting this
in config allows the control to be locked out of interactions from (re)start until
the game code decides to enable it.

Each scheme can override any dial property; unspecified properties inherit from
the default (top-level) dial config:

```json
"schemes": {
  "warning": {
    "background_mode": "gradient",
    "start_color": "#060000",
    "end_color": "#060600",
    "animation": { "mode": "blink", "period_ms": 500 }
  }
}
```

Scheme changes are transient: they apply for the current session and revert to
`DEFAULT` on game reset. See [CONTROL_MAPPINGS.md](CONTROL_MAPPINGS.md) for how to
activate schemes from game code.

> [!IMPORTANT]
> Scheme names become generated identifiers. Use
> `FtlKnobs.PhaseBalance.Scheme = FtlKnobs.PhaseBalance.Schemes.WARNING`,
> not the string `"warning"`: a typo in the identifier crashes immediately, while
> a typo in a string fails silently.

## Disabling controls (`enabled`)

Set `"enabled": false` on a control to freeze it. The firmware skips all
processing for that control: encoder rotation and button input are ignored, and
its reported value and LEDs stay put. Controls default to `enabled: true`. This is
a functional lock, distinct from a scheme (which only changes appearance); the two
pair naturally. Controls can also be enabled and disabled at runtime from game
code; see [CONTROL_MAPPINGS.md](CONTROL_MAPPINGS.md).

## Acceleration Configuration

For incremental mode encoders, acceleration scales the value change based on rotation speed: slow turns make fine adjustments, fast spins make coarse ones.

```json
"acceleration": {
  "max_multiplier": 50,
  "ramp_speed": 40,
  "dead_zone": 8
}
```

| Property | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `max_multiplier` | float | No | `1.0` | Maximum scale factor at high speed |
| `ramp_speed` | float | No | `30.0` | Reports/sec to reach full acceleration |
| `dead_zone` | float | No | `5.0` | Reports/sec below which multiplier stays at 1.0 |

### How It Works

1. **Below dead_zone:** Fine mode; each encoder click moves exactly one step (multiplier = 1.0)
2. **Between dead_zone and ramp_speed:** Accelerating; multiplier ramps up exponentially
3. **At or above ramp_speed:** Full acceleration; each click moves `max_multiplier` steps

The exponential easing (t^2) provides a natural feel: slow at first, then accelerating as you spin faster.

### Choosing Values

For a phase balance control (-pi to +pi, 200 step resolution):
- `dead_zone: 8`: Need to turn deliberately to start accelerating
- `ramp_speed: 40`: Moderate spin reaches full speed
- `max_multiplier: 50`: Full spin traverses the entire range in ~4 clicks

After 500ms of no activity, the system resets to fine mode.

## Complete Examples

### Life Support Pressure Control

A ranged dial showing safe/warning/danger zones with alpha-blended position indicator:

```json
{
  "control_num": 1,
  "name": "ForePressureKnob",
  "desc": "Set Fore Atmospheric Pressure",
  "num_leds": 23,
  "button_reports": 1,
  "min_value": 0,
  "max_value": 6,
  "dial": {
    "background_mode": "ranged",
    "zones": [
      {"threshold": 1,  "color": "#100000"},
      {"threshold": 4,  "color": "#101000"},
      {"threshold": 8,  "color": "#001000"},
      {"threshold": 12, "color": "#101000"},
      {"threshold": 14, "color": "#100000"}
    ],
    "active_render": "alpha",
    "overlay_color": "#101030",
    "animation": {"mode": "solid"}
  }
}
```

### FTL Phase Balance

High-precision phase control with acceleration for quick traversal:

```json
{
  "control_num": 1,
  "name": "PortStbdPhaseBalance",
  "desc": "Trim port/starboard phase",
  "count_mode": "incremental",
  "num_leds": 200,
  "button_reports": 0,
  "min_value": -3.14159265,
  "max_value": 3.14159265,
  "wrap": true,
  "acceleration": {
    "max_multiplier": 50,
    "ramp_speed": 40,
    "dead_zone": 8
  }
}
```

### Throttle with Gradient and Bar Display

Engine throttle showing blue (idle) to orange (full) gradient:

```json
{
  "control_num": 3,
  "name": "Throttle",
  "desc": "Engine throttle",
  "num_leds": 23,
  "button_mode": "momentary",
  "button_reports": 1,
  "min_value": 0.0,
  "max_value": 100.0,
  "dial": {
    "background_mode": "gradient",
    "start_color": "#000020",
    "end_color": "#060200",
    "active_render": "replace",
    "overlay_color": "#000800",
    "animation": {"mode": "solid"}
  }
}
```

## See Also

- [SW14_CONFIG.md](SW14_CONFIG.md): switch panel config reference
- [AN08_CONFIG.md](AN08_CONFIG.md): analog input board config reference
- [CONTROL_MAPPINGS.md](CONTROL_MAPPINGS.md): mapping physical boards to panel names
