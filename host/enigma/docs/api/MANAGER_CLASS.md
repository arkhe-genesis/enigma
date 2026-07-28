<!-- SPDX-License-Identifier: MIT -->
# EnigmaManager

The top-level orchestrator. It owns the connected boards and the displays: it
enumerates hardware, applies configs, runs the per-tick cycle (device logic, spec
commit, display publish), and exposes console-wide operations. Most applications
construct one, `start()` it, call `update()` each tick, and `stop()` at exit.

```python
import enigma

mgr = enigma.EnigmaManager(enigma.ConfigManager("configs"))
mgr.start()
while running:
    mgr.update()      # tick devices, commit specs, publish displays
    time.sleep(0.05)
mgr.stop()
```

## ConfigManager

`ConfigManager(config_dir)` loads the JSON configs (specs, controls, displays,
audio) from `config_dir`. You construct it once, hand it to the manager, and
rarely touch it again.

## Getting the instance

The manager is a singleton. Anywhere below the top level, get it without
threading a reference through your call stack:

```python
from enigma.manager import get_manager
get_manager().set_brightness_all(180)
```

`get_manager()` returns the instance created by the `EnigmaManager(...)`
constructor.

---

## Lifecycle

### `start()`

Begin the background poll loop (hardware enumeration + reads) and bring up the
displays. Boards may be attached or removed afterward; the manager hot-plugs
them (see [HID_PROTOCOL.md](../HID_PROTOCOL.md)).

### `update()`

Run one cycle: drain queued input events, run every panel's `update()`, then
every device's `update()`, commit pending spec values, and publish changed specs
to displays. Call it once per application tick. See
[The Update Cycle](../DESIGN_GUIDE.md#the-update-cycle) for the full sequence and
the ordering rules.

### `stop()`

Shut down cleanly: stop the poll loop, close boards, and stop the displays.

---

## Devices

### `get_device(board_id)`

Return the device for a board id (e.g. `"SW14-03"`), or `None` if not connected.

### `get_all_devices()`

Return a `dict` of `board_id -> device` for everything currently connected.

---

## Console-wide control enable / disable

These act across **every** board, not one panel. (For a single panel, use the
panel-level methods in [CONTROL_CLASS.md](CONTROL_CLASS.md).)

### `disable_all_controls(pushState=False)`

Disable every control on every board. With `pushState=True`, each board saves its
current enable mask first, so `pop_all_enable_masks()` can restore it exactly.

### `enable_all_controls()`

Restore every board to its **config-default** enable mask. Controls declared
`"enabled": false` in their config stay disabled. This resets to defaults; it
does not pop a saved state.

### `pop_all_enable_masks()`

Restore the enable masks saved by the most recent `disable_all_controls(pushState=True)`
(or other pushed state): the exact prior state, not the config defaults.

### `clear_all_enable_stacks()`

Discard any saved enable-mask states on every board without changing the current
masks.

---

## Console-wide indicators

### `set_brightness_all(brightness)`

Set global LED brightness (`0`-`255`) on every board.

### `set_scheme_all(scheme_name)`

Activate an indicator scheme on every board that defines it; boards/controls
without that scheme are left unchanged.

### `set_blanking_all(mode, duration_tenths=0)`

Set blanking on every board. `mode`: `0`=off, `1`=on (all dark), `2`=disruption.
`duration_tenths` applies to disruption only (see `set_blanking` in
[CONTROL_CLASS.md](CONTROL_CLASS.md)).

### `pulse_all()`

Flash all indicators white briefly across every board.

---

## Reset

### `reset_all(timebase_ms=None)`

Reset every board's controls and indicators to their stored config, and sync the
animation timebase across boards. This is the board-level (hardware) reset. For
the whole-system picture (what a sim reset does to specs, devices, audio, and
physical controls) see the [Reset Behavior](../DESIGN_GUIDE.md#reset-behavior)
section of the design guide.

---

## Example: pause the console

The pattern behind a pause screen: kill the whole console except a few controls,
then restore it on resume:

```python
from enigma.manager import get_manager

def enter_pause():
    get_manager().disable_all_controls(pushState=True)   # save + disable everything
    # re-enable just the controls the operator still needs
    Meta.Brightness.Enabled = True
    Meta.MasterVolume.Enabled = True
    ConsoleSwitches.PauseRestart.Enabled = True

def exit_pause():
    get_manager().pop_all_enable_masks()   # restore the exact pre-pause state
```

> [!NOTE]
> `disable_all_controls(pushState=True)` pushes each board's enable mask onto a
> stack, so pair it with `pop_all_enable_masks()` on the way out: one push, one
> pop. Do **not** resume a pushed disable with `enable_all_controls()`: that
> restores config defaults but never pops, so the stack grows on every pause. Use
> `enable_all_controls()` only when you did not push (a hard reset to defaults).

---

See [CONTROL_CLASS.md](CONTROL_CLASS.md) for per-panel control operations,
[DEVICE_CLASS.md](DEVICE_CLASS.md) for the simulation devices the manager ticks,
and [the design guide](../DESIGN_GUIDE.md) for the overall architecture.
