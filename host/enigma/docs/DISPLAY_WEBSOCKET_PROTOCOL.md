# Display WebSocket Protocol

Wire-level reference for the WebSocket messages exchanged between an
enigma application and a display server. Read this if you're writing
your own display client (in Rust, Godot, embedded C, whatever) instead
of using the JavaScript or C# libraries shipped with enigma.

The [`DISPLAY_CONFIG.md`](DISPLAY_CONFIG.md) tutorial is the friendlier
introduction if you're using the reference libraries; this document
assumes you already know what a display is and are down at the socket
level.

---

## 1. Transport

The protocol is **Socket.IO on top of Engine.IO on top of WebSocket**.
(Socket.IO and Engine.IO are the standard third-party networking libraries;
Engine.IO is the transport layer Socket.IO is built on. Neither has any relation
to the Enigma library or its "engine": the name overlap is coincidental.)
Enigma applications connect as **Socket.IO clients** to a display's
Socket.IO **server**. Both directions of the connection carry JSON.

The reference Python display server (`server.py`) uses `python-socketio`
+ Flask-SocketIO on the server side. The reference JavaScript client
(`enigma.js`) uses the vendored `socket.io.min.js`. Enigma applications
use `python-socketio.AsyncClient`. The Unity `Enigma.cs` MonoBehaviour
implements the server side by hand in ~600 lines of C#, no external
dependencies.

**Direction of the connection.** Displays are servers; enigma
applications are clients. Browsers (also clients) connect to the *same*
display server the application connects to. State pushed by the
application is re-broadcast by the server to every browser client.

If you're implementing a display in a language without a Socket.IO
library, note that Socket.IO's framing is documented at
https://socket.io/docs/v4/socket-io-protocol/. You need Socket.IO v4
compatibility.

---

## 2. Envelope format

All messages are Socket.IO **events**. Each event is a JSON array
containing the event name followed by its arguments:

```
["event_name", { ...payload object... }]
```

The Engine.IO frame prefix (`42` for a Socket.IO EVENT packet) is added
by whichever library you're using; it's not part of the payload.

Payload objects are flat JSON dictionaries where keys are strings and
values are JSON-native scalars: number, boolean, string, or null.
Nested objects and arrays are permitted for custom events but are not
used by the built-in `host_update` / `update` traffic.

---

## 3. Application -> Display server

### `host_update`

The workhorse. Sent by the enigma application whenever any spec value
in the display's `Publish` list has changed since the last emit.

```
["host_update", {
  "PortEngineSpec.Thrust": 4200000.0,
  "PortEngineSpec.State":  "ONLINE"
}]
```

Payload is a flat dict of **spec paths** (dotted, `<SpecName>.<Field>`)
mapping to their **current values**. Only paths whose values changed
this tick are present.

**Cadence.** The application's publish loop runs at 20 Hz. If no
published spec value changed since the last tick, no `host_update` is
emitted at all: do not expect a heartbeat. Consumers should use the
Socket.IO / Engine.IO ping-pong (25 s interval) to detect a dead
connection, not silence on `host_update`.

**Full snapshot on (re)connect.** On the first `host_update` after the
Socket.IO `connect` event fires (whether it's the initial connect or a
reconnect after a network blip), the payload contains **every** value
in the Publish list, not just deltas. This guarantees the server-side
cache is complete after any reconnect. Ordinary delta behavior resumes
from the second `host_update` onward.

Concretely: deltas after the first update, full snapshot on every
connect.

### Custom events

Applications may emit any additional event names for out-of-band
messages. The display server can dispatch these to browsers as-is by
subscribing to `sio.on('<event_name>')` and re-emitting. Not used by
the built-in Publish machinery; useful for one-shot notifications
(e.g., `end_of_game` or `player_died`) that don't map naturally to
spec-value deltas.

### `reload`

Sent to force every connected browser client to reload its page.

```
["reload"]
```

No payload. Used when the application has changed something the
declarative side of the page depends on (config-driven layout, image
paths) and pushing spec-value deltas alone won't reflect it. Called
via `DisplayManager.reload_clients()` on the application side.

### Receiving events from a display (host side)

Custom events also flow the other way: a display (or the browser / Unity behind
it) can emit to the host over the same socket. The application receives them by
registering a callback with the DisplayManager; the Python interface
(`get_instance()`, `register_handler(...)`) is documented in the
[DisplayManager reference](api/DISPLAY_MANAGER.md). This is how, for example,
Unity sends boarding config, impact reports, and targeting back to the app.

