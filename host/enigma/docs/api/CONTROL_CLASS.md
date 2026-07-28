# Control Classes

The code generator produces one panel class per `name` group (e.g.
`EngineControl`) containing one control object per declared control (e.g.
`EngineControl.IgnitionEnable`). Two levels of API are available: panel-level
methods that operate across all boards in the group, and per-control properties
on each individual control.

---

## Panel-level methods

These are called on the panel class itself, not on a specific control.

> [!NOTE]
> **`pushState` is a save/restore stack, built for temporary overrides.** Any
> call that takes `pushState=True` first saves the current enable state (or, for
> `set_scheme`, the current schemes) before changing anything; a later
> `pop_enable()` / `pop_scheme()` restores exactly what was there.
>
> The classic use is **pausing a game**: on entering pause,
> `disable_all(pushState=True)` makes every control go dead; on exit, a single
> `pop_enable()` returns each control to whatever it was before the pause. The
> unpause code never has to track or reconstruct which controls were enabled;
> the stack remembers for it.

---

### `all_controls()`

Return a list of every control object in this panel, across all boards. A control
that spans multiple boards appears once. Useful for panel-wide operations that
aren't already covered by a dedicated method: for example, disabling everything
except a few controls:

```python
# Disable the whole panel except two controls (a pause-screen pattern).
keep = {ConsoleSwitches.PauseRestart, ConsoleSwitches.SilenceAlarms}
for ctrl in ConsoleSwitches.all_controls():
    ctrl.Enabled = ctrl in keep
```

To disable/enable *every* control across *all* panels at once (not just one
panel), use the manager-global helpers instead: see
[`disable_all_controls` / `enable_all_controls`](MANAGER_CLASS.md).

---

### `enable_all(pushState=False)`

Enable all controls on all boards in this panel.

```python
EngineControl.enable_all()
EngineControl.enable_all(pushState=True)  # save state for later restore
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `pushState` | `bool` | If `True`, saves the current enable state so it can be restored with `pop_enable()`. Default `False`. |

---

### `disable_all(pushState=False)`

Disable all controls on all boards in this panel. Disabled controls do not
report state changes.

```python
EngineControl.disable_all()
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `pushState` | `bool` | Save current enable state for restore. Default `False`. |

---

### `enable(*controls, pushState=False)`

Enable one or more specific controls. More efficient than enabling them
individually because it batches the HID commands.

```python
EngineControl.enable(EngineControl.IgnitionEnable, EngineControl.EngineMode)
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `*controls` | control objects | Controls to enable. |
| `pushState` | `bool` | Save current enable state for restore. Default `False`. |

---

### `disable(*controls, pushState=False)`

Disable one or more specific controls.

```python
EngineControl.disable(EngineControl.IgnitionEnable, EngineControl.EngineMode)
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `*controls` | control objects | Controls to disable. |
| `pushState` | `bool` | Save current enable state for restore. Default `False`. |

---

### `pop_enable()`

Restore the enable state saved by the most recent `pushState=True` call.

```python
EngineControl.pop_enable()
```

---

### `set_scheme(*controls, scheme, pushState=False)`

