# SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
# SPDX-License-Identifier: MIT

"""
Out-of-process audio daemon. Run as:

    python -m enigma.audio.daemon --project-root <path> [--config-dir configs]

Owns the real `enigma.audio.AudioManager` (and PyAudio). The main thread reads
one JSON envelope per line from stdin and dispatches it; a background thread runs
`AudioManager.update(dt)` on its own GIL, decoupled from whatever heavy work the
parent process is doing. That decoupling is the whole point: audio ticks no
longer contend with the parent for the GIL, so buffer serialization cannot be
starved by parent-side load.

`AudioManager.spawn()` starts this for you; you rarely invoke it directly.
"""

import argparse
import os
import signal
import sys
import threading
import time
from pathlib import Path

from ._ipc.protocol import decode


class _CachingWatcher:
    """Stand-in for a parent-side watcher object. The real `WatchedAudio` calls
    `get_current_value()` once per update; we return the most recent value the
    parent pushed for this event name."""

    def __init__(self, name, cache):
        self._name = name
        self._cache = cache

    def get_current_value(self):
        return self._cache.get(self._name, 0.0)


def main(project_root, config_dir="configs"):
    # Terminal signals (Ctrl-\, hangup, Ctrl-C) reach the whole foreground
    # process group. The parent handles them for graceful shutdown; the child
    # must ignore them or it inherits the default "terminate + core dump"
    # disposition and trips the macOS crash dialog. The parent closing our
    # stdin (or sending the shutdown sentinel) is our only exit path.
    for sig in (signal.SIGQUIT, signal.SIGHUP, signal.SIGINT):
        try:
            signal.signal(sig, signal.SIG_IGN)
        except (OSError, ValueError):
            pass

    # Audio config and sound paths resolve relative to the project root.
    os.chdir(project_root)

    # Import lazily so a non-daemon process never pulls the mixer in.
    from enigma import ConfigManager
    from . import AudioManager

    print("[enigma.audio.daemon] starting", file=sys.stderr, flush=True)

    audio_manager = AudioManager(ConfigManager(Path(config_dir)))

    # Latest watched values pushed by the parent. The CachingWatchers registered
    # with the audio_manager read from this dict.
    values_cache = {}
    shutdown_event = threading.Event()

    def tick_loop():
        # 200 Hz tick. Shortens the window where the tick thread is inside
        # audio_manager.update() holding shared state while the CoreAudio
        # callback wants the same lock — a longer window causes the
        # callback to block, underrun its ring buffer, and produce
        # audible clicks. Doubles daemon CPU (~10 % → ~20 % of one core),
        # still comfortably not a busy loop since sleep() yields to the OS
        # scheduler regardless of size.
        last = time.monotonic()
        while not shutdown_event.is_set():
            now = time.monotonic()
            dt = now - last
            last = now
            try:
                audio_manager.update(dt)
            except Exception as e:
                print(f"[enigma.audio.daemon] update error: {e}",
                      file=sys.stderr, flush=True)
            time.sleep(0.005)

    threading.Thread(target=tick_loop, daemon=True).start()

    def dispatch(call, args):
        """Run one command. Returns False on the shutdown sentinel."""
        if call == "shutdown":
            return False
        if call == "set_watched_values":
            if args and isinstance(args[0], dict):
                values_cache.update(args[0])
            return True
        if call == "register_watched_audio":
            name = args[0]
            audio_manager.register_watched_audio(
                name, _CachingWatcher(name, values_cache)
            )
            return True
        # Everything else maps 1:1 onto a method on AudioManager.
        method = getattr(audio_manager, call, None)
        if method is None:
            print(f"[enigma.audio.daemon] unknown call: {call!r}",
                  file=sys.stderr, flush=True)
            return True
        try:
            method(*args)
        except Exception as e:
            print(f"[enigma.audio.daemon] error in {call}({args!r}): {e}",
                  file=sys.stderr, flush=True)
        return True

    try:
        for line in sys.stdin:
            call, args = decode(line)
            if call is None:
                if line.strip():
                    print(f"[enigma.audio.daemon] bad message: {line.strip()!r}",
                          file=sys.stderr, flush=True)
                continue
            if not dispatch(call, args):
                break
    except KeyboardInterrupt:
        pass
    finally:
        shutdown_event.set()
        try:
            audio_manager.shutdown()
        except Exception:
            pass
        print("[enigma.audio.daemon] exited", file=sys.stderr, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Enigma out-of-process audio daemon")
    parser.add_argument("--project-root", default=".",
                        help="directory holding configs/ and sounds/")
    parser.add_argument("--config-dir", default="configs",
                        help="config directory name under the project root")
    args = parser.parse_args()
    main(Path(args.project_root), args.config_dir)