---

## 4. Display server -> Client (browser / Unity / etc.)

### `update`

Sent to every connected client whenever the server receives a
`host_update` from the application. The server re-emits the same
payload verbatim, so the client sees the same `{spec_path: value}` dict
the application sent.

```
["update", {
  "PortEngineSpec.Thrust": 4200000.0
}]
```

On a **new client connection**, immediately after the Socket.IO
handshake completes, the server also emits one `update` containing
its entire cached state so the newly-arrived client sees everything
at once. This makes browser refresh mid-session cheap: no waiting for
the next application-side change.

### `reload`

Forwarded verbatim from the application. Clients that receive it
should reload their current page (browsers: `window.location.reload()`;
other stacks: whatever equivalent applies).

```
["reload"]
```

---

## 5. Client -> Display server

### `get_data`

Sent by the client on connect to explicitly request the current cached
state.

```
["get_data"]
```

No payload. The server responds by emitting one `update` with the full
cache. The reference `server.py` also does this automatically on
connect, so `get_data` is technically redundant on those servers, but
sending it makes the client behavior reliable across server
implementations that may not push the initial state proactively.

### Custom events

Clients may emit any additional event names to send messages *back* to
the display server, which can either handle them locally or forward
them to the application. This is the bidirectional path; see
[Section 6](#6-bidirectional-writes-display--application).

---

## 6. Bidirectional writes (display -> application)

Neither the reference `enigma.js` nor `Enigma.cs` ship with a helper
for writing back to a spec value. When a display page needs to send a
command to the application (a button click that toggles a control, a
canvas-drag that adjusts a knob), the client emits a custom event and
the application-side handler catches it via `DisplayManager.register_handler()`.

This path is used sparingly in practice. In Halcyon Dawn almost all input comes
from physical panels; the main exception is Unity reporting results it is better
placed to compute, such as NPC and geometry collisions worked out in-scene (a
boarder impact, for example). A touch screen with interactive buttons is another
candidate, though a cleaner one would be a dedicated input "board" type wrapping
the touchscreen so its presses flow through the normal control-to-spec pipeline
(see [NEW_BOARD_HANDLER.md](NEW_BOARD_HANDLER.md)) rather than this event channel.

**Client side** (browser, using the raw `_socket` inside the reference
library):

```js
Enigma._socket.emit('user_action', {
  action: 'toggle_purge',
  value:  true
});
```

**Application side**:

```python
def on_user_action(data):
    action = data.get('action')
    value  = data.get('value')
    if action == 'toggle_purge':
        PortEngineSpec.PurgeActive = value

display_manager.register_handler('PortEngineDisplay', 'user_action', on_user_action)
```

The handler runs on the application's event loop, not on the display
server. Any exception thrown gets logged; the emit is fire-and-forget
from the client's perspective.

**Unity `Enigma.cs` server side**, sending an event to all connected
clients (application-side included):

```csharp
_enigma.EmitToAll("game_state_change", new Dictionary<string, object> {
  { "phase", "combat" },
  { "opponent_count", 3 }
});
```

The application, connected as a Socket.IO client, receives this via
the same `add_handler` machinery.

---

## 7. Value types on the wire

| Spec type | JSON encoding | Notes |
|-----------|---------------|-------|
| `number` | `4200000.0` | Always `double` on the wire. Integer specs come back as floats; use your language's int conversion. |
| `bool`   | `true` / `false` | |
| `enum`   | `"ONLINE"` | Emitted as the string value name, not the ordinal. |
| `string` | `"whatever"` | UTF-8. |
| `null`   | `null` | Used when a spec value has never been assigned. |

Nested objects and arrays are not used for `host_update` traffic.
Custom events are free to use them; the reference JS library uses
`MiniJSON`-equivalent parsing on the C# side, standard `JSON.parse` on
the JS side.

---

## 8. Connection lifecycle

Standard Socket.IO v4 semantics, with one deliberate exception: the application
drives its own connection retry rather than using the library's built-in
reconnection (see step 6).

1. **Client connects**: TCP + Engine.IO handshake + Socket.IO CONNECT
   packet. Server assigns a session id (`sid`).
2. **Server sends `update`** (from cache) so the client sees the current
   state immediately.
3. **Application sends `host_update`** (full snapshot, because
   `_first_publish` is true on connect). Server merges into cache and
   re-emits `update` to all clients including the newly-arrived one.
4. **Steady state**: at 20 Hz the application checks its spec values;
   whenever any published value changes it emits a delta `host_update`;
   server forwards to all clients as `update`.
5. **Ping/pong**: Engine.IO pings every 25 s, 20 s timeout, so a dead
   connection is detected even during `host_update` silence.
6. **Reconnect**: Socket.IO's built-in reconnection is disabled
   (`reconnection=False`). Instead `DisplayManager` retries the connection
   itself, about every 2 s, whenever it finds a display not connected. This
   covers a display that has not come up yet as well as one that dropped: the
   host keeps trying until the display is reachable. On the (re)connect, the
   next `host_update` emits a full snapshot again.
7. **Explicit disconnect**: either side may close. No graceful shutdown
   payload is required.

---

## 9. Debugging on the wire

The reference `server.py` exposes an HTTP `/heartbeat` endpoint that
returns every spec key currently in the server's cache:

```
$ curl -s http://localhost:8080/heartbeat | python3 -m json.tool
{
  "status": "alive",
  "data_keys": [
    "PortEngineSpec.Thrust",
    "PortEngineSpec.Temperature"
  ]
}
```

If a key you expect is missing, either the application isn't
publishing it (check the display's `Publish` list) or the connection
isn't established (check the application logs for `Emit failed`
messages).

For a live wire-level view, run `wscat` against the server (assumes
socket.io-client available):

```
npx wscat -c ws://localhost:8080/socket.io/?EIO=4^&transport=websocket
```

Every `host_update` and `update` frame is visible. Payload deltas
should be tight; the initial connect frame will be much larger because
it carries the full snapshot.

---

## 10. Annotated transcript

Full session from initial connect through a spec update. Comments
prefixed with `#` are not on the wire.

```
# Client connects, Engine.IO OPEN packet from server
S->C  0{"sid":"abc123","upgrades":[],"pingInterval":25000,"pingTimeout":20000}

# Client sends Socket.IO CONNECT
C->S  40

# Server acknowledges CONNECT
S->C  40{"sid":"abc123"}

# Server sends full cache as first update (empty if nothing cached yet)
S->C  42["update",{"PortEngineSpec.Thrust":0.0,"PortEngineSpec.State":"ONLINE"}]

# Application connects to the same server, immediately sends full snapshot
# (relayed to all clients as an update)
S->C  42["update",{"PortEngineSpec.Thrust":0.0,"PortEngineSpec.Temperature":100.0,"PortEngineSpec.State":"ONLINE"}]

# Application ticks: thrust changed. Delta on the wire.
S->C  42["update",{"PortEngineSpec.Thrust":420000.0}]

# ... 20 Hz stream of small deltas ...
S->C  42["update",{"PortEngineSpec.Thrust":840000.0}]
S->C  42["update",{"PortEngineSpec.Thrust":1260000.0}]

# Engine.IO ping/pong keeps the connection alive during silence
S->C  2
C->S  3

# Client emits a custom event back to the application
C->S  42["user_action",{"action":"toggle_purge","value":true}]

# Application-side handler processes it; next tick, PurgeActive is now true
# and gets pushed out as a delta
S->C  42["update",{"PortEngineSpec.PurgeActive":true}]
```

---

## 11. Compatibility

- **Socket.IO version**: v4 (July 2021 onward). v3 is not supported by
  the reference server.
- **Engine.IO version**: v4 (`EIO=4` query parameter).
- **Transport**: WebSocket only. Polling fallback works for the
  Engine.IO handshake but is not exercised in production; if your
  browser is stuck on polling for some reason, `host_update` throughput
  degrades gracefully but latency will suffer.

---

## 12. Reference implementations

- **Application side**: `enigma/displaymanager.py` (`DisplayManager` and
  `DisplayPublisher` classes)
- **Display server (Python)**: [`host/examples/engine-sw/display/server.py`](../../examples/engine-sw/display/server.py)
- **JavaScript client**: [`host/examples/engine-sw/display/content/lib/enigma.js`](../../examples/engine-sw/display/content/lib/enigma.js)
- **Unity server (C#)**: [`host/examples/engine-sw/unity/Enigma.cs`](../../examples/engine-sw/unity/Enigma.cs)
