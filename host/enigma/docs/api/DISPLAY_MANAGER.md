<!-- SPDX-License-Identifier: MIT -->
# DisplayManager

Publishes spec values to displays over WebSocket and delivers events sent back
from them. It is owned and driven by [EnigmaManager](MANAGER_CLASS.md): built
from the config files and ticked every frame, so an application rarely
constructs or updates it directly. Publishing is automatic: declaring
`display_mappings.json` plus a display config turns it on (see
[DISPLAY_CONFIG.md](../DISPLAY_CONFIG.md)). The wire format is in
[DISPLAY_WEBSOCKET_PROTOCOL.md](../DISPLAY_WEBSOCKET_PROTOCOL.md); this page is
the Python interface.

## Access

### `DisplayManager.get_instance()`  *(classmethod)*

Return the singleton, or `None` if `EnigmaManager` has not created it yet. Guard
for `None` (or register lazily on first need).

```python
from enigma.displaymanager import DisplayManager
dm = DisplayManager.get_instance()
```

---

## Application methods

### `register_handler(display_name, event_name, callback)`

Register a callback for an inbound event emitted by a named display
(display -> host). This is the receiving half of the same socket that carries
spec updates outbound.

```python
dm.register_handler("MainDisplay", "boarding_config", on_boarding_config)
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `display_name` | `str` | The display's key from `display_mappings.json`. |
| `event_name` | `str` | The event the display emits (a custom event; see the protocol doc). |
| `callback` | `callable` | Invoked as `callback(payload)` when the event arrives. |

The callback runs on the DisplayManager **background thread**: keep it
thread-safe; hand off to your main loop if it touches live game state. On
(re)connect the display replays its cached state, so late registration still
catches up.

### `reload_clients()`

Tell every connected display client (browser, Unity, etc.) to reload its page.
Use it after changing something the declarative side of the page depends on
(config-driven layout, image paths) that spec-value deltas alone won't reflect.

---

## Manager-driven methods

These are called for you by `EnigmaManager`; applications do not normally invoke
them.

| Method | Purpose | Called by |
|--------|---------|-----------|
| `update()` | Flush changed spec values to all displays. | `EnigmaManager.update()`, each tick |
| `reset()` | Resync (full snapshot on the next publish). | sim reset |
| `stop()` | Stop the background connection thread. | `EnigmaManager.stop()` |
| `__init__(config_dir)` | Build publishers from `display_mappings.json`. | `EnigmaManager` |

---

See [DISPLAY_CONFIG.md](../DISPLAY_CONFIG.md) for declaring displays,
[DISPLAY_WEBSOCKET_PROTOCOL.md](../DISPLAY_WEBSOCKET_PROTOCOL.md) for the wire
format, and [MANAGER_CLASS.md](MANAGER_CLASS.md) for the manager that drives it.
