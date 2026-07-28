#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
# SPDX-License-Identifier: MIT

"""
Engine example, input side: physical controls drive the spec.

This is the companion to engine-sw. Same PortEngineSpec, same web display; the
only difference is where the values come from. Here they come from real Enigma
boards read through the generated EngineControl panel:

    Throttle    AN08 analog pot        -> PortEngineSpec.Thrust
    RunStandby  SW14 momoffmom toggle  -> PortEngineSpec.State (ONLINE / OFFLINE)
    Scram       SW14 button            -> PortEngineSpec.State (SCRAMMED)
    Purge       SW14 button            -> PortEngineSpec.PurgeActive (while held)
    TempCap     QD04 encoder           -> PortEngineSpec.TemperatureCap

`EnginePanel` (a PanelManager subclass) reads those controls every tick and
writes the spec, exactly as a real subsystem would. It also runs a small reactor
thermal model, drives the toggle's LED to show the latched state, and locks out
the operational controls (input disabled + red DISABLED scheme) whenever the
reactor is not ONLINE.

This example needs the boards to do anything visible. To play with the display
and spec without hardware, use the interactive controls page in engine-sw.

Run the display server first (see the README or `make demo`), then run this.

Usage:
    python3 engine_panel.py
    python3 engine_panel.py --audio
"""

import argparse
import signal
import sys
import time
from pathlib import Path

from enigma import EnigmaManager, ConfigManager
from enigma.panelmanager import PanelManager

# Generated code (spec + controls) lives at the example root.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from generated.devices import PortEngineSpec
from generated.controls import EngineControl

THRUST_MAX = 8_000_000.0

_stop = False


def _request_stop(signum, _frame):
    global _stop
    _stop = True


def advance_temperature(temp, online, thrust, cap, dt):
    """First-order reactor thermal model. Temperature climbs with thrust while
    ONLINE and cools toward 100 MK otherwise, always clamped to the operator's
    temperature cap. Returns the new temperature."""
    target = 100.0 + (thrust / THRUST_MAX) * 100.0 if online else 100.0
    target = min(target, cap)
    return temp + (target - temp) * min(1.0, dt * 0.5)


