# SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
# SPDX-License-Identifier: MIT

"""
Audio Manager - Main audio subsystem coordinator

Singleton manager that coordinates all audio playback:
- Event-based sound triggering
- Class-based volume control
- Voice callout priority queue
- Watched audio with threshold-based behavior
- Background thread for audio updates
- Thread-safe event queue
"""

import json
import time
import random
import threading
from typing import Dict, List, Optional, Any
from pathlib import Path

from .sound_library import SoundLibrary
from .audio_player import AudioPlayer
from .voice_queue import VoiceQueue
from .watched_audio import WatchedAudio
from .watch_condition import WatchCondition
from enigma.colors import print_error, print_warning


# When True, haptic volume is scaled by the event's volume setting in addition to
# master_haptic_volume. When False, haptic always plays at master_haptic_volume
# regardless of event volume - preferred to avoid under-driving haptic transducers.
_HAPTIC_SCALES_WITH_EVENT_VOLUME = False


class AudioManager:
    """Main audio system manager (singleton)"""

    _instance = None

    def __init__(self, config_manager=None):
        """
        Initialize audio manager

        Args:
            config_manager: ConfigManager instance for loading configs
        """
        if AudioManager._instance is not None:
            raise RuntimeError("AudioManager already instantiated. Use get_instance()")

        AudioManager._instance = self

        # Configuration
        self.config_manager = config_manager
        self.audio_classes_config = {}
        self.audio_library_config = {}
        self.audio_devices_config = {}

        # Load configurations
        self._load_configs()

        # Core components
        base_path = self.audio_classes_config.get('base_path', './sounds/')
        self.sound_library = SoundLibrary(base_path)

        audio_device = self.audio_devices_config.get('audio_device', 'default')
        haptic_device = self.audio_devices_config.get('haptic_device')
        self.audio_player = AudioPlayer(audio_device, haptic_device)

        # Voice queue
        voice_config = self.audio_classes_config['classes'].get('voice', {})
        post_pause = voice_config.get('post_pause', 0.3)
        dedupe     = voice_config.get('dedupe', False)
        self.voice_queue = VoiceQueue(post_pause, dedupe=dedupe)

        # Watched audio instances
        self.watched_audio: Dict[str, WatchedAudio] = {}
        self.watched_audio_objects: Dict[str, Any] = {}  # References to watcher objects

        # Watch condition instances (for alert triggers)
        self.watch_conditions: Dict[str, WatchCondition] = {}
        self._init_watch_conditions()

        # Playing sounds tracking
        self.looping_sounds: Dict[str, int] = {}  # event_name -> sound_id
        self.event_sounds: Dict[str, int] = {}  # event_name -> sound_id (for replace mode)
        self._shuffle_state: Dict[str, dict] = {}  # event_name -> shuffle playlist state
        # Per-class state:
        #   class_max_volumes  - the [0..1] ceiling configured per class in
        #     audio_classes.json under "max_volume". Acts as the actual audible
        #     scale for the class; everything else (operator knobs, set_class_volume)
        #     is a fraction of this.
        #   class_volumes      - the live class volume in the mix, in [0..max].
        #     Initialised at the class's max (equivalent to a fresh-up
        #     "knob at 1.0"); set_class_volume(class, x) maps xin[0..1] to
        #     x x max for the class.
        self.class_volumes: Dict[str, float] = {}
        self.class_max_volumes: Dict[str, float] = {}
        self.master_audio_volume = 1.0
        self.master_haptic_volume = 1.0

        # Reset state
        self.reset_start_time: Optional[float] = None
        self.reset_fadeout_time = self.audio_classes_config.get('reset_fadeout_time', 5.0)
        self.resetting = False
        self.reset_immediate = False

        # Initialize per-class ceilings and live volumes. Each class starts at
        # its full max (equivalent to a "knob at 1.0" startup); set_class_volume
        # scales subsequent operator inputs against the configured ceiling.
        for class_name, class_config in self.audio_classes_config['classes'].items():
            mx = float(class_config.get('max_volume', 1.0))
            mx = max(0.0, min(1.0, mx))
            self.class_max_volumes[class_name] = mx
            self.class_volumes[class_name]     = mx

        # Background thread and event queue (following DisplayManager pattern)
        self.event_queue: List[tuple] = []
        self.event_lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # Initialize audio player
        self.audio_player.initialize()

    @classmethod
    def get_instance(cls):
        """Get the singleton AudioManager instance"""
        if cls._instance is None:
            raise RuntimeError("AudioManager not initialized")
        return cls._instance

    @classmethod
    def spawn(cls, project_root=None, config_dir="configs"):
        """Run the audio engine in its own OS process and return a handle.

        The child process owns the real AudioManager (and PyAudio) and runs the
        mix/update loop on its own GIL, so heavy work in this process cannot
        starve audio buffer serialization (no clicks or underruns under load).
        The returned handle is installed as the singleton, so the generated
        Voice / Event / Ambient / Music / Ui / Alerts proxies forward every call
        to the child transparently. Use it exactly like an in-process
        AudioManager::

            audio = AudioManager.spawn(project_root)
            ...
            audio.update(dt)   # each tick (ships watched values to the child)
            audio.shutdown()   # at exit (stops the child and reaps it)

        Args:
            project_root: directory holding ``configs/`` and ``sounds/``
                (default: current working directory).
            config_dir: config directory name under ``project_root``
                (default ``"configs"``).

        Returns:
            An ``AudioClient`` handle exposing ``update(dt)`` and ``shutdown()``.
        """
        import subprocess
        import sys
        from pathlib import Path
        from ._ipc.client import AudioClient

        root = Path(project_root) if project_root is not None else Path.cwd()
        cmd = [
            sys.executable, "-m", "enigma.audio.daemon",
            "--project-root", str(root),
            "--config-dir", str(config_dir),
        ]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        # project_root passed so AudioClient can locate audio_library.json for
        # parent-side watch_condition evaluation. Daemon-side evaluation of
        # watch_condition entries is inert because the daemon process reads
        # generated.devices from its OWN (never-updated) memory space; the
        # AudioClient evaluates them against the parent's live specs and
        # dispatches play_event() over the wire on trigger.
        client = AudioClient(proc.stdin, proc, project_root=root)
        cls._instance = client
        return client

    def _load_configs(self):
        """Load audio configuration files"""
        try:
            # Load audio classes config
            classes_path = Path('configs/audio_classes.json')
            if classes_path.exists():
                with open(classes_path, 'r') as f:
                    self.audio_classes_config = json.load(f)
            else:
                print_warning("[Audio] WARNING: audio_classes.json not found")

            # Load audio library config
            library_path = Path('configs/audio_library.json')
            if library_path.exists():
                with open(library_path, 'r') as f:
                    self.audio_library_config = json.load(f)
            else:
                print_warning("[Audio] WARNING: audio_library.json not found")

            # Load audio devices config
            devices_path = Path('configs/audio_devices.json')
            if devices_path.exists():
                with open(devices_path, 'r') as f:
                    self.audio_devices_config = json.load(f)
            else:
                print_warning("[Audio] WARNING: audio_devices.json not found")

        except Exception as e:
            print_error(f"[enigma] [Audio] ERROR loading configs: {e}")

    def _init_watch_conditions(self):
        """Initialize watch conditions from audio library config"""
        events = self.audio_library_config.get('events', {})
        for event_name, event_config in events.items():
            if 'watch_condition' in event_config:
                watch_spec = event_config.get('watch_spec')
                watch_condition = event_config.get('watch_condition')

                if watch_spec and watch_condition:
                    try:
                        condition = WatchCondition(event_name, watch_spec, watch_condition)
                        self.watch_conditions[event_name] = condition
                    except Exception as e:
                        print_error(f"[enigma] [Audio] ERROR: Failed to create watch condition for '{event_name}': {e}")

    def _get_spec_value(self, spec_string: str) -> Optional[float]:
        """
        Get current value from a spec string like 'FtlSpec.PortFeedPressure'

        Args:
            spec_string: Dot-separated spec path

        Returns:
            Current value or None if not found
        """
        try:
            # Import generated.devices to access specs
            import generated.devices as devices

            # Parse spec string (e.g., "FtlSpec.PortFeedPressure")
            parts = spec_string.split('.')
            if len(parts) != 2:
                return None

            spec_name, attr_name = parts

            # Get the spec class
            if not hasattr(devices, spec_name):
                return None

            spec = getattr(devices, spec_name)

            # Get the attribute value
            if not hasattr(spec, attr_name):
                return None

            value = getattr(spec, attr_name)

            # Convert to float if possible
            return float(value)

        except Exception:
            return None

    def play_event(self, event_name: str):
        """
        Play a simple audio event

        Args:
            event_name: Name of the event from audio_library.json
        """
        with self.event_lock:
            self.event_queue.append(('play_event', event_name))

    def start_loop(self, event_name: str):
        """
        Start a looping sound

        Args:
            event_name: Name of the looping event
        """
        with self.event_lock:
            self.event_queue.append(('start_loop', event_name))

    def stop_loop(self, event_name: str):
        """
        Stop a looping sound

        Args:
            event_name: Name of the looping event
        """
        with self.event_lock:
            self.event_queue.append(('stop_loop', event_name))

    def register_watched_audio(self, event_name: str, watcher_object: Any):
        """
        Register a watched audio source

        Args:
            event_name: Name of the watched audio event
            watcher_object: Object that has get_current_value() method
        """
        event_config = self.audio_library_config['events'].get(event_name)
        if not event_config:
            print_warning(f"[Audio] WARNING: Watched audio event '{event_name}' not found in config")
            return

        class_config = self.audio_classes_config['classes'].get(event_config['class'], {})
        crossfade_time = class_config.get('crossfade_time', 1.0)

        watched = WatchedAudio(event_name, event_config, crossfade_time)
        self.watched_audio[event_name] = watched
        self.watched_audio_objects[event_name] = watcher_object

        print(f"[enigma] [Audio] Registered watched audio: {event_name}")

    def start_watched_audio(self, event_name: str):
        """Start a watched audio source"""
        if event_name in self.watched_audio:
            self.watched_audio[event_name].start()

    def pause_watched_audio(self, event_name: str):
        """Pause a watched audio source"""
        if event_name in self.watched_audio:
            self.watched_audio[event_name].pause()

    def stop_watched_audio(self, event_name: str):
        """Stop a watched audio source"""
        if event_name in self.watched_audio:
            self.watched_audio[event_name].stop()

    def reset_watched_audio(self, event_name: str, now: bool = False):
        """Reset a watched audio source"""
        if event_name in self.watched_audio:
            self.watched_audio[event_name].reset(now)

    def watched_audio_ready(self, event_name: str) -> bool:
        """Check if watched audio is ready"""
        if event_name in self.watched_audio:
            return not self.watched_audio[event_name].is_playing()
        return True

    def set_class_volume(self, class_name: str, volume: float):
        """Set the live volume for an audio class.

        `volume` is in [0..1] from the caller's perspective (operator-side
        thinks of "max volume = 1.0"). It's scaled by the class's configured
        `max_volume` ceiling (from audio_classes.json) so the effective mix
        gain is `volume x max_volume`. This makes the config-level
        `max_volume` an actual ceiling: an operator pushing the knob to 1.0
        cannot exceed the class's configured cap. Pre-rename behaviour
        (`default_volume` as initializer only) is gone; callers don't need
        to know the ceiling.
        """
        v   = max(0.0, min(1.0, volume))
        mx  = self.class_max_volumes.get(class_name, 1.0)
        self.class_volumes[class_name] = v * mx

    def set_master_audio_volume(self, volume: float):
        """Set master audio output volume"""
        self.master_audio_volume = max(0.0, min(1.0, volume))

    def set_master_haptic_volume(self, volume: float):
        """Set master haptic output volume"""
        self.master_haptic_volume = max(0.0, min(1.0, volume))

    def reset_class(self, class_name: str, now: bool = False):
        """Reset all sounds in a class"""
        with self.event_lock:
            self.event_queue.append(('reset_class', class_name, now))

    def clear_pending_class(self, class_name: str) -> int:
        """Drop queued (not-yet-playing) voice requests in the given audio
        class. The currently-playing voice is untouched and runs to its
        natural end. Useful at game-over (or similar pivots) when a stack of
        in-flight status callouts should not keep narrating after the game
        state has changed."""
        def _lookup(event_name: str) -> Optional[str]:
            cfg = self.audio_library_config['events'].get(event_name, {})
            return cfg.get('class')
        return self.voice_queue.clear_pending_in_class(class_name, _lookup)

    def _reset_class_impl(self, class_name: str, now: bool = False):
        """Implementation of reset_class - stops all sounds in a class"""
        fade_out = 0.0 if now else 1.0

        # Stop all looping sounds of this class
        loops_to_remove = []
        for event_name, sound_id in self.looping_sounds.items():
            event_config = self.audio_library_config['events'].get(event_name, {})
            if event_config.get('class') == class_name:
                self.audio_player.stop(sound_id, fade_out=fade_out)
                loops_to_remove.append(event_name)

        for event_name in loops_to_remove:
            del self.looping_sounds[event_name]
            self._shuffle_state.pop(event_name, None)

        # Reset watched audio in this class: clear stale active_sound so they re-evaluate
        # cleanly on the next update cycle rather than thinking they're still playing.
        for event_name, watched in self.watched_audio.items():
            event_config = self.audio_library_config['events'].get(event_name, {})
            if event_config.get('class') == class_name:
                watched.stop()   # clears _active_sound, _crossfading_sound
                watched.start()  # immediately re-enable so updates keep running
                self.looping_sounds.pop(event_name, None)

        # Note: We can't easily stop simple events since we don't track them by class
        # They will finish playing naturally

    def reset_all(self, now: bool = False):
        """Reset all audio"""
        self.resetting = True
        self.reset_immediate = now
        self.reset_start_time = time.time()

        if now:
            # Immediate stop - explicitly pass 0.0 fade time
            self.audio_player.stop_all(fade_out=0.0)
            self.looping_sounds.clear()
            self.event_sounds.clear()
            self._shuffle_state.clear()
            self.voice_queue.reset(now=True)
            for watched in self.watched_audio.values():
                watched.reset(now=True)
            for condition in self.watch_conditions.values():
                condition.reset()
            # Don't set resetting=False yet - let the update loop handle it
            # This prevents watched audio from immediately restarting
        else:
            # Graceful fadeout - stop all looping sounds with fadeout
            fade_time = self.reset_fadeout_time
            for sound_id in self.looping_sounds.values():
                self.audio_player.stop(sound_id, fade_out=fade_time)
            # Clear tracking so they don't get restarted
            self.looping_sounds.clear()
            self.event_sounds.clear()
            self._shuffle_state.clear()
            # Reset voice queue and watched audio with fadeout
            self.voice_queue.reset(now=False)
            for watched in self.watched_audio.values():
                watched.reset(now=False)
            for condition in self.watch_conditions.values():
                condition.reset()

    def all_ready(self) -> bool:
        """True once the audio subsystem has finished resetting."""
        return not self.resetting

    def class_ready(self, class_name: str) -> bool:
        """Check if a class is ready (not implemented fully - simplified)"""
        return not self.resetting

    def update(self, dt: float = 0.016):
        """
        Update audio manager (called from main loop)

        Args:
            dt: Delta time since last update
        """
        # Process event queue
        with self.event_lock:
            events = self.event_queue[:]
            self.event_queue.clear()

        for event in events:
            self._process_event(event)

        # Update watched audio (only if not resetting)
        if not self.resetting:
            for event_name, watched in self.watched_audio.items():
                watcher = self.watched_audio_objects.get(event_name)
                if watcher:
                    current_value = watcher.get_current_value()
                    result = watched.update(current_value, self.sound_library, dt)
                    self._handle_watched_result(event_name, result)

        # Update watch conditions (only if not resetting)
        if not self.resetting:
            for event_name, condition in self.watch_conditions.items():
                try:
                    current_value = self._get_spec_value(condition.watch_spec)
                    if current_value is not None:
                        triggered = condition.update(current_value)
                        if triggered:
                            # Play the event
                            self.play_event(event_name)
                except Exception as e:
                    # Silently ignore - spec might not be ready yet
                    pass

        # Advance shuffle playlists when the current track finishes
        if not self.resetting:
            for event_name in list(self._shuffle_state.keys()):
                sound_id = self.looping_sounds.get(event_name)
                if sound_id is not None and not self.audio_player.is_playing(sound_id):
                    self._advance_shuffle(event_name)

        # Update voice queue
        next_voice = self.voice_queue.get_next()
        if next_voice:
            self._play_voice(next_voice)

        # Handle reset completion
        if self.resetting:
            if self.reset_immediate:
                # Immediate reset - done after one frame
                self.resetting = False
            else:
                # Graceful fadeout
                elapsed = time.time() - self.reset_start_time
                if elapsed >= self.reset_fadeout_time:
                    # Fadeout complete, mark as done
                    self.resetting = False

    def _process_event(self, event: tuple):
        """Process a queued event"""
        event_type = event[0]

        if event_type == 'play_event':
            event_name = event[1]
            self._play_simple_event(event_name)

        elif event_type == 'start_loop':
            event_name = event[1]
            self._start_loop_event(event_name)

        elif event_type == 'stop_loop':
            event_name = event[1]
            self._stop_loop_event(event_name)

        elif event_type == 'reset_class':
            class_name = event[1]
            now = event[2]
            self._reset_class_impl(class_name, now)

    def _play_simple_event(self, event_name: str):
        """Play a simple (non-looping, non-watched) event"""
        event_config = self.audio_library_config['events'].get(event_name)
        if not event_config:
            print_warning(f"[Audio] WARNING: Event '{event_name}' not found")
            return

        audio_path = event_config.get('audio')
        event_volume = event_config.get('volume', 1.0)
        priority = event_config.get('priority')
        fade_in_time = event_config.get('fade_in', 0.0)  # Default: no fade
        playback_mode = event_config.get('playback_mode', 'stack')  # Default: stack

        # Get random volume if range specified
        if isinstance(event_volume, list):
            event_volume = random.uniform(event_volume[0], event_volume[1])

        # Load audio files (haptic auto-discovered from parent/haptic/same_name.*)
        audio_file, haptic_file = self.sound_library.get_audio_with_haptic(audio_path) if audio_path else (None, None)

        if not audio_file:
            return

        audio_data = self.sound_library.load_audio_file(audio_file)
        haptic_data = self.sound_library.load_audio_file(haptic_file) if haptic_file else None

        # Calculate final volume
        class_name = event_config.get('class', 'event')
        class_volume = self.class_volumes.get(class_name, 1.0)
        final_audio_volume = event_volume * class_volume * self.master_audio_volume
        final_haptic_volume = (event_volume if _HAPTIC_SCALES_WITH_EVENT_VOLUME else 1.0) * self.master_haptic_volume

        # Voice events use priority queue
        if priority is not None:
            if audio_data:
                # Adjust audio data volume for haptic
                audio_for_voice = (audio_data[0] * final_audio_volume, audio_data[1])
                haptic_for_voice = None
                if haptic_data:
                    haptic_for_voice = (haptic_data[0] * final_haptic_volume, haptic_data[1])

                self.voice_queue.request(event_name, priority, audio_for_voice, haptic_for_voice)
        else:
            # Handle playback mode - replace stops previous instance
            if playback_mode == 'replace' and event_name in self.event_sounds:
                self.audio_player.stop(self.event_sounds[event_name], fade_out=0.0)

            # Regular event - play immediately with dynamic volume callback
            if audio_data:
                # Create volume callback for dynamic volume updates
                def volume_callback():
                    current_class_volume = self.class_volumes.get(class_name, 1.0)
                    audio_vol = event_volume * current_class_volume * self.master_audio_volume
                    haptic_vol = (event_volume if _HAPTIC_SCALES_WITH_EVENT_VOLUME else 1.0) * self.master_haptic_volume
                    return (audio_vol, haptic_vol)

                sound_id = self.audio_player.play(audio_data, haptic_data, event_volume,
                                      loops=False, fade_in=fade_in_time,
                                      volume_callback=volume_callback)

                # Track sound ID for replace mode
                if playback_mode == 'replace':
                    self.event_sounds[event_name] = sound_id

    def _start_loop_event(self, event_name: str):
        """Start a looping event"""
        event_config = self.audio_library_config['events'].get(event_name)
        if not event_config:
            return

        shuffle = event_config.get('shuffle', False)
        loops   = event_config.get('loops',   False)

        if shuffle and loops:
            print_error(f"[enigma] [Audio] ERROR: Event '{event_name}' has both 'shuffle' and 'loops' set - "
                        f"these are incompatible. Use 'shuffle' alone for playlist behaviour.")
            return

        class_name = event_config.get('class', 'music')
        class_config = self.audio_classes_config['classes'].get(class_name, {})

        # Check if this class only allows one sound at a time
        max_simultaneous = class_config.get('max_simultaneous', -1)
        crossfade_time = class_config.get('crossfade_time', 1.0)

        if max_simultaneous == 1:
            # Stop ALL other looping sounds in this class (for crossfade)
            events_to_stop = []
            for loop_event_name, sound_id in self.looping_sounds.items():
                loop_config = self.audio_library_config['events'].get(loop_event_name)
                if loop_config and loop_config.get('class') == class_name:
                    events_to_stop.append((loop_event_name, sound_id))
            for loop_event_name, sound_id in events_to_stop:
                self.audio_player.stop(sound_id, fade_out=crossfade_time)
                del self.looping_sounds[loop_event_name]
                self._shuffle_state.pop(loop_event_name, None)
        else:
            # Just stop this specific event if it's already playing
            if event_name in self.looping_sounds:
                self.audio_player.stop(self.looping_sounds[event_name], fade_out=crossfade_time)
                del self.looping_sounds[event_name]
                self._shuffle_state.pop(event_name, None)

        fade_in_time = event_config.get('fade_in', crossfade_time if max_simultaneous == 1 else 0.0)

        if shuffle:
            self._start_shuffle_event(event_name, event_config, class_name, fade_in_time)
            return

        audio_path = event_config.get('audio')
        event_volume = event_config.get('volume', 1.0)

        # Load audio files (haptic auto-discovered from parent/haptic/same_name.*)
        audio_file, haptic_file = self.sound_library.get_audio_with_haptic(audio_path) if audio_path else (None, None)

        if not audio_file:
            return

        audio_data = self.sound_library.load_audio_file(audio_file)
        haptic_data = self.sound_library.load_audio_file(haptic_file) if haptic_file else None

        if audio_data:
            # Create volume callback for dynamic volume updates
            def volume_callback():
                current_class_volume = self.class_volumes.get(class_name, 1.0)
                audio_vol = event_volume * current_class_volume * self.master_audio_volume
                haptic_vol = (event_volume if _HAPTIC_SCALES_WITH_EVENT_VOLUME else 1.0) * self.master_haptic_volume
                return (audio_vol, haptic_vol)

            sound_id = self.audio_player.play(audio_data, haptic_data, event_volume,
                                               loops=True, fade_in=fade_in_time,
                                               volume_callback=volume_callback)
            self.looping_sounds[event_name] = sound_id

    def _start_shuffle_event(self, event_name: str, event_config: dict,
                             class_name: str, fade_in_time: float):
        """Build a shuffled playlist and start the first track."""
        audio_path = event_config.get('audio')
        if not audio_path:
            return

        all_files = self.sound_library.get_all_files(audio_path)
        if not all_files:
            return

        playlist = list(all_files)
        random.shuffle(playlist)

        self._shuffle_state[event_name] = {
            'remaining':   playlist[1:],
            'all_files':   all_files,
            'event_config': event_config,
            'class_name':  class_name,
            'last_played': playlist[0],
        }

        self._play_shuffle_track(event_name, playlist[0],
                                 event_config.get('volume', 1.0),
                                 fade_in_time, class_name)

    def _play_shuffle_track(self, event_name: str, file_path,
                            volume: float, fade_in: float, class_name: str):
        """Load and start one non-looping track in a shuffle sequence."""
        audio_data = self.sound_library.load_audio_file(file_path)
        if not audio_data:
            return

        # Auto-discover paired haptic file (same convention as get_audio_with_haptic)
        haptic_data = None
        haptic_dir = file_path.parent / "haptic"
        if haptic_dir.is_dir():
            for ext in ['.wav', '.ogg', '.flac', '.mp3']:
                candidate = haptic_dir / (file_path.stem + ext)
                if candidate.is_file():
                    haptic_data = self.sound_library.load_audio_file(candidate)
                    break

        def volume_callback():
            current_class_volume = self.class_volumes.get(class_name, 1.0)
            audio_vol = volume * current_class_volume * self.master_audio_volume
            haptic_vol = (volume if _HAPTIC_SCALES_WITH_EVENT_VOLUME else 1.0) * self.master_haptic_volume
            return (audio_vol, haptic_vol)

        sound_id = self.audio_player.play(audio_data, haptic_data, volume,
                                          loops=False, fade_in=fade_in,
                                          volume_callback=volume_callback)
        self.looping_sounds[event_name] = sound_id

    def _advance_shuffle(self, event_name: str):
        """Advance to the next track; reshuffles the full set when the playlist is exhausted."""
        state = self._shuffle_state.get(event_name)
        if not state:
            return

        if not state['remaining']:
            playlist = list(state['all_files'])
            random.shuffle(playlist)
            # Avoid the same track back-to-back at the cycle boundary: if the
            # freshly-shuffled first pick matches the last track played, rotate
            # it to the end (only possible when there are 2+ tracks).
            if len(playlist) > 1 and playlist[0] == state.get('last_played'):
                playlist.append(playlist.pop(0))
            state['remaining'] = playlist

        next_file = state['remaining'].pop(0)
        state['last_played'] = next_file
        event_config = state['event_config']
        self._play_shuffle_track(
            event_name, next_file,
            event_config.get('volume', 1.0),
            event_config.get('fade_in', 1.0),
            state['class_name'],
        )

    def _stop_loop_event(self, event_name: str):
        """Stop a looping event"""
        if event_name in self.looping_sounds:
            self.audio_player.stop(self.looping_sounds[event_name], fade_out=1.0)
            del self.looping_sounds[event_name]
        self._shuffle_state.pop(event_name, None)

    def _handle_watched_result(self, event_name: str, result: Dict[str, Any]):
        """Handle result from watched audio update"""
        action = result.get('action')

        if action == 'crossfade':
            new_sound = result['new_sound']
            old_sound = result.get('old_sound')
            duration = result['duration']

            # Stop old sound with fadeout
            if old_sound and event_name in self.looping_sounds:
                self.audio_player.stop(self.looping_sounds[event_name], fade_out=duration)

            # Start new sound with fade in and dynamic volume callback
            event_config = self.audio_library_config['events'].get(event_name)
            class_name = event_config.get('class', 'ambient')

            # Create volume callback that reads the smoothly ramped current_volume
            def volume_callback():
                # Get the current volume from the watched audio's active sound
                watched = self.watched_audio.get(event_name)
                if watched and watched._active_sound:
                    current_vol = watched._active_sound.current_volume
                else:
                    current_vol = new_sound.current_volume  # Fallback

                current_class_volume = self.class_volumes.get(class_name, 1.0)
                audio_vol = current_vol * current_class_volume * self.master_audio_volume
                haptic_vol = current_vol * self.master_haptic_volume
                return (audio_vol, haptic_vol)

            sound_id = self.audio_player.play(
                new_sound.audio_data,
                new_sound.haptic_data,
                new_sound.target_volume,
                loops=True,
                fade_in=duration,
                volume_callback=volume_callback
            )
            self.looping_sounds[event_name] = sound_id

        elif action == 'update_volume':
            # Volume is now updated automatically via callbacks, but we still
            # need to update the target volume in the watched audio
            pass  # Volume callback handles this dynamically

        elif action == 'fadeout':
            # Watched value fell outside every threshold. WatchedAudio's
            # _start_fadeout sets fading_out=True but never actually clears
            # _active_sound, so on re-entry the library takes the "same
            # threshold, just update volume" path and never emits a fresh
            # crossfade - meaning the audible loop is gone (we stop it here)
            # AND won't come back. Clearing _active_sound forces the next
            # in-range tick to go through the new-sound branch, which emits
            # 'crossfade' and we spin a new audio_player loop. _shuffle_state
            # and looping_sounds bookkeeping both get cleaned up.
            watched = self.watched_audio.get(event_name)
            if event_name in self.looping_sounds:
                fade_dur = watched.crossfade_time if watched is not None else 0.5
                self.audio_player.stop(self.looping_sounds[event_name],
                                       fade_out=fade_dur)
                del self.looping_sounds[event_name]
                self._shuffle_state.pop(event_name, None)
            if watched is not None:
                watched._active_sound = None
                watched._crossfading_sound = None

        elif action == 'stop':
            # WatchedAudio.stop() was called from the outside (or the source
            # entered a permanently-stopped state). Hard-stop the loop with
            # no fade and forget about it; .start() will resume the watcher
            # and the next in-range tick must produce a fresh crossfade -
            # clearing _active_sound is what makes that branch fire.
            watched = self.watched_audio.get(event_name)
            if event_name in self.looping_sounds:
                self.audio_player.stop(self.looping_sounds[event_name],
                                       fade_out=0.0)
                del self.looping_sounds[event_name]
                self._shuffle_state.pop(event_name, None)
            if watched is not None:
                watched._active_sound = None
                watched._crossfading_sound = None

        elif action == 'pause':
            # No native pause in audio_player; cleanest interpretation is
            # the same as stop (drop the loop with a quick fade). On resume
            # the next in-range tick has to re-emit 'crossfade', which means
            # _active_sound must be cleared here too.
            watched = self.watched_audio.get(event_name)
            if event_name in self.looping_sounds:
                self.audio_player.stop(self.looping_sounds[event_name],
                                       fade_out=0.1)
                del self.looping_sounds[event_name]
                self._shuffle_state.pop(event_name, None)
            if watched is not None:
                watched._active_sound = None
                watched._crossfading_sound = None

    def _play_voice(self, voice_request):
        """Play a voice callout"""
        audio_data, samplerate = voice_request.audio_data
        duration = len(audio_data) / samplerate

        # Play the voice
        self.audio_player.play(voice_request.audio_data, voice_request.haptic_data, 1.0)

        # Mark as playing in queue
        self.voice_queue.mark_playing(voice_request, duration)

    def shutdown(self):
        """Shutdown audio manager"""
        self.audio_player.shutdown()
        print("[enigma] [Audio] AudioManager shutdown")
