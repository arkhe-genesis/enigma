# Engine example (software only)

Reference layout of a complete enigma display: spec definition,
display config, server, browser page, and Unity client, all wired up
around a single hypothetical `PortEngineSpec` device.

**No hardware required.** A small web page stands in for a hardware panel: this
application serves it on its own input server, stores what it posts as the
`SimPanel` class attributes, and `EngineDevice.update()` reads those, drives the
spec, runs a reactor thermal model, and plays audio on transitions. Drive the
panel, watch the display react.

Its companion, `engine-full`, is the same example driven by real Enigma boards.
The one real difference is the input read: here the device reads `SimPanel` (fed
by the web page); there it reads `EngineControl.<Control>.value` from the generated
control code. Everything downstream is identical, and the web display is
byte-identical between the two. The display server stays output only in both: the
simulated-panel input server lives with the application, separate by design.

In practice, a remote display might be running on a Raspberry Pi that starts
server.py at boot in a chromium window, displaying locally.  The web page it
vends can render whatever you want, whether HTML or WebGL, using the spec
variables that the display subscribes to.

Caching of variables is reliable. The enigma library caches its local copy,
the python (and C#) display servers cache their updates. This allows data
to stay in sync even if one or the other restarts/reconnects. On first
[re]connect, the enigma libary sends all of them. Thereafter it just sends
deltas as independent variables change.  My Halcyon Dawn implementation
sends hundreds of complex JSON based combat objects every update and it
doesnt break a sweat.


## What this is

The layout below shows how the pieces of an enigma display fit
together. Every code snippet in
[`DISPLAY_CONFIG.md`](../../enigma/docs/DISPLAY_CONFIG.md) and
[`DISPLAY_WEBSOCKET_PROTOCOL.md`](../../enigma/docs/DISPLAY_WEBSOCKET_PROTOCOL.md)
is a subset of what's here.

```
engine-sw/
+-- README.md                 (this file)
+-- Makefile                  build + run the demo (`make help`)
+-- application/
|   +-- example_app.py        the device (reads SimPanel, writes the spec) + input server
|   `-- panel/                the simulated-panel page this app serves (not the display)
|       +-- index.html
|       +-- controls.js       posts widget values to /input
|       +-- controls.css
|       `-- style.css
+-- configs/
|   +-- PortEngineSpec.json   spec definition (fields + types + defaults)
|   +-- device_mappings.json      binds the spec so its class is generated
|   +-- PortEngineDisplay.json    display config (URL + Publish list)
|   +-- display_mappings.json     display registration
|   +-- audio_classes.json    audio class/volume config (for --audio)
|   +-- audio_library.json    the three UI blip events (for --audio)
|   `-- audio_devices.json    audio output device ("default")
+-- sounds/
|   +-- README.md             sound license (CC0)
|   `-- ui/                   click / toggle / knob blips (CC0)
+-- generated/                build output (git-ignored); `make gen` writes here
|   +-- devices.py            generated PortEngineSpec class
|   `-- audio_events.py       generated audio proxies (Ui.button_click(), ...)
+-- display/
|   +-- server.py             display server (Flask + Socket.IO)
|   `-- content/              files served to browsers
|       +-- index.html
|       +-- main.js           programmatic watch demo
|       +-- style.css
|       `-- lib/
|           +-- enigma.js       client library
|           +-- debug-panel.js  stock debug overlay (gear -> subscribed SpecVars)
|           +-- debug-panel.css
|           `-- socket.io.min.js
`-- unity/                    reference C#, not runnable as-is (see unity/README.md)
    +-- README.md             wiring + the MiniJSON dependency
    +-- Enigma.cs             C# core: Socket.IO server + event fan-out
    `-- EngineReceiver.cs     sample MonoBehaviour consuming Enigma updates
```

## Quick start

A `Makefile` builds and runs the whole thing. From this directory:

```
make install    # once: installs the library with the audio + display extras
make demo       # runs the display server + the app (which serves the panel), with audio
```

`make demo` prints both URLs and starts everything: open the display at
**<http://localhost:8080/>** and the panel at **<http://localhost:8090/>** in two
tabs. Move the panel's controls and the display reacts, with audio on transitions.
Press Ctrl-C to stop: the app exits cleanly and the display server is reaped
automatically. Run `make help` for the full list of targets.

The rest of this document explains the pieces the Makefile wires together, in
case you want to run them by hand.

## Running the display in isolation

You can bring up the display server and browser page with no enigma
runtime and no hardware. Values render as `---` until something pushes
to the server; you can drive them by hand with `curl` or by running
the example app below.

```
cd display/
python3 -m pip install flask flask-socketio
python3 server.py --port 8080 --content ./content
```

Then in a browser: <http://localhost:8080/>. You'll see labels and
dashes for every readout.

In another terminal, drive some values in:

```
# Set thrust to 4.2 MN
curl -X POST http://localhost:8080/update \
     -H 'Content-Type: application/json' \
     -d '{"PortEngineSpec.Thrust": 4200000}'
```

The browser updates within one frame. Try posting different values
for `PortEngineSpec.State` (`ONLINE`, `OFFLINE`, `SCRAMMED`) and
`PortEngineSpec.PurgeActive` (`true`, `false`) to see the
operational-mode label switch between `NOMINAL`, `PURGING`, `STANDBY`,
and `SHUTDOWN`. The label is a JS-side derivation combining the two
values (see `content/main.js`).

Or run the example app: a real enigma application that defines a device owning
the spec and lets `EnigmaManager` publish it to the display for you (start the
server first; the app reads the display's URL from `PortEngineDisplay.json`):

```
python3 application/example_app.py
```

## Adding audio

The app can also drive the **out-of-process audio engine** as a live
demonstration of that interface. With `--audio` it starts the audio daemon via
`AudioManager.spawn()`, and `EngineDevice.update()` plays a short UI blip on each
transition (the same click / toggle / knob sounds a physical panel uses): a knob
blip entering MAX BURN, a click leaving it, a toggle on each purge, and a toggle on
a state change. Drive those from the panel and you hear them.

Those blips are triggered through the **generated audio accessors**
(`Ui.button_click()`, `Ui.switch_toggle()`, `Ui.knob_adjust()`), which is how
real code always calls audio, never the low-level manager methods. `spawn()`
installs the daemon client as the singleton those accessors resolve through, so
the calls forward to the child process transparently.

```
make install     # once: installs the library with the audio + display extras
make app-audio   # or:  python3 application/example_app.py --audio
```

The generated code (`generated/devices.py`, `generated/audio_events.py`) is built
from the JSON configs by `make gen` (and automatically by `make app-audio`); it
is not committed. The audio configs and CC0 blip WAVs ship under the example root
and are found automatically (see [`sounds/README.md`](sounds/README.md)). Audio
is entirely optional: without the `[audio]` extra the flag prints a notice and
the app runs unchanged.

The engine runs in its own OS process precisely so heavy work in this loop can't
starve it; see [audio usage](../../enigma/audio/USAGE.md) for why the daemon
exists.

## Clean shutdown

`example_app.py` doubles as a small reference for graceful teardown. It
installs handlers for `SIGINT` (Ctrl-C), `SIGQUIT` (Ctrl-\\), and `SIGTERM`
(`kill`) that just set a stop flag, so the main loop always exits through one
`finally` block. That block stops the `EnigmaManager` and shuts down + reaps the
audio daemon, so every exit path releases both the manager and the child process
cleanly rather than leaving anything orphaned.

## Running with a real enigma application

This example already *is* a real enigma application: `example_app.py` builds an
`EnigmaManager`, registers `EngineDevice`, and lets the display publish
automatically from the configs. To make it a hardware subsystem, delete the input
server and change the input read in `EngineDevice.update()` from `SimPanel` to
`EngineControl.<Control>.value`; everything downstream stays identical.
`engine-full` is exactly that.

## Debug panel

Any page that includes the stock `lib/debug-panel.js` and `lib/debug-panel.css` gets a small gear
button in the corner. Click it to open a live list of every SpecVar the display has cached from the
server; the list updates in real time while open, and Escape or a background click closes it. It reads
only the `Enigma` client (`getAll()` / `subscribe()`), so it drops onto any display with no extra
wiring: include the two files and it self-initializes. The optional
`<div class="enigma-debug-hint">...</div>` label is positioned next to the gear by the stylesheet;
this example uses it to point the gear out.

## The simulated panel

The application serves a small controls page on its own input server (port 8090,
`application/panel/`): sliders and buttons for throttle, state, purge, and the
temperature cap. Each widget POSTs its value to `/input`, where the app stores it
as a `SimPanel` class attribute. `EngineDevice.update()` reads `SimPanel` every
tick, exactly as a hardware build reads `EngineControl` (see engine-full), so the
same device logic, spec writes, thermal model, and audio run either way.

This input server is the one part of the app a hardware build would not have. It
is kept here, in the application, on purpose: the display server (`server.py`)
never sees input and stays output only. (The `/update` HTTP fallback on the display
server, used by the `curl` examples above, is a separate display-only convenience
and does not involve the app or the device.)

## Browser note

Chrome and other Chromium-based browsers sometimes upgrade `http://`
URLs to `https://` via cached HSTS entries, especially for `.local`
hostnames. If your display page won't load in Chrome, try Safari,
disable Chrome's HTTPS-only mode for that origin, or use a raw IP
instead of `hostname.local`.
