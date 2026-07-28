# PanelManager

Base class for panel logic. Subclass it once per logical panel; instantiation
auto-registers with the manager and `update()` is called every tick.  The
difference between a Panel subclass and a Device subclass is that the Panel
is there to simply manage the state and appearance of a physical control
panel, while the Device code is what drives the "business logic" associated
with the interface.

```python
from enigma.panelmanager import PanelManager

class EnginePanel(PanelManager):
    def update(self):
        ...
```

---

## Instance methods

### `update()`

Called once per manager tick, after HID events have been processed and changed
flags cleared. Override this to read control states, update indicator schemes,
and enable/disable controls.

```python
def update(self) -> None
```

Not called from application code: the manager calls it automatically.

---

### `reset()`

Called when the sim resets. Override to restore any panel-internal state that
lives outside spec vars. Spec vars reset to their JSON defaults automatically;
`reset()` is only needed for state the panel tracks independently.

```python
def reset(self) -> None
```

Not called from application code: the manager calls it automatically.