class EnginePanel(PanelManager):
    """Reads the physical EngineControl inputs each tick and writes PortEngineSpec.

    Also: runs the thermal model, shows the latched run state on the toggle LED,
    and locks out the operational controls whenever the reactor is not ONLINE."""

    def __init__(self, ui=None):
        super().__init__()               # auto-registers; update() runs each tick
        self._ui = ui                    # generated Ui audio proxy, or None
        self._state = PortEngineSpec.State.Values.ONLINE   # spec is double-buffered; track locally
        self._temp = 100.0
        self._t = time.monotonic()
        self._applied = False            # force the initial lock/indicator on first tick
        self._prev_max_burn = False
        self._prev_purge = False
        self._prev_throttle = 0.0
        self._prev_tempcap = 150.0
        self._prev_audio_state = None
        self._last_knob = 0.0

    def update(self):
        ec = EngineControl
        S = PortEngineSpec.State.Values

        # Latched run state: the momoffmom toggle sticks (center rests, no report),
        # and the scram button overrides to SCRAMMED.
        new_state = self._state
        if ec.RunStandby.changed():
            if ec.RunStandby == ec.RunStandby.Values.ONLINE:
                new_state = S.ONLINE
            elif ec.RunStandby == ec.RunStandby.Values.OFFLINE:
                new_state = S.OFFLINE
        if ec.Scram.changed() and ec.Scram == ec.Scram.Values.SCRAM:
            new_state = S.SCRAMMED

        online = new_state == S.ONLINE
        if new_state != self._state or not self._applied:
            self._applied = True
            self._state = new_state
            PortEngineSpec.State = new_state
            self._lock_controls(online)      # enable/disable + scheme on the panel
            self._show_state(new_state)       # recolor the toggle's LED

        # Continuous + momentary inputs. Board values read None until the hardware
        # is present, so fall back to rest values. When not ONLINE the operational
        # controls are disabled (input frozen), so the engine reads as shut down.
        throttle = ec.Throttle.value
        throttle = throttle if throttle is not None else 0.0
        cap = ec.TempCap.value
        cap = cap if cap is not None else 150.0
        purge = ec.Purge == ec.Purge.Values.PURGE
        thrust = throttle if online else 0.0
        PortEngineSpec.Thrust = thrust
        PortEngineSpec.TemperatureCap = cap
        PortEngineSpec.PurgeActive = online and purge

        now = time.monotonic()
        self._temp = advance_temperature(self._temp, online, thrust, cap, now - self._t)
        self._t = now
        PortEngineSpec.Temperature = self._temp

        # Audio blips on transitions, through the generated Ui accessors, the same
        # interface engine-sw demonstrates. Audio is a first-class part of a panel
        # build; Halcyon Dawn leans on it heavily alongside the physical controls.
        if self._ui is not None:
            if (throttle != self._prev_throttle or cap != self._prev_tempcap) \
                    and now - self._last_knob >= 0.1:
                self._ui.knob_adjust()            # tick as the throttle or temp cap moves
                self._last_knob = now
            max_burn = online and throttle > 7_000_000
            if max_burn != self._prev_max_burn:
                self._ui.button_click()           # clunk crossing MAX BURN, either way
            if purge != self._prev_purge:
                self._ui.switch_toggle()          # toggle on purge, on and off
            if self._prev_audio_state is not None and new_state != self._prev_audio_state:
                self._ui.switch_toggle()          # toggle on a state change
            self._prev_max_burn = max_burn
            self._prev_purge = purge
            self._prev_throttle = throttle
            self._prev_tempcap = cap
            self._prev_audio_state = new_state

    def _lock_controls(self, online):
        """Operational controls are live only while ONLINE. Otherwise freeze their
        input and switch their indicators to the red DISABLED scheme."""
        ec = EngineControl
        lockable = (ec.Throttle, ec.Scram, ec.Purge, ec.TempCap)
        with_leds = (ec.Scram, ec.Purge, ec.TempCap)   # the AN08 throttle has no indicator
        if online:
            ec.enable(*lockable)
            for c in with_leds:
                c.Scheme = c.Schemes.DEFAULT
        else:
            ec.disable(*lockable)
            for c in with_leds:
                c.Scheme = c.Schemes.DISABLED

    def _show_state(self, state):
        """Color the Run/Standby toggle's resting LED to show the latched state."""
        S = PortEngineSpec.State.Values
        rs = EngineControl.RunStandby
        rs.Scheme = {
            S.ONLINE: rs.Schemes.ONLINE,
            S.OFFLINE: rs.Schemes.OFFLINE,
            S.SCRAMMED: rs.Schemes.SCRAM,
        }[state]


def main():
    parser = argparse.ArgumentParser(description="Engine example, input side.")
    parser.add_argument('--audio', action='store_true',
                        help='Also run the out-of-process audio engine and blip on transitions')
    args = parser.parse_args()

    for sig in (signal.SIGINT, signal.SIGTERM, getattr(signal, 'SIGQUIT', None)):
        if sig is not None:
            try:
                signal.signal(sig, _request_stop)
            except (OSError, ValueError):
                pass

    # EnigmaManager reads the configs, brings up whatever boards are connected
    # (per control_mappings.json), and stands up the DisplayManager. Publishing is on.
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

    EnginePanel(ui=ui)     # auto-registers; reads EngineControl from the boards each tick
    print("[enigma] Reading the EngineControl panel and publishing PortEngineSpec.")
    print("[enigma] Open http://localhost:8080/ . Ctrl-C to stop.")

    try:
        while not _stop:
            mgr.update()
            if audio is not None:
                audio.update()
            time.sleep(0.05)   # 20 Hz
    finally:
        if audio is not None:
            audio.shutdown()
        mgr.stop()
        print("\n[enigma] stopped cleanly.")


if __name__ == '__main__':
    main()
