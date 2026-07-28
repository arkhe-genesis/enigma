# AN08 Analog Input Board Configuration

The AN08 board provides 8 channels of 10-bit analog input via the MCP3008T-I/SL
SPI ADC. It is read-only (no LEDs, buttons, or output controls). Each channel
maps a physical sensor voltage range to a host-side float value.

Each board is configured by a JSON file describing each channel's voltage range,
response curve, and deadband. That config is written to non-volatile storage on
the board and survives power cycles. The board operates autonomously and starts
reporting immediately, before the host has finished booting. Each signal line
includes hardware ESD protection.

The `name` field is the **panel name**. Multiple boards of any type can share
the same name; the code generator aggregates them into one logical class. See
[CONTROL_MAPPINGS.md](CONTROL_MAPPINGS.md) for how panel names map to physical
boards.

> [!NOTE]
> **Physical statefulness (an outlier in the Enigma family).** SW14 switches and
> QD04 encoders were chosen specifically because they carry no physical state that
> needs resetting between games: a momoffmom switch returns to center on release,
> and a rotary encoder has no home position. Analog controls connected via AN08
> (potentiometers, thumb wheels, sliders) do not inherently share this property. 
> A knob left at 75% stays at 75%; a slider left halfway stays halfway. When the game resets,
> the host-side value resets to the spec default, but the physical control is now
> lying about its position until the operator moves it.
>
> For serial-play installations (arcades, escape rooms) this usually means either
> choosing hall-effect sensors or linear pots wired to controls that operators are
> expected to physically zero between sessions, or using AN08 only for inputs where
> the "wrong" starting position is acceptable (throttle levers that default to
> idle and can be pulled back to zero, for instance). My Halcyon Dawn build included
> 6 spring-loaded pedals (for 3-space rotation and translation), which naturally
> return to a predictable position.

## File Structure

```json
{
  "name": "ConfigName",
  "controls": [
    { ... }
  ]
}
```

The `name` key is the config identifier. The `board_id` and physical address (DIP switches) are defined separately in `control_mappings.json`.

### Board-level keys

| Property | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `name` | string | Yes | | Config identifier |
| `controls` | array | Yes | | List of channel configs |
| `comment` | string | No | | Free-form ignored by the parser |

## Control Properties

| Property | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `control_num` | int | Yes | | Hardware channel (1-8) on the MCP3008 |
| `name` | string | Yes | | Control identifier used in generated code |
| `desc` | string | No | `""` | Human-readable description |
| `sensor_min_v` | float | No | `0.0` | Sensor voltage at physical minimum (volts, 0.0-3.3) |
| `sensor_max_v` | float | No | `3.3` | Sensor voltage at physical maximum (volts, 0.0-3.3) |
| `deadband` | int | No | `2` | Minimum change in processed output to trigger a report |
| `gamma` | float | No | `1.0` | Response curve exponent (see below) |
| `invert` | bool | No | `false` | Flip output: `true` makes physical max -> logical 0 |
| `enabled` | bool | No | `true` | Whether this channel sends reports to the host |
| `min_value` | float | No | `0.0` | Host-side minimum float output |
| `max_value` | float | No | `1.0` | Host-side maximum float output |

## Sensor Voltage Range (`sensor_min_v` / `sensor_max_v`)

Physical sensors rarely use the full 0-3.3V range. Hall-effect sensors typically output 0.83-2.9V, and potentiometers may not reach their endpoints mechanically. Set `sensor_min_v` and `sensor_max_v` to the voltages your sensor produces at physical minimum and maximum travel.

The firmware remaps this range to the full 0-1023 output scale, giving full resolution regardless of the sensor's actual voltage range.

**To measure:** Use a multimeter at both physical extremes, or read `.raw` values in a test loop while moving the sensor. Values must be in the range 0.0-3.3, and `sensor_min_v` must be less than `sensor_max_v`.

The defaults (0.0 and 3.3) assume a rail-to-rail sensor, suitable for potentiometers.

### 5V Hall-effect sensors on the 3.3V rail

The AN08 supply and ADC reference are both 3.3V, but Hall-effect sensors nominally specified for 5V operation (e.g., Honeywell SS49E and equivalents) have worked reliably in testing when powered from the board's 3.3V rail. Output linearity and range are usable across the full magnet travel: no observed drop-out, saturation, or non-linearity from undervolting. The 0.83-2.9V range quoted above is the measured 3.3V-supplied output, not the datasheet 5V figure.

If a specific unit ever runs hot, loses linearity, or refuses to swing across its full range, that unit is out of spec for undervolt operation and probably won't function properly on this board. Do not attempt to feed it 5V from an external supply: the AN08's signal inputs are 3.3V-referenced and a 5V-swinging sensor output can damage the ADC. Substitute a 3.3V-compatible part. So far no such case has come up.

### Pull the range in slightly

Sensors return slightly different voltages depending on temperature, supply voltage, and unit-to-unit variation. A Hall-effect sensor that reads 0.85V at rest on a warm day may read 0.80V in a cold room. If `sensor_min_v` is set exactly to the warm-day reading, the game will never reach logical 0.0 in the cold.

