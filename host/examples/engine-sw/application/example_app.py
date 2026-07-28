#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
# SPDX-License-Identifier: MIT

"""
Engine example, software side: a web page stands in for a hardware panel.

Same PortEngineSpec and same web display as engine-full; the only real difference
is where the inputs come from. Here this application runs a small HTTP server that
serves a browser controls page and stores what it posts as the `SimPanel` class
attributes below. `EngineDevice.update()` reads those attributes each tick, writes
the spec, runs the reactor thermal model, and plays audio on transitions. The
manager ticks `update()` automatically; that is where the work lives.

In a hardware build (see engine-full) the application server and `SimPanel`
disappear: the device reads `EngineControl.<Control>.value` from the generated
control code instead. Everything after the input read is identical. That is the
whole point: the device does not care whether the numbers come from a web page
standing in for a panel or from a real one.

The display server (display/server.py) is output only and never sees this input.
Keeping the simulated-panel input server here, separate from the display server,
is deliberate: the display code stays clean.

Run the display server first (see the README or `make demo`), then run this.
Add --audio to also drive the out-of-process audio engine.

Usage:
    python3 example_app.py
    python3 example_app.py --audio
"""

import argparse
import functools
import http.server
import json
import signal
import sys
import threading
import time
from pathlib import Path

from enigma import EnigmaManager, ConfigManager
from enigma.device import Device

# Generated code (spec, audio proxies) lives at the example root.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from generated.devices import PortEngineSpec

PANEL_DIR = Path(__file__).resolve().parent / "panel"   # the controls page this app serves
THRUST_MAX = 8_000_000.0

_stop = False


def _request_stop(signum, _frame):
    global _stop
    _stop = True


class SimPanel:
    """A simulated hardware panel. The web controls page POSTs here and these class
    attributes hold the latest values, the way a physical board's controls would.

    In a hardware build this class does not exist. The device reads
    `EngineControl.<Control>.value` from the generated control code instead; see
    engine-full for the same logic driven by real boards."""

    throttle = 0.0        # 0 .. 8 MN         (an AN08 pot in engine-full)
    state = "ONLINE"       # ONLINE/OFFLINE/SCRAMMED  (an SW14 toggle + scram button)
    purge = False          # true while held    (an SW14 button)
    tempcap = 150.0        # 100 .. 200 MK      (a QD04 encoder)


def advance_temperature(temp, online, thrust, cap, dt):
    """First-order reactor thermal model. Temperature climbs with thrust while
    ONLINE and cools toward 100 MK otherwise, always clamped to the temperature
    cap. Returns the new temperature."""
    target = 100.0 + (thrust / THRUST_MAX) * 100.0 if online else 100.0
    target = min(target, cap)
    return temp + (target - temp) * min(1.0, dt * 0.5)


class EngineDevice(Device):
    """Owns PortEngineSpec. Reads the panel inputs each tick, writes the spec, runs
    the thermal model, and plays audio on transitions. EnigmaManager ticks
    update() automatically, so all the logic lives here rather than in the main
    loop."""

    def __init__(self, ui=None):
        super().__init__()          # auto-registers with the manager
        self._ui = ui               # generated Ui audio proxy, or None
        self._temp = 100.0
        self._t = time.monotonic()
        self._prev_state = None
        self._prev_max_burn = False
        self._prev_purge = False
        self._prev_throttle = 0.0
        self._prev_tempcap = 150.0
        self._last_knob = 0.0

    def update(self):
        S = PortEngineSpec.State.Values

        # --- read the inputs ---------------------------------------------------
        # Software build: from the simulated panel (SimPanel, driven by the web
        # page). Hardware build: read EngineControl.<Control>.value / compare
        # against .Values here instead; nothing below this block changes.
        throttle = SimPanel.throttle
        state = {"ONLINE": S.ONLINE, "OFFLINE": S.OFFLINE, "SCRAMMED": S.SCRAMMED}.get(
            SimPanel.state, S.ONLINE)
        purge = SimPanel.purge
        cap = SimPanel.tempcap
        online = state == S.ONLINE

        # --- drive the spec ----------------------------------------------------
        PortEngineSpec.State = state
        PortEngineSpec.Thrust = throttle if online else 0.0
        PortEngineSpec.TemperatureCap = cap
        PortEngineSpec.PurgeActive = purge

        # --- thermal model -----------------------------------------------------
        now = time.monotonic()
        self._temp = advance_temperature(self._temp, online, throttle if online else 0.0,
                                         cap, now - self._t)
        self._t = now
        PortEngineSpec.Temperature = self._temp

        # --- audio on transitions ----------------------------------------------
        if self._ui is not None:
            # A knob tick as the throttle or temp cap moves, rate-limited so a drag
            # is a run of ticks rather than a machine-gun.
            if (throttle != self._prev_throttle or cap != self._prev_tempcap) \
                    and now - self._last_knob >= 0.1:
                self._ui.knob_adjust()
                self._last_knob = now
            # A clunk crossing the MAX BURN threshold, either direction.
            max_burn = online and throttle > 7_000_000
            if max_burn != self._prev_max_burn:
                self._ui.button_click()
            # A toggle on every purge change (on and off) and every state change.
            if purge != self._prev_purge:
                self._ui.switch_toggle()
            if self._prev_state is not None and state != self._prev_state:
                self._ui.switch_toggle()
            self._prev_max_burn = max_burn
            self._prev_purge = purge
            self._prev_throttle = throttle
            self._prev_tempcap = cap
        self._prev_state = state


