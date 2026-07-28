<!-- SPDX-License-Identifier: MIT -->
# Device

Base class for simulation logic: the "business logic" behind a subsystem.
Subclass it, and instantiating the subclass auto-registers it so its `update()`
runs every tick. A Device reads from controls and other specs and writes to its
own spec; the manager then commits those spec values and publishes them to
displays. (Contrast with a [Panel](PANEL_CLASS.md) subclass, which manages the
state and appearance of a physical control panel rather than the logic behind
it.)

```python
from enigma.device import Device
from generated.devices import PortEngineSpec
from generated.controls import EngineControl

class EngineDevice(Device):
    def update(self):
        if EngineControl.Ignition == EngineControl.Ignition.Values.ON:
            PortEngineSpec.State = PortEngineSpec.State.Values.ONLINE
            PortEngineSpec.Thrust = EngineControl.Throttle * 8_000_000

# Just instantiate - it auto-registers with the manager.
EngineDevice()
```

Where it runs: `EnigmaManager.update()` calls every registered device's
`update()`, then commits pending spec values and publishes changes to displays.
So a value written in `update()` becomes visible to displays and audio on that
same tick, with no transport code on your part: declaring the config files is
what wires the publishing up.

---

## Instance methods

### `update()`

Called once per manager tick to advance simulation state. Override it to read
controls and other specs and write your own spec.

```python
def update(self) -> None
```

Not called from application code: the manager calls it automatically.

> [!NOTE]
> Spec vars are double-buffered: a value you write in `update()` is not readable
> back until the next tick (reads return the previous cycle's value). Do not rely
> on reading a spec you just set in the same `update()`.

---

### `on_reset()`

Called when the simulation resets (game restart). Override it to restore any
device-internal state that lives outside spec vars. Spec vars return to their
JSON defaults automatically; `on_reset()` is only for state the device tracks in
plain attributes (`self._prev_powered`, timers, and so on). See the
"Prefer specs over local variables" note in [DEVICE_SPECS.md](../DEVICE_SPECS.md).

```python
def on_reset(self) -> None
```

Not called from application code: the manager calls it automatically.

---

## Class methods

### `Device.all()`

Return a list of all registered device instances (the manager iterates this each
tick).

```python
@classmethod
def all(cls) -> list[Device]
```

### `Device.clear()`

Unregister every device instance. Intended for tests and teardown.

```python
@classmethod
def clear(cls) -> None
```

---

See [DEVICE_SPECS.md](../DEVICE_SPECS.md) for the spec definitions a device reads
and writes, and [PANEL_CLASS.md](PANEL_CLASS.md) for the panel-side counterpart.
