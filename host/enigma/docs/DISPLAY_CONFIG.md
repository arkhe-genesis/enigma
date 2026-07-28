# Display Development

Enigma applications publish device-spec values to zero or more *displays*
(displays are optional: an application can run with none). A display is a
self-contained screen that receives spec updates over a WebSocket connection and
renders them however it likes: a browser page, a local game-engine screen (Unity,
Unreal, Godot), an LED matrix panel, or a small networked screen on a Raspberry
Pi across the room. Anything that can hold a socket open works, on the same
machine as the application or anywhere it can reach over the network. This
document walks through building a web-based display end to end, gives the
equivalent notes for other stacks, and covers the reverse path: a display sending
input back to the application.

The runnable engine example under [`host/examples/engine-sw/`](../../examples/engine-sw/)
is the reference implementation; every code snippet below is a subset of that
example.

---

## 1. What a display actually is

A display is three things at once:

- **A configuration file**: one JSON file that names the display, lists
  which spec paths it wants to receive, and points at the URL to publish to.
- **A server**: a small program that accepts incoming spec updates and
  serves the rendered UI. For web displays this is `server.py` (a tiny
  Flask + Socket.IO server); for Unity displays it's a `MonoBehaviour`
  running a Socket.IO server inside the game process.
- **A client renderer**: the code that actually paints values on screen.
  For web it's a browser page loading `enigma.js`; for Unity it's C#
  scripts subscribed to a callback.

The enigma application uses `DisplayManager` internally to open a
persistent Socket.IO client connection to each display's server and push
`host_update` events at 20 Hz whenever any published spec value changes.

> **Note: direction of the connection.** In every reference
> implementation shipped with enigma, the *display* is the server and the
> *application* is the client. A web display's `server.py` listens on a
> TCP port and accepts inbound state pushes; the enigma application
> connects out to it. A Unity display's `WebSocketServer.cs`
> `MonoBehaviour` does the same, listening inside the game process.
>
> This is opposite from what you might expect (state usually flows *from*
> servers *to* clients). It's set up this way so displays can come and go
> (a browser page reload, a Unity restart, a Pi power-cycle) without the
> application needing to know or care. Each display re-establishes its
> subscription on boot; the application's publish loop is oblivious.

---

## 2. The wiring, top to bottom

Given an application that owns a `PortEngineSpec` device with a `Thrust`
field, here's how a value change on the application side lands on a
browser screen:

1. Application code updates the spec: `PortEngineSpec.Thrust = 4_200_000`.
2. Enigma's `DisplayManager` runs a publish loop at 20 Hz. On the next
   tick it notices the value differs from what was last emitted and
   queues an entry for the corresponding `host_update` envelope.
3. The envelope is emitted over the persistent Socket.IO connection to
   the display server as a Socket.IO event named `host_update` with a
   flat payload dict: `{"PortEngineSpec.Thrust": 4200000.0}`.
4. The display server receives it, merges into its cached snapshot, and
   re-broadcasts as an `update` event to every connected browser client.
5. Each browser's `enigma.js` receives the `update` event, merges into
   its own local cache, and fires any registered watchers plus refreshes
   any declaratively-bound DOM elements.

Steps 4 and 5 are decoupled: the server-side cache is what any newly
connected browser gets on first load, so a browser refreshed
mid-session immediately sees the current state without waiting for
the next spec change.