# --------------------------------------------------------------------------- #
#  Simulated-panel input server (software build only)
# --------------------------------------------------------------------------- #
class _PanelHandler(http.server.SimpleHTTPRequestHandler):
    """Serves the controls page and accepts its POSTs, writing SimPanel. This is
    the one piece of the app that would not exist in a hardware build: it stands
    in for a physical panel. The display server is untouched by any of it."""

    def do_POST(self):
        if self.path != '/input':
            self.send_error(404)
            return
        length = int(self.headers.get('Content-Length', 0))
        try:
            data = json.loads(self.rfile.read(length) or b'{}')
        except json.JSONDecodeError:
            self.send_error(400)
            return
        if 'throttle' in data:
            SimPanel.throttle = float(data['throttle'])
        if 'state' in data:
            SimPanel.state = str(data['state'])
        if 'purge' in data:
            SimPanel.purge = bool(data['purge'])
        if 'tempcap' in data:
            SimPanel.tempcap = float(data['tempcap'])
        self.send_response(204)
        self.end_headers()

    def end_headers(self):
        # Never cache the panel: it is edited live during development, and a stale
        # controls.js is a classic "my change did nothing" trap.
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def log_message(self, *args):
        pass   # quiet; this is a demo helper, not a production server


def start_panel_server(port):
    handler = functools.partial(_PanelHandler, directory=str(PANEL_DIR))
    httpd = http.server.ThreadingHTTPServer(('', port), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def main():
    parser = argparse.ArgumentParser(description="Engine example, software side.")
    parser.add_argument('--audio', action='store_true',
                        help='Also run the out-of-process audio engine and blip on transitions')
    parser.add_argument('--panel-port', type=int, default=8090,
                        help='Port for the simulated-panel controls page (default: 8090)')
    args = parser.parse_args()

    for sig in (signal.SIGINT, signal.SIGTERM, getattr(signal, 'SIGQUIT', None)):
        if sig is not None:
            try:
                signal.signal(sig, _request_stop)
            except (OSError, ValueError):
                pass

    # EnigmaManager reads the configs, brings up any boards (none here), and stands
    # up the DisplayManager from the configs. Publishing to the display is on.
    mgr = EnigmaManager(ConfigManager(str(ROOT / "configs")))
    mgr.start()

    audio, ui = None, None
    if args.audio:
        try:
            from enigma.audio import AudioManager
            from generated.audio_events import Ui
            audio = AudioManager.spawn(str(ROOT))
            ui = Ui
            print("[enigma] audio daemon spawned (out-of-process)")
        except Exception as exc:
            print(f"[enigma] --audio requested but unavailable ({exc}); continuing without audio")
            audio, ui = None, None

    EngineDevice(ui=ui)                      # auto-registers; update() does the work
    panel = start_panel_server(args.panel_port)

    print(f"[enigma] Simulated panel (controls page): http://localhost:{args.panel_port}/")
    print("[enigma] Display: http://localhost:8080/ . Drive the panel, watch the display. Ctrl-C to stop.")

    try:
        while not _stop:
            mgr.update()                     # ticks EngineDevice.update(), commits, publishes
            if audio is not None:
                audio.update()
            time.sleep(0.05)                 # 20 Hz
    finally:
        panel.shutdown()
        if audio is not None:
            audio.shutdown()
        mgr.stop()
        print("\n[enigma] stopped cleanly.")


if __name__ == '__main__':
    main()
