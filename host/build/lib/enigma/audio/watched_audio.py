# SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
# SPDX-License-Identifier: MIT

"""
Watched Audio - Threshold tracking and crossfade management

Handles audio that dynamically responds to changing values:
- Monitors watched values (e.g., engine throttle, reactor power)
- Switches audio based on threshold value_ranges
- Crossfades between different loops when crossing thresholds
- Interpolates volume within value_ranges using volume_range mapping
"""

import time
from typing import Optional, List, Dict, Any
from dataclasses import dataclass


@dataclass
class Threshold:
    """Represents a threshold configuration"""
    range_min: float
    range_max: float
    audio_path: str
    volume_min: float
    volume_max: float


@dataclass
class ActiveSound:
    """Represents a currently playing sound in a threshold"""
    threshold: Threshold
    audio_data: tuple  # (data, samplerate)
    haptic_data: Optional[tuple]
    target_volume: float
    current_volume: float
    fading_out: bool = False
    fade_start_time: Optional[float] = None
    fade_duration: float = 0.0


class WatchedAudio:
    """Manages a single watched audio source with threshold-based behavior"""

    def __init__(self, event_name: str, config: Dict[str, Any],
                 crossfade_time: float = 1.0):
        """
        Initialize watched audio

        Args:
            event_name: Name of this audio event
            config: Configuration dict with 'thresholds' list
            crossfade_time: Default crossfade duration in seconds
        """
        self.event_name = event_name
        self.crossfade_time = config.get('crossfade_time', crossfade_time)
        self.watched_value_getter = None  # Set by manager
        self._active_sound: Optional[ActiveSound] = None
        self._crossfading_sound: Optional[ActiveSound] = None
        self._paused = False
        self._stopped = False

        # Parse thresholds from config
        self.thresholds: List[Threshold] = []
        for t in config.get('thresholds', []):
            range_vals = t['value_range']

            # Handle volume - can be single value, range, or use volume_range
            volume = t.get('volume')
            volume_range = t.get('volume_range')

            if volume_range:
                # Explicit volume_range takes precedence
                vol_min, vol_max = volume_range
            elif isinstance(volume, list):
                # volume as a list (legacy support)
                vol_min, vol_max = volume
            elif volume is not None:
                # Single volume value
                vol_min = vol_max = volume
            else:
                # Default to full volume
                vol_min = vol_max = 1.0

            self.thresholds.append(Threshold(
                range_min=range_vals[0],
                range_max=range_vals[1],
                audio_path=t.get('audio'),
                volume_min=vol_min,
                volume_max=vol_max
            ))

    def update(self, current_value: float, sound_library, dt: float) -> Dict[str, Any]:
        """
        Update watched audio based on current value

        Args:
            current_value: Current value of the watched parameter
            sound_library: SoundLibrary instance for loading files
            dt: Delta time since last update

        Returns:
            Dict with playback instructions for audio player
        """
        if self._stopped:
            return {'action': 'stop'}

        if self._paused:
            return {'action': 'pause'}

        # Find which threshold we're in
        target_threshold = self._find_threshold(current_value)

        if target_threshold is None:
            # Value is outside all thresholds, fade out
            if self._active_sound:
                self._start_fadeout(self._active_sound)
            return {'action': 'fadeout'}

        # Calculate target volume based on position in threshold
        target_volume = self._calculate_volume(current_value, target_threshold)

        # Check if we need to switch sounds (crossed threshold)
        if self._active_sound is None or self._active_sound.threshold != target_threshold:
            # Need to switch to new sound (haptic auto-discovered from parent/haptic/same_name.*)
            audio_file, haptic_file = sound_library.get_audio_with_haptic(target_threshold.audio_path)

            if audio_file:
                audio_data = sound_library.load_audio_file(audio_file)
                haptic_data = sound_library.load_audio_file(haptic_file) if haptic_file else None

                if audio_data:
                    # Create new active sound
                    new_sound = ActiveSound(
                        threshold=target_threshold,
                        audio_data=audio_data,
                        haptic_data=haptic_data,
                        target_volume=target_volume,
                        current_volume=target_volume  # Start at target, audio_player handles fade-in
                    )

                    # Start crossfade
                    if self._active_sound:
                        self._start_fadeout(self._active_sound)
                        self._crossfading_sound = self._active_sound

                    self._active_sound = new_sound

                    return {
                        'action': 'crossfade',
                        'new_sound': new_sound,
                        'old_sound': self._crossfading_sound,
                        'duration': self.crossfade_time
                    }
        else:
            # Same threshold, just update volume
            self._active_sound.target_volume = target_volume

        # Update volume ramping for active sound
        if self._active_sound:
            self._update_volume_ramp(self._active_sound, dt)

        # Update crossfade volumes
        self._update_fadeout(dt)

        return {
            'action': 'update_volume',
            'active_sound': self._active_sound,
            'crossfading_sound': self._crossfading_sound
        }

    def _find_threshold(self, value: float) -> Optional[Threshold]:
        """Find which threshold contains the given value"""
        for threshold in self.thresholds:
            if threshold.range_min <= value <= threshold.range_max:
                return threshold
        return None

    def _calculate_volume(self, value: float, threshold: Threshold) -> float:
        """Calculate interpolated volume based on position in threshold"""
        range_size = threshold.range_max - threshold.range_min
        if range_size == 0:
            return threshold.volume_min

        # Calculate position in range (0.0 to 1.0)
        position = (value - threshold.range_min) / range_size
        position = max(0.0, min(1.0, position))

        # Interpolate volume
        return threshold.volume_min + (threshold.volume_max - threshold.volume_min) * position

    def _start_fadeout(self, sound: ActiveSound):
        """Start fading out a sound"""
        sound.fading_out = True
        sound.fade_start_time = time.time()
        sound.fade_duration = self.crossfade_time

    def _update_volume_ramp(self, sound: ActiveSound, dt: float):
        """Smoothly ramp current_volume towards target_volume"""
        if sound.current_volume == sound.target_volume:
            return

        # Ramp rate: change 0.5 volume per second (adjust for smoothness)
        ramp_rate = 0.5 * dt

        diff = sound.target_volume - sound.current_volume

        if abs(diff) <= ramp_rate:
            # Close enough, snap to target
            sound.current_volume = sound.target_volume
        else:
            # Ramp towards target
            if diff > 0:
                sound.current_volume += ramp_rate
            else:
                sound.current_volume -= ramp_rate

    def _update_fadeout(self, dt: float):
        """Update fadeout progress for crossfading sound"""
        if not self._crossfading_sound:
            return

        current_time = time.time()
        elapsed = current_time - self._crossfading_sound.fade_start_time

        if elapsed >= self._crossfading_sound.fade_duration:
            # Fadeout complete
            self._crossfading_sound = None
        else:
            # Update fade volume
            progress = elapsed / self._crossfading_sound.fade_duration
            self._crossfading_sound.current_volume *= (1.0 - progress)

    def pause(self):
        """Pause playback"""
        self._paused = True

    def stop(self):
        """Stop playback"""
        self._stopped = True
        self._active_sound = None
        self._crossfading_sound = None

    def start(self):
        """Start/resume playback"""
        self._paused = False
        self._stopped = False

    def reset(self, now: bool = False):
        """Reset to default state"""
        if now:
            self.stop()
        else:
            # Graceful fadeout handled by manager
            pass

    def is_playing(self) -> bool:
        """Check if actively playing"""
        return self._active_sound is not None and not self._stopped and not self._paused