Set your range values a little inside the measured extremes (20-50mV on each end is usually enough). This maps the sensor's reachable range to values just inside `[min_value, max_value]`, so the game always reaches both ends regardless of environmental conditions.

## Deadband

Analog sensors are noisy. A pot sitting perfectly still will still produce slightly different ADC readings from sample to sample, which without filtering would fire a continuous storm of change notifications even when nothing is moving. The `deadband` sets a minimum threshold: a `REPORTSTATE` is only sent when the processed output (post-pipeline, 0-1023) has moved by more than this many counts since the last report.

The comparison is: `|new_out - last_reported| > deadband`.

`last_reported` is updated even when `enabled = false`, preventing a burst of queued changes when the channel is re-enabled.

**Recommended values:**
- Potentiometers: `2` (default): typical ADC noise is +/-1 count
- Hall-effect sensors: `2-4`: slightly more electrical noise
- Noisy environments: `5-8`

**Unused channels:** a physically unused connector left floating picks up electrical noise. Declaring a channel with `enabled: false` silences it in firmware (no reports), but a connector you leave out of the config entirely is not automatically silenced, so jumper its center pin to a rail to hold it steady. See the [AN08 board README](../../../hardware/an08/README.md) for the physical dongle.

## Gamma

The `gamma` parameter applies a power-law curve to the normalized sensor output:

```
curved = norm ^ gamma
```

| gamma | Effect |
|-------|--------|
| `1.0` | Linear (default): output proportional to input |
| `< 1.0` | Logarithmic-like: more sensitive near the bottom of travel |
| `> 1.0` | Exponential-like: more sensitive near the top of travel |

**Common use cases:**
- Throttle controls: `gamma: 2.0` gives finer control at low throttle settings
- Brake axes: `gamma: 0.5` gives quicker initial response
- Linear position sensors where you want direct mapping: `gamma: 1.0`

**Linear vs audio-taper potentiometers:** A linear pot divides resistance
evenly across travel, so `gamma: 1.0` is correct. An audio-taper (log) pot
front-loads resistance (half travel is already ~10% of full output), so it
already applies its own curve in hardware. Use `gamma: 1.0` with an audio pot
too; fighting its taper with a software curve rarely produces a useful result.
Prefer linear pots for any analog input where you want predictable software
control over the response curve.

Gamma is stored in firmware NVS as an integer (`gamma x 1000`), so values like `1.5`, `2.0`, `0.5` are stored exactly. The technical range is 0.1-65.535 (the limit of a uint16 scaled by 1000), but anything above about `3.0` produces a curve so steep it is barely useful in practice. Typical values stay between `0.5` and `2.5`.

## Invert

When `invert: true`, the firmware flips the output: `out = 1023 - out`. Use this when your sensor reads high at the physical minimum position (e.g. a pull-up sensor, or a control mechanically installed in reverse).

## Output Value Range (`min_value` / `max_value`)

The library maps the firmware's 0-1023 output to a float in `[min_value, max_value]`:

```
value = min_value + (raw / 1023.0) * (max_value - min_value)
```

This mapping lives in the library and is not stored in firmware NVS.

**Examples:**
- Throttle (0-100%): `min_value: 0.0`, `max_value: 100.0`
- Heading offset (+/-30deg): `min_value: -30.0`, `max_value: 30.0`
- Rudder (-1 to +1): `min_value: -1.0`, `max_value: 1.0`

## Complete Examples

### Hall-Effect Throttle Axis

A hall-effect sensor with a restricted voltage range, gamma curve for low-throttle sensitivity, and full 0.0-1.0 output range:

```json
{
  "control_num": 1,
  "name": "Throttle",
  "desc": "Main engine throttle (hall effect)",
  "sensor_min_v": 0.83,
  "sensor_max_v": 2.8,
  "deadband": 3,
  "gamma": 2.0,
  "min_value": 0.0,
  "max_value": 100.0
}
```

### Rail-to-Rail Potentiometer

A pot that uses the full voltage range with no curve. `sensor_min_v` and `sensor_max_v` can be omitted entirely since 0.0/3.3 are the defaults:

```json
{
  "control_num": 2,
  "name": "BrakeAxis",
  "desc": "Manual braking input",
  "deadband": 2,
  "min_value": 0.0,
  "max_value": 1.0
}
```

### Rudder with Reverse Mounting

A pot installed mechanically inverted, with symmetrical output range centered on zero:

```json
{
  "control_num": 3,
  "name": "RudderAxis",
  "desc": "Lateral thrust (pot mounted in reverse)",
  "sensor_min_v": 0.1,
  "sensor_max_v": 3.2,
  "deadband": 2,
  "invert": true,
  "min_value": -1.0,
  "max_value": 1.0
}
```

## See Also

- [SW14_CONFIG.md](SW14_CONFIG.md): switch panel config reference
- [QD04_CONFIG.md](QD04_CONFIG.md): encoder board config reference
- [CONTROL_MAPPINGS.md](CONTROL_MAPPINGS.md): mapping physical boards to panel names
