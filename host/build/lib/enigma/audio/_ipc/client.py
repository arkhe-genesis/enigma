# SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
# SPDX-License-Identifier: MIT

"""
AudioClient - the parent-side surrogate the generated audio proxies talk to.

It duck-types the slice of the `enigma.audio.AudioManager` call surface that the
generated code uses, but every call is serialized over the daemon's stdin pipe
instead of executing locally. `AudioManager.spawn()` constructs one, installs it
as the singleton (so `AudioManager.get_instance()` returns it and the generated
proxies forward transparently), and hands it back for the main loop (`update`)
and shutdown.
"""

import json
import sys
import threading
from pathlib import Path

from .protocol import encode
from ..watch_condition import WatchCondition


# Hysteresis on per-name watched-value diffs. Below this the value is treated as
# unchanged and no message is sent; the daemon's WatchedAudio interpolation
# smooths the rest, so a 1e-3 floor is plenty.
_EPS = 1e-3


class AudioClient:
    """Duck-types the AudioManager call surface used by codegen; every call is
    shipped to the daemon as one line of JSON over its stdin pipe."""

    def __init__(self, pipe, proc=None, project_root=None):
        self._pipe = pipe          # daemon's stdin (BufferedWriter)
        self._proc = proc          # daemon subprocess handle (for shutdown)
        self._lock = threading.Lock()
        self._dead = False
        # name -> watcher object. Codegen passes the proxy instance as the
        # watcher; update() reads get_current_value() from it each tick and
        # pushes changed values to the daemon, which keeps its own cache.
        self._watchers = {}
        self._last = {}
        # Parent-side watch_condition evaluation. Audio-library entries with
        # `watch_condition` (used by voice callouts triggered on rising /
        # falling threshold crossings) can't be evaluated inside the daemon:
        # the daemon reads specs from its OWN copy of generated.devices,
        # which is never updated because spec writes happen in the parent
        # process. We mirror the WatchCondition objects here and evaluate
        # them against the parent's live specs, dispatching play_event()
        # over the wire on trigger.
        self._watch_conditions = self._load_watch_conditions(project_root)

    # -- internal --------------------------------------------------------

    @staticmethod
    def _load_watch_conditions(project_root):
        """Parse configs/audio_library.json for entries with `watch_condition`
        and build a list of WatchCondition objects. Called once at
        construction. Returns [] on any parse failure — a missing library
        just means no parent-side callouts fire, which matches the pre-fix
        behaviour rather than throwing at startup."""
        conditions = []
        try:
            root = Path(project_root) if project_root else Path.cwd()
            lib_path = root / "configs" / "audio_library.json"
            with open(lib_path) as f:
                data = json.load(f)
            for name, entry in data.get("events", {}).items():
                if not isinstance(entry, dict):
                    continue
                spec = entry.get("watch_spec")
                cond_str = entry.get("watch_condition")
                if spec and cond_str:
                    conditions.append(WatchCondition(name, spec, cond_str))
        except Exception as e:
            print(f"[enigma.audio] failed to load watch_conditions: {e}",
                  file=sys.stderr)
        return conditions

    @staticmethod
    def _get_spec_value(spec_string):
        """Read a live spec value from the parent process's generated.devices.
        Returns None if unresolvable. Mirrors AudioManager._get_spec_value,
        but runs in the parent so the values are current."""
        try:
            import generated.devices as devices
            parts = spec_string.split(".")
            if len(parts) != 2:
                return None
            spec_name, attr_name = parts
            spec = getattr(devices, spec_name, None)
            if spec is None:
                return None
            val = getattr(spec, attr_name, None)
            if val is None:
                return None
            return float(val)
        except Exception:
            return None

    def _send(self, call, *args):
        if self._dead:
            return
        try:
            with self._lock:
                self._pipe.write(encode(call, *args))
                self._pipe.flush()
        except (BrokenPipeError, OSError) as e:
            self._dead = True
            print(f"[enigma.audio] daemon pipe closed ({e}); audio disabled",
                  file=sys.stderr)

    # -- fire-and-forget surface (mirrors AudioManager) ------------------

    def play_event(self, event_name):
        self._send("play_event", event_name)

    def start_loop(self, event_name):
        self._send("start_loop", event_name)

    def stop_loop(self, event_name):
        self._send("stop_loop", event_name)

    def register_watched_audio(self, event_name, watcher_object):
        # Stash the watcher locally (update() reads it); only the name crosses
        # the wire, where the daemon attaches its own caching stand-in. Lock the
        # dict write so a concurrent update() can't hit "changed size during
        # iteration".
        with self._lock:
            self._watchers[event_name] = watcher_object
        self._send("register_watched_audio", event_name)

    def start_watched_audio(self, event_name):
        self._send("start_watched_audio", event_name)

    def pause_watched_audio(self, event_name):
        self._send("pause_watched_audio", event_name)

    def stop_watched_audio(self, event_name):
        self._send("stop_watched_audio", event_name)

    def reset_watched_audio(self, event_name, now=False):
        self._send("reset_watched_audio", event_name, bool(now))

    def set_class_volume(self, class_name, level):
        self._send("set_class_volume", class_name, float(level))

    def clear_pending_class(self, class_name):
        # Codegen exposes this as returning an int; nothing reads the count, so
        # ship the call and return 0.
        self._send("clear_pending_class", class_name)
        return 0

    def reset_class(self, class_name, now=False):
        self._send("reset_class", class_name, bool(now))

    def set_master_audio_volume(self, level):
        self._send("set_master_audio_volume", float(level))

    def set_master_haptic_volume(self, level):
        self._send("set_master_haptic_volume", float(level))

    def reset_all(self):
        self._send("reset_all")

    # -- query stubs: never used by live code, return True so a defensive
    #    future caller does not hang ---------------------------------------

    def class_ready(self, class_name):
        return True

    def watched_audio_ready(self, event_name):
        return True

    def all_ready(self):
        return True

    # -- main loop -------------------------------------------------------

    def update(self, dt=None):
        """Call once per tick, exactly where an in-process `AudioManager.update`
        would go. Reads each registered watched value locally and ships changed
        ones to the daemon, whose WatchedAudio loop consumes them. `dt` is
        accepted for signature-compatibility with AudioManager.update() and
        ignored (the daemon measures its own tick delta)."""
        with self._lock:
            items = list(self._watchers.items())
        deltas = {}
        for name, watcher in items:
            try:
                v = float(watcher.get_current_value())
            except Exception:
                # Value source may not be ready yet (e.g. a Spec not yet
                # initialised); skip and catch the next transition.
                continue
            prev = self._last.get(name)
            if prev is None or abs(v - prev) > _EPS:
                deltas[name] = v
                self._last[name] = v
        if deltas:
            self._send("set_watched_values", deltas)

        # Evaluate watch_condition entries parent-side (see __init__ note).
        # Read live specs, run each WatchCondition, dispatch play_event()
        # on triggers.
        for condition in self._watch_conditions:
            value = self._get_spec_value(condition.watch_spec)
            if value is None:
                continue
            if condition.update(value):
                self.play_event(condition.event_name)

    # -- lifecycle -------------------------------------------------------

    def shutdown(self):
        """Send the graceful shutdown sentinel, close the pipe, and reap the
        daemon process."""
        self._send("shutdown")
        if not self._dead:
            try:
                self._pipe.close()
            except Exception:
                pass
            self._dead = True
        if self._proc is not None:
            try:
                self._proc.wait(timeout=2.0)
            except Exception:
                try:
                    self._proc.terminate()
                except Exception:
                    pass