Deltas ordinarily flow: only spec values that changed since the last update are
on the wire. The exceptions are connection edges. The application holds a
persistent client connection to each display and keeps retrying it (about every
two seconds) whenever it is not connected, so a display can boot late,
power-cycle, or drop off the network and the host connects to it whenever it
becomes reachable, with no attention from your code. On every connect or
reconnect, the first publish sends the **full** current snapshot of that
display's subscribed vars, so the display is fully synced before delta traffic
resumes. See [the protocol
reference](DISPLAY_WEBSOCKET_PROTOCOL.md#8-connection-lifecycle) for the wire
detail.

> **Note: scale.** A spec value is not limited to a small scalar; it can be a
> large serialized-JSON string, and the delta model means it is only sent when it
> changes. Even a big value that changes every tick is handled comfortably:
> Halcyon Dawn packs hundreds of combat objects into a single such value and
> republishes it every frame without trouble.

---

## 3. The config files

### `configs/<DisplayName>Display.json`

One file per display. Names the target URL and the exact list of spec
paths this display wants to receive.

```json
{
  "URL": "http://display-host:8080/update",
  "Publish": [
    "PortEngineSpec.Thrust",
    "PortEngineSpec.Temperature",
    "PortEngineSpec.State"
  ]
}
```

- **`URL`**: HTTP endpoint on the display server. Enigma's
  `DisplayManager` opens a Socket.IO connection to this host and port;
  the `/update` path is a legacy HTTP fallback the server also accepts,
  but the persistent WebSocket is used in practice.
- **`Publish`**: every spec path this display should receive. Not on
  this list = not on the wire. The server won't push it and the client
  can't read it.

Publish lists are scoped per display so a small kiosk screen doesn't
receive megabytes of specs it doesn't render. Keep them tight.

### `configs/display_mappings.json`

Registers each display's config file with the manager.

```json
{
  "PortEngineDisplay": "PortEngineDisplay.json",
  "PowerCoreDisplay":  "PowerCoreDisplay.json"
}
```

Keys are the display names your application code refers to; values are
paths relative to `configs/`.

### Device spec + control configs

The spec being published is defined by the same JSON files the rest of
enigma uses (see [DEVICE_SPECS.md](DEVICE_SPECS.md)). No display-specific extension is
needed on the spec side: every spec field is publishable by default;
whether it actually goes out is gated by the display's Publish list.

---

## 4. First working page

Below is a minimal web display for a single spec value. The runnable
version lives at [`host/examples/engine-sw/display/`](../../examples/engine-sw/display/).

### `content/index.html`

```html
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>Port Engine</title>
  <link rel="stylesheet" href="/style.css">
</head>
<body>
  <h1>PORT ENGINE</h1>

  <!-- Declarative: bind textContent to the spec value, SI-format as kN. -->
  <div class="label">Thrust</div>
  <div class="readout" data-bind="PortEngineSpec.Thrust" data-unit="N"></div>

  <!-- Programmatic: JS-derived label combining two spec values (see main.js). -->
  <div class="label">Operational mode</div>
  <div id="operational-mode" class="readout">--</div>

  <!-- Connection dot in a corner. -->
  <div id="conn-dot"></div>

  <script src="/lib/socket.io.min.js"></script>
  <script src="/lib/enigma.js"></script>
  <script src="/main.js"></script>
</body>
</html>
```

### `content/main.js`

```js
// Programmatic watch - derive an operational-mode string from two
// spec values. The declarative bindings can only read one key at a
// time, so any cross-dependency logic belongs here.
function refreshMode() {
  const state = Enigma.get('PortEngineSpec.State');
  const purge = Enigma.get('PortEngineSpec.PurgeActive');
  const el = document.getElementById('operational-mode');
  if      (state === 'SCRAMMED')  el.textContent = 'SHUTDOWN';
  else if (state === 'OFFLINE')   el.textContent = 'STANDBY';
  else if (purge === true)        el.textContent = 'PURGING';
  else if (state === 'ONLINE')    el.textContent = 'NOMINAL';
  else                            el.textContent = '--';
}
Enigma.watch(['PortEngineSpec.State', 'PortEngineSpec.PurgeActive'], refreshMode);

// Connection status - flip a CSS class on the corner dot.
Enigma.onStatus((connected) => {
  document.getElementById('conn-dot').className = connected ? 'ok' : 'lost';
});
```

That's a complete display. `data-bind` handles the raw thrust readout with
unit formatting for free; the programmatic watcher demonstrates the
"not just cloning" case: a derived label that depends on more than
one spec value.

> **On magic numbers.** The example deliberately avoids deriving state
> from magnitude thresholds like `thrust > 5_600_000`. Any threshold a
> display hard-codes has to be kept in sync by hand with values defined
> in the spec config; there is no runtime channel that publishes spec
> constants to displays. Where the derivation needs a threshold that's
> semantically owned by the application, publish the derived state
> from the application side (as an enum spec) and consume the enum
> string. Multi-value logic, temporal derivations (trend arrows,
> rolling averages), and presentation state (blink on rapid change) are
> good fits for the programmatic API precisely because they don't
> depend on config-defined magnitudes.

### `configs/PortEngineDisplay.json`

```json
{
  "URL": "http://localhost:8080/update",
  "Publish": [
    "PortEngineSpec.Thrust"
  ]
}
```

### Server (`display/server.py`)

The reference `server.py` is a small Flask + Socket.IO wrapper that
serves the `content/` directory and accepts `host_update` pushes. It's
under 150 lines and lives at
[`host/examples/engine-sw/display/server.py`](../../examples/engine-sw/display/server.py).
Run it with:

```
python3 server.py --port 8080 --content ./content
```

Then open `http://localhost:8080/` in a browser. Values will show
`---` until the application connects and pushes something.

> **Browser note.** The reference server serves plain HTTP. Chrome and
> other Chromium-based browsers sometimes upgrade `http://` URLs to
> `https://` via cached HSTS entries, especially for `.local` hostnames
> like `http://raspberrypi.local:8080`, and refuse to load the page. If
> you see an `HTTPS-only mode` warning or `certificate error`, either
> use Safari (more permissive by default), disable HTTPS-only mode for
> that origin in Chrome settings, or use the raw IP address instead of
> the `.local` name.

---

## 5. `enigma.js`: the JavaScript client library

The library exposes three top-level objects. It auto-initializes on
`DOMContentLoaded`; no explicit setup call is required.

### `Enigma`: state cache and event fan-out

**Reading cached state**

```js
Enigma.get('PortEngineSpec.Thrust');   // current value, or undefined
Enigma.getAll();                       // full copy of the cache
Enigma.has('PortEngineSpec.Thrust');   // bool
```

**Watching for changes**

```js
// One key. Callback: (newValue, key, allValues).
const unwatch = Enigma.watch('PortEngineSpec.Thrust', (v) => { ... });

// Many keys, same callback.
Enigma.watch(['A.Thrust', 'A.Temperature'], (v, k) => { ... });

// Unwatch. Also returned by watch() as a convenience.
unwatch();
Enigma.unwatch('PortEngineSpec.Thrust', myCallback);
```

**Global subscription**: fires on every delta. Useful for canvas or
WebGL render loops that want to redraw whenever *anything* changes.

```js
const unsubscribe = Enigma.subscribe((deltas, allValues) => {
  // deltas: { key: newValue, ... } - only what changed this update
  // allValues: complete current cache
});
```

**Connection status**

```js
Enigma.onStatus((connected) => { ... });   // fires immediately with current
Enigma.isConnected();                       // bool
```

### `Units`: number formatting

```js
Units.format(4200000, 'N');             // "4.2MN"
Units.format(0.075,   'A', 2);          // "75.00mA"  (auto-SI-prefixed)
Units.fixed(3.14159, 2);                // "3.14"
Units.percent(0.25);                    // "25%"     (0..1 input)
Units.percent100(75);                   // "75%"     (0..100 input)
```

All formatters return `'---<unit>'` when passed `null`, `undefined`, or
`NaN`, so a display that boots before any state arrives shows dashes
rather than "undefined".

### `Bindings`: declarative HTML attributes

For most values you don't need any JS at all. Add `data-*` attributes to
your HTML and `enigma.js` wires them up on page load.

**Text output**: `data-bind="SpecPath"`:

| Attribute | Purpose | Example |
|---|---|---|
| `data-unit="N"` | SI-prefix format with unit suffix | `4.2MN` |
| `data-decimals="2"` | Number of decimal places | `3.14` |
| `data-format="percent"` | Percentage, 0..1 input | `25%` |
| `data-format="percent100"` | Percentage, 0..100 input | `75%` |
| `data-format="fixed"` | Fixed decimals, no SI prefix | `3.14` |
| `data-color="red:>800, yellow:>500, green:*"` | Color rules, first match wins | element turns red |

Color-rule operators: `>`, `>=`, `<`, `<=`, `=`, `*` (fallback).

```html
<span data-bind="PortEngineSpec.Thrust" data-unit="N"></span>
<span data-bind="PortEngineSpec.Temperature" data-decimals="0"
      data-color="red:>=150, yellow:>=125, green:*"></span>
```

**Show / hide**: `data-show="SpecPath"` with one condition:

| Attribute | Condition |
|---|---|
| `data-eq="VALUE"` | value equals |
| `data-neq="VALUE"` | value not equal |
| `data-gt` / `data-gte` / `data-lt` / `data-lte="N"` | numeric compare |
| `data-in="A,B,C"` | value is in list |
| `data-notin="A,B,C"` | value is not in list |
| *(none)* | show on truthy |

```html
<div data-show="PortEngineSpec.State" data-eq="SCRAMMED">
  SCRAM ACTIVE - RESTART PROCEDURE REQUIRED
</div>
```

**Sprite switching**: swap between children based on a value:

```html
<div data-sprite-switch="PortEngineSpec.State">
  <img data-case="ONLINE"   src="/img/status-green.svg">
  <img data-case="OFFLINE"  src="/img/status-grey.svg">
  <img data-case="SCRAMMED" src="/img/status-red.svg">
</div>
```

Only the child whose `data-case` matches the current value is visible;
the rest have `display: none` applied. Value type is coerced to string
before comparison, so enum values and integers both work.

**CSS class binding**: `data-class-bind` + optional `data-class-prefix`:

```html
<div data-class-bind="PortEngineSpec.State" data-class-prefix="state-">
  <!-- adds class="state-ONLINE", swaps to state-SCRAMMED etc. -->
</div>
```

Bindings can be mixed freely with programmatic watches on the same
keys. The declarative layer does the boilerplate; the watchers do the
things that require actual computation.

### What the library does *not* do

- **No client -> server writes.** `Enigma` is read-only for spec state.
  Sending values back to the application (a button that toggles a control) is a
  separate, explicit path: see [Writing values
  back](#6-writing-values-back-display--application) below.
- **No throttling / debouncing.** Every delta fans out to every watcher
  immediately. If your application publishes a value at 60 Hz, watchers
  run at 60 Hz. Add your own `requestAnimationFrame` batching in the
  watcher if that matters.
- **No initial-state promise.** Bindings render `---` until the first
  update arrives (~100 ms after page load on a fresh connect). If you
  need to gate rendering on a full state being present, use
  `Enigma.onStatus` and check specific keys with `Enigma.has()`.

---

## 6. Writing values back (display -> application)

A display is not only a readout. A client can send messages back to the
application over the same socket: a button that toggles a control, a canvas drag
that nudges a value, a game engine reporting an in-world event. The application
receives them and does whatever it likes, typically writing a spec value that
then publishes back out to every display on the next tick.

This direction is used sparingly. In Halcyon Dawn almost all input comes from
physical panels, not screens. The notable exception is Unity: it is far better at
3D math than the host, so it computes NPC and geometry collisions in-scene and
reports the results back (a boarder impact, for instance). A touch screen with
interactive buttons is another natural case, and a cleaner one still would be a
dedicated input "board" type wrapping the touchscreen (see [Implementing a new
board handler](NEW_BOARD_HANDLER.md)) so its presses flow through the same
control-to-spec pipeline as any physical control, rather than through this ad hoc
event path.

The read path (specs to screen) is fully automatic. This write path is explicit
by design: the client emits a named event, and the application registers a handler
for it. There is deliberately no "set this spec from the browser" call, so a
display can never write a spec it was not meant to touch. The event name and
payload shape are yours; the two sides only have to agree.

**Client side (browser).** `enigma.js` is read-only for spec state, but its
underlying socket is available for your own events:

```js
Enigma._socket.emit('user_action', { action: 'toggle_purge', value: true });
```

**Application side.** Register a handler for that event on the display it comes
from:

```python
from enigma.displaymanager import DisplayManager

def on_user_action(data):
    if data.get('action') == 'toggle_purge':
        PortEngineSpec.PurgeActive = data.get('value')

dm = DisplayManager.get_instance()
if dm:
    dm.register_handler('PortEngineDisplay', 'user_action', on_user_action)
```

The callback runs on the DisplayManager background thread, so keep it light and
let the next tick publish any spec changes. Emits are fire-and-forget from the
client, and an exception in the handler is logged rather than sent back.

Unity displays use the same pattern from C# (see [Unity displays](#7-unity-displays-c-core)).

Wire-level detail (envelope format, reserved event names) is in the [WebSocket
protocol reference](DISPLAY_WEBSOCKET_PROTOCOL.md#6-bidirectional-writes-display--application);
the full handler API is in the [DisplayManager reference](api/DISPLAY_MANAGER.md).

---

## 7. Unity displays (C# core)

For native displays running under Unity or Godot, enigma ships a
generic C# `Enigma.cs` `MonoBehaviour` that speaks the same protocol.
The API is coarser than the JS library (no per-key `watch()`, no
declarative binding layer) but it handles the same connection,
handshake, cache, and event fan-out.

Attach as a component in the scene once:

```csharp
public class EngineReceiver : MonoBehaviour {
    private Enigma _enigma;

    void Start() {
        _enigma = FindObjectOfType<Enigma>();
        _enigma.OnUpdate += HandleUpdate;
    }

    void OnDestroy() {
        if (_enigma != null) _enigma.OnUpdate -= HandleUpdate;
    }

    void HandleUpdate(Dictionary<string, object> deltas) {
        if (deltas.TryGetValue("PortEngineSpec.Thrust", out var v)) {
            float thrust = System.Convert.ToSingle(v);
            // ...update your game object...
        }
    }
}
```

Full example: [`host/examples/engine-sw/unity/`](../../examples/engine-sw/unity/). See [Writing values
back](#6-writing-values-back-display--application) for the concept and [the
protocol reference](DISPLAY_WEBSOCKET_PROTOCOL.md) for the C# bidirectional path
(sending events back to the connected application). This is how Halcyon Dawn's
Unity scene reports collisions it computes in 3D back to the host.

---

## 8. Debugging

- **Server side.** Open `http://<display-host>:<port>/heartbeat` in a
  browser. It returns a JSON object listing every spec key the server
  has ever received. If the key you expect isn't in the list, the
  application isn't publishing it (check the display's Publish list) or
  the connection is failing (check `--port` and firewall).
- **Client side.** In the browser console, `Enigma.getAll()` prints the
  entire current cache. `Enigma.watch('...', console.log)` gives you a
  live log of any single key.
- **Reconnect testing.** Kill the display server; the browser will show
  `Enigma.isConnected() === false`. Restart the server; the client
  reconnects and receives the full state as one update.
- **On-page debug panel.** The stock `lib/debug-panel.js` + `lib/debug-panel.css`
  (shipped with the example client library) add a corner gear button that opens a
  live, dismissable list of every SpecVar the display has cached, updating in real
  time while open. Include the two files and it self-initializes off the `Enigma`
  client; nothing else to wire. Drop an optional
  `<div class="enigma-debug-hint">...</div>` label and the stylesheet places it by
  the gear.

---

## 9. Where the pieces live

```
host/examples/engine-sw/
+-- README.md                         intro + how to run
+-- application/                      application-side skeleton
|   `-- example_publisher.py          minimal publisher script
+-- configs/
|   +-- PortEngineSpec.json           spec definition
|   +-- PortEngineDisplay.json        display config
|   `-- display_mappings.json         display registration
+-- display/
|   +-- server.py                     display server (Flask + Socket.IO)
|   `-- content/                      served to browsers
|       +-- index.html
|       +-- main.js
|       +-- style.css
|       `-- lib/
|           +-- enigma.js             client library
|           `-- socket.io.min.js      socket.io client (vendored)
`-- unity/
    +-- Enigma.cs                     C# core: Socket.IO server + event fan-out
    `-- EngineReceiver.cs             sample MonoBehaviour subscribing to Enigma
```

The application-side code is a skeleton, not runnable end-to-end without
the enigma runtime and a physical control panel. The display side runs
in isolation: clone the example, start `server.py`, open the page, and
POST a synthetic update with `curl` to see the display come alive.
