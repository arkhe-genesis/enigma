# Engine example (hardware + software)

The input-side companion to [`engine-sw`](../engine-sw/). Same `PortEngineSpec`,
same web display; the difference is where the values come from. Here they come
from real Enigma boards, read through the generated `EngineControl` panel and
written to the spec by a `PanelManager` subclass. The display and the debug gear
react exactly as they do in `engine-sw`, because nothing downstream of the spec
knows or cares that the numbers now originate at a knob instead of a timer.

No boards on hand? This example is about the hardware path, so it needs the boards
to show anything. To play with the same display and spec without hardware, use the
interactive controls page in [`engine-sw`](../engine-sw/).

## The controls

| Control | Board | Channel | Type | Drives |
|---------|-------|---------|------|--------|
| Throttle | AN08 (analog) | 1 | potentiometer | `Thrust` (0 to 8 MN) |
| Run / Standby | SW14 (switch) | 1 | momoffmom toggle | `State` = ONLINE (up) / OFFLINE (down) |
| Scram | SW14 (switch) | 2 | momentary button | `State` = SCRAMMED |
| Purge | SW14 (switch) | 3 | momentary button | `PurgeActive` (true while held) |
| Temp cap | QD04 (encoder) | 1 | rotary encoder | `TemperatureCap` (100 to 200 MK) |

Each control type feeds the spec the same way: `EngineControl.<name>.value` (or a
comparison against `.Values.<STATE>` for the switches). One panel object reads
them all, regardless of which of the three boards each one lives on.

The Run/Standby toggle is a **momoffmom**: it rests at center and reports nothing
there, so the last flick sticks. Flick up for ONLINE, down for OFFLINE; it springs
back to center and the state stays put. Its own LED shows the latched state
(green ONLINE, amber OFFLINE, red SCRAMMED). Scram overrides to SCRAMMED.

Whenever the reactor is not ONLINE, the operational controls (throttle, scram,
purge, temp cap) are **locked**: their input is disabled and their indicators
switch to a red DISABLED scheme. Flick back to ONLINE and they re-enable and
restore their normal look. This is the runtime enable/disable and scheme API
driven straight off the spec state; see `engine_panel.py`.

## Wiring

Set each board's DIP-switch address to **00** (that is what `control_mappings.json`
expects: `AN08-00`, `SW14-00`, `QD04-00`). Give the LED-bearing boards their
off-board 5 V supply. Then wire each control to the channel above:

- **AN08 throttle (channel 1).** A potentiometer across the 3-pin channel connector:
  wiper to signal, the two ends to the 3.3 V and ground pins. Full travel maps
  0 to 8 MN. See [AN08_CONFIG.md](../../enigma/docs/AN08_CONFIG.md).
- **SW14 Run/Standby (port 1).** A center-off toggle (or any 3-position rocker) on
  the 3-pin connector: the connector is state1 / common / state2 top to bottom, so
  the up contact goes to state1, the down contact to state2, the pole to common.
- **SW14 Scram (port 2) and Purge (port 3).** Momentary buttons, one pole each:
  the button between state1 and common (state2 left unconnected). These are
  illuminated pushbuttons; their LEDs are driven by the board.
- **QD04 Temp cap (port 1).** A quadrature encoder (A / B / common) plus its QD04 LED
  ring chain board. See [QD04_CONFIG.md](../../enigma/docs/QD04_CONFIG.md).

Full connector and switch-type detail is in the per-board config docs
([SW14](../../enigma/docs/SW14_CONFIG.md), [AN08](../../enigma/docs/AN08_CONFIG.md),
[QD04](../../enigma/docs/QD04_CONFIG.md)) and the hardware board READMEs under
`hardware/`.

## Quick start

```
make install    # once: installs the library with the audio + display extras
make demo       # display server + the panel app (reads the boards), with audio
```

`make demo` prints the browser URL and starts everything; open the display at
**<http://localhost:8080/>**. Turn the throttle, flick Run/Standby, hold Purge,
spin the Temp cap: the readouts move and the debug gear shows the SpecVars change.

No boards? The point here is the hardware path, so it needs the boards to show
anything. To drive the same display and spec without hardware, use the interactive
controls page in [`engine-sw`](../engine-sw/).

## Thermal model

`Temperature` is not an operator input; the panel derives it. It climbs with
`Thrust` while ONLINE and cools toward 100 MK otherwise, always clamped to the
operator's `TemperatureCap`. Dial the cap down and you can see the readout stop
climbing at the ceiling you set.

## Audio

With `make demo` (or `--audio`) the app spawns the out-of-process audio engine and
blips on transitions through the generated `Ui` accessors: a knob tick as the
throttle or temp cap moves, a clunk crossing MAX BURN, and a toggle on purge and on
each state change. Audio is a first-class part of a panel build: Halcyon Dawn leans
on it heavily alongside the physical controls (UI blips, spec-driven alerts, voice
callouts). This is the same audio interface engine-sw demonstrates. Without the
`[audio]` extra the flag prints a notice and the app runs unchanged.

## Layout

```
engine-full/
+-- README.md                 (this file)
+-- Makefile                  build + run (`make help`)
+-- application/
|   `-- engine_panel.py       reads the controls, writes the spec, blips on transitions
+-- configs/
|   +-- control_mappings.json board address -> board config file
|   +-- EngineAnalog.json     AN08: throttle pot
|   +-- EngineSwitches.json   SW14: run/standby toggle, scram, purge (with schemes)
|   +-- EngineDial.json       QD04: temperature-cap encoder (with LED ring)
|   +-- PortEngineSpec.json   the spec (identical to engine-sw)
|   +-- device_mappings.json  binds the spec
|   +-- audio_*.json          audio class / library / device config (for --audio)
|   +-- PortEngineDisplay.json / display_mappings.json   display wiring
+-- sounds/                   CC0 UI blip WAVs (for --audio)
+-- generated/                build output (git-ignored); `make gen` writes here
+-- display/                  identical to engine-sw's display (server + page + debug gear)
`-- unity/                    reference C# display, not runnable as-is (see unity/README.md)
```

## How it works

`EnginePanel.update()` runs every manager tick. It reads each control off the
generated `EngineControl` class, writes the corresponding spec field, runs the
thermal model, and manages the LED schemes and the ONLINE lock. That is the entire
input side: declare the controls in JSON, read them in one panel, write the spec.
The manager brings up whatever boards are connected (per `control_mappings.json`);
nothing else changes whether the values originate at hardware here or at a synthetic
timer (or the interactive controls page) in `engine-sw`.
