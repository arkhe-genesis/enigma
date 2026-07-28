# Device Specs

Device specs define the shared state for game subsystems. They're the central source of truth that controls, displays, audio, and simulation devices all interact with.

## Overview

The Enigma system separates concerns:
- **Spec files** (JSON) declare what variables exist and their types
- **Generated code** (`generated/devices.py`) provides a type-safe Python API
- **Device classes** (your code) implement simulation logic using specs

```
Spec JSON -> generate_devices.py -> generated/devices.py -> Your Device classes
```

## Spec File Format

Spec files are JSON objects where each key is a variable name:

```json
{
  "VariableName": {
    "type": "number",
    "desc": "Description of this variable",
    "default": 0.0,
    "constants": { ... }
  }
}
```

### Variable Properties

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `type` | string | Yes | `"number"`, `"bool"`, `"enum"`, or `"string"` |
| `desc` | string | No | Documentation |
| `default` | varies | Yes | Initial value (type must match) |
| `constants` | object | No | Named threshold values (for number type) |
| `values` | array | Yes* | Enum values (*required for enum type only) |

## Variable Types

### Number

Floating-point numeric values, optionally with named threshold constants.

```json
"Temperature": {
  "type": "number",
  "desc": "Reactor temperature in million-kelvins",
  "default": 100.0,
  "constants": {
    "LOW": 75.0,
    "NOMINAL": 100.0,
    "MAX": 150.0,
    "CRITICAL": 175.0
  }
}
```

Generated code allows direct comparison with constants:

```python
from generated.devices import PowerCoreSpec

if PowerCoreSpec.Temperature > PowerCoreSpec.Thresholds.Temperature.CRITICAL:
    trigger_emergency()

# Arithmetic works naturally
delta = PowerCoreSpec.Temperature - PowerCoreSpec.Thresholds.Temperature.NOMINAL
```

### Bool

Boolean true/false values.

```json
"PurgeActive": {
  "type": "bool",
  "desc": "True if antimatter purge is in progress",
  "default": false
}
```

Usage:

```python
if PowerCoreSpec.PurgeActive:
    disable_antimatter_feed()

PowerCoreSpec.PurgeActive = True
```

### Enum

One of a fixed set of string values.

```json
"ReactorState": {
  "type": "enum",
  "values": ["OFFLINE", "STARTING", "RUNNING", "SCRAMMED"],
  "default": "OFFLINE"
}
```

Usage:

```python
# Compare with enum values
if PowerCoreSpec.ReactorState == PowerCoreSpec.ReactorState.RUNNING:
    ...

# Set to enum value
PowerCoreSpec.ReactorState = PowerCoreSpec.ReactorState.Values.SCRAMMED
```

### String

Free-form text for messages, status, or serialized data.

```json
"StatusMessage": {
  "type": "string",
  "desc": "Current status message for display",
  "default": ""
}
```

Usage:

```python
PowerCoreSpec.StatusMessage = "Rerouting power to shields"

# Can also store JSON for complex data
import json
PowerCoreSpec.NodeStatus = json.dumps({"node1": "active", "node2": "failed"})
```

## Device Mappings

Spec files are registered in `device_mappings.json`:

```json
{
  "PowerCoreSpec": "PowerCoreSpec.json",
  "PortEngineSpec": "EngineSpec.json",
  "StarboardEngineSpec": "EngineSpec.json",
  "ShipSpec": "ShipSpec.json"
}
```

Multiple logical specs can share the same definition file while maintaining separate runtime state. Here, both engine specs use `EngineSpec.json`, but `PortEngineSpec.Temperature` and `StarboardEngineSpec.Temperature` are independent values.

## Code Generation

Run the generator to create the Python API:

```bash
python3 -m enigma.tools.generate_devices \
  --config-dir configs/ \
  --output generated/devices.py \
  --docs docs/devices.txt
```

`--config-dir`: directory containing the spec JSON files.

`--output`: destination for the generated Python module.

`--docs`: optional plain-text summary of all generated specs (useful for debugging).

This creates `generated/devices.py` with classes like:

> **Important:** Always use the generated identifiers (e.g., `PowerCoreSpec.ReactorState.RUNNING`) instead of hardcoded strings (e.g., `"RUNNING"`). The generated code declares all enum values, constants, and thresholds as actual Python identifiers. A typo in an identifier causes an immediate crash on execution, while a typo in a string like `"RUNING"` silently fails to match anything: a stealth bug that's very hard to find.

```python
class _PowerCoreSpec(DeviceSpec):
    NAME = "PowerCoreSpec"

    class _Temperature:
        LOW = 75.0
        NOMINAL = 100.0
        MAX = 150.0
        CRITICAL = 175.0

    Temperature = PublishedNumber(default=100.0, thresholds=_Temperature)
    ReactorState = PublishedEnum(_ReactorState, default=_ReactorState.OFFLINE)
    PurgeActive = PublishedBool(default=False)

PowerCoreSpec = _PowerCoreSpec()  # Singleton instance
```

## Double-Buffering

Spec variables are double-buffered for consistency. During an update cycle:

1. **Reads** return the value from the start of the cycle (current buffer)
2. **Writes** go to a pending buffer
3. After all device updates complete, pending values are promoted to current for the next iteration

Every Device, display, and audio watcher sees the same value for a given variable during a single cycle, even if another Device modifies it mid-cycle.

## Device Classes

Device classes implement simulation logic. They read from controls and other specs, and write to their own spec.

```python
from enigma.device import Device
from generated.devices import PowerCoreSpec, ShipSpec
from generated.controls import PowerPanel

class PowerCoreDevice(Device):
    def update(self):
        # React to control inputs
        if PowerPanel.MasterEnable == PowerPanel.MasterEnable.Values.ON:
            # Simulate temperature based on other state
            load = ShipSpec.PowerDemand / 1000.0
            PowerCoreSpec.Temperature = 100.0 + (load * 50.0)

            # Check thresholds
            if PowerCoreSpec.Temperature > PowerCoreSpec.Thresholds.Temperature.CRITICAL:
                PowerCoreSpec.ReactorState = PowerCoreSpec.ReactorState.Values.SCRAMMED

    def on_reset(self):
        # Called when the sim resets between games.
        # Spec vars are reset to their JSON defaults automatically;
        # use this for any device-internal state that lives outside specs.
        pass
```

> [!NOTE]
> **Prefer specs over local variables for state.** Every spec var returns to its
> JSON default automatically on reset, so state you keep in specs is clean on the
> next game with no work from you. State you keep in a plain Python attribute
> (`self._prev_powered`, `self._last_temp`, and so on) is not touched by the
> reset and carries its stale value into the new game. That is the usual cause of
> a spurious callout or a wrong transition on startup: a "was previously X" flag
> left `True` from the last session.
>
> Local variables are still fine when the double-buffering of specs gets in your
> way (see Double-Buffering above) or when there is genuinely no matching spec, for example a
> button-press timestamp. The rule when you do that: reset every one of them in
> the device's `on_reset()` method. Audit any `_prev_*`, `_was_*`, or `_last_*`
> field you add and make sure `on_reset()` clears it.

### Update Cycle

Each `EnigmaManager.update()` tick, in order:
1. Queued input events are drained.
2. Every panel's `update()` runs (`PanelManager.update_all()`).
3. Every device's `update()` runs (`Device.all()`).
4. Pending spec values are promoted to current in one sweep.
5. Changed spec values are published to displays.

Hardware reports are read on a separate background poll loop, not in this tick;
audio watchers react to the committed spec values on the audio side. See
[The Update Cycle](DESIGN_GUIDE.md#the-update-cycle) for the full picture,
including why the order among panels and among devices is not guaranteed.

## Resetting State

```python
from enigma.device import PublishedValue

# Reset all specs to their default values
PublishedValue.reset_all()
```

## Complete Example

### EngineSpec.json

```json
{
  "State": {
    "type": "enum",
    "values": ["ONLINE", "OFFLINE", "SCRAMMED"],
    "default": "ONLINE"
  },
  "Temperature": {
    "type": "number",
    "desc": "Reactor temperature in million-kelvins",
    "default": 100.0,
    "constants": {
      "LOW": 75.0,
      "NOMINAL": 100.0,
      "MAX": 150.0,
      "CRITICAL": 175.0
    }
  },
  "Pressure": {
    "type": "number",
    "desc": "Antimatter chamber pressure in torr x10^-5",
    "default": 0.0,
    "constants": {
      "LOW": 1.0,
      "NOMINAL": 2.0,
      "MAX": 3.0,
      "CRITICAL": 5.0
    }
  },
  "Thrust": {
    "type": "number",
    "desc": "Current output thrust in kN",
    "default": 0.0
  },
  "PurgeActive": {
    "type": "bool",
    "desc": "True if antimatter purge is in progress",
    "default": false
  }
}
```

### Using the Generated Spec

```python
from generated.devices import PortEngineSpec

# Read values
print(f"Temperature: {PortEngineSpec.Temperature}")
print(f"State: {PortEngineSpec.State}")

# Compare with thresholds
if PortEngineSpec.Temperature > PortEngineSpec.Thresholds.Temperature.MAX:
    print("WARNING: Temperature exceeds maximum!")

if PortEngineSpec.Pressure < PortEngineSpec.Pressure.LOW:
    print("WARNING: Pressure below minimum!")

# Write values
PortEngineSpec.Thrust = 5000.0
PortEngineSpec.State = PortEngineSpec.State.Values.SCRAMMED

# Check enum state
if PortEngineSpec.State == PortEngineSpec.State.Values.OFFLINE:
    print("Engine is offline")
```

## See Also

- [CONTROL_MAPPINGS.md](CONTROL_MAPPINGS.md): Device mappings and generated code usage
- [DISPLAY_CONFIG.md](DISPLAY_CONFIG.md): Publishing specs to displays
- [AUDIO_CONFIG.md](AUDIO_CONFIG.md): Audio events that watch spec values
- `enigma/device.py`: Runtime implementation