Set the indicator scheme on the specific controls you pass. This targets only
those controls; passing none is a no-op. To set a scheme on every control in the
panel at once, use the [`Scheme` property](#scheme-property-write-only) below.

```python
EngineControl.set_scheme(
    EngineControl.IgnitionEnable,
    EngineControl.EngineArm,
    scheme="warning"
)
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `*controls` | control objects | Controls to update. |
| `scheme` | `str` | Scheme name. Use the generated `Schemes` constant, not a string literal. |
| `pushState` | `bool` | Save current schemes for restore. Default `False`. |

---

### `pop_scheme()`

Restore the schemes saved by the most recent `set_scheme(pushState=True)` call.

```python
EngineControl.pop_scheme()
```

---

### `set_blanking(mode, duration_tenths=0)`

Set the blanking mode on all boards in this panel.

```python
from enigma.hid_protocol import BlankingMode
EngineControl.set_blanking(BlankingMode.ON)
EngineControl.set_blanking(BlankingMode.DISRUPTION, duration_tenths=30)
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `mode` | `BlankingMode` | `OFF`, `ON`, or `DISRUPTION`. |
| `duration_tenths` | `int` | For `DISRUPTION` only: wind-down duration in tenths of a second. |

DISRUPTION mode is an effect I use in Halcyon Dawn when a starship subsystem loses
power from the main reactor.  I send it a 100 (100 tenths of a second = 1000ms)
disruption blanking, and all the indicators on that panel spend 1000ms
flickering progressively toward fully extinguished.

[!NOTE] Blanking does not affect control enable/disable status; it's 
just a visual effect.

---

### `restore_enable_defaults()`

Reset all controls to the enabled/disabled state defined in their config JSON.

```python
EngineControl.restore_enable_defaults()
```

---

### `Scheme` (property, write-only)

Set the same scheme on all controls on all boards in this panel at once. Use
the generated `Schemes` class constant rather than a string.

```python
EngineControl.Scheme = EngineControl.Schemes.WARNING
```

Controls that do not define the named scheme are left unchanged: the assignment
is applied to every control that has that scheme and silently skips the rest. So
you can set a panel-wide scheme like `WARNING` even if only some controls define
it; the others keep their current appearance.

---

## Per-control properties and methods

These are called on an individual control object, e.g. `EngineControl.IgnitionEnable`.

---

### `value` (property)

Read or write the current value of the control. The type depends on the board:
SW14 controls return the configured `value` string for the current state; QD04
encoders return a float; AN08 channels return a float.

```python
# Read
mode = EngineControl.EngineMode.value          # str: "idle", "cruise", "boost"
power = EngineControl.PowerTarget.value        # float
throttle = EngineControl.Throttle.value        # float

# Write (programmatic set)
EngineControl.PowerTarget.value = 50.0
```

Controls support comparison and arithmetic operators directly, so you can
compare without reading `.value` explicitly:

```python
if EngineControl.EngineMode == EngineControl.EngineMode.Values.IDLE:
    ...
if EngineControl.PowerTarget > 80.0:
    ...
```

---

### `changed(hardware_only=False)`

Returns `True` if the control's value changed since the last tick. Call this
in `update()` to detect operator input.

```python
def changed(self, hardware_only: bool = False) -> bool
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `hardware_only` | `bool` | If `True`, only returns `True` for changes that originated from the physical hardware, not programmatic sets. Default `False`. |

```python
if EngineControl.IgnitionEnable.changed():
    ...

if EngineControl.PowerTarget.changed(hardware_only=True):
    # only fires when the operator physically moved the encoder
    ...
```

---

### `Scheme` (property, write-only)

Set the indicator scheme for this control. Use the generated `Schemes` constant.

```python
EngineControl.IgnitionEnable.Scheme = EngineControl.IgnitionEnable.Schemes.WARNING
```

---

### `Enabled` (property)

Read or set whether this control reports state changes. Disabled controls still
show their current indicator but do not fire `changed()`.

```python
# Read
if EngineControl.IgnitionEnable.Enabled:
    ...

# Write
EngineControl.IgnitionEnable.Enabled = False
```

---

## Generated constants

Each control has a `Values` class containing the string values declared in the
config JSON, and a `Schemes` class containing the scheme names.

```python
EngineControl.EngineMode.Values.IDLE    # "idle"
EngineControl.EngineMode.Values.CRUISE  # "cruise"

EngineControl.IgnitionEnable.Schemes.WARNING   # "warning"
EngineControl.IgnitionEnable.Schemes.DEFAULT   # "default"
```

Always use these constants rather than string literals. A typo in a constant
crashes at startup; a typo in a string silently matches nothing.
