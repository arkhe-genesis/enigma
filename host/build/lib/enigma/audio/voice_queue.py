# SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
# SPDX-License-Identifier: MIT

"""
Voice Queue - Priority-based voice callout management

Handles voice callouts with smart priority-based queuing:
- Only one voice callout plays at a time
- Configurable post-pause between callouts
- Priority-based dropping: new requests < max(playing, queued) priority are dropped
- Only queues items at the highest priority level
- Optional adjacent-play dedupe: incoming request is dropped if it matches the
  tail of the queue (or the currently-playing item when the queue is empty)
"""

import time
from typing import Optional, List, Callable
from dataclasses import dataclass


@dataclass
class VoiceRequest:
    """Represents a voice callout request"""
    event_name: str
    priority: int
    audio_data: tuple  # (data, samplerate)
    haptic_data: Optional[tuple] = None  # (data, samplerate) for haptic channel


class VoiceQueue:
    """Manages priority-based voice callout queue"""

    def __init__(self, post_pause: float = 0.3, dedupe: bool = False):
        """
        Initialize voice queue

        Args:
            post_pause: Silence duration (seconds) after each voice clip finishes
            dedupe: If True, incoming requests whose event_name matches the tail
                    of the queue (or the currently-playing item when the queue
                    is empty) are dropped. Prevents rapid-fire duplicates from
                    stacking up in a queue that would then narrate the same
                    line 3-5 times back-to-back.
        """
        self.post_pause = post_pause
        self.dedupe = dedupe
        self._queue: List[VoiceRequest] = []
        self._currently_playing: Optional[VoiceRequest] = None
        self._playback_end_time: Optional[float] = None
        self._pause_end_time: Optional[float] = None

    def request(self, event_name: str, priority: int, audio_data: tuple,
                haptic_data: Optional[tuple] = None) -> bool:
        """
        Request a voice callout to be played

        Args:
            event_name: Name of the voice event
            priority: Priority level (higher = more important)
            audio_data: Tuple of (audio_array, samplerate)
            haptic_data: Optional haptic audio data

        Returns:
            True if request was queued/played, False if dropped
        """
        request = VoiceRequest(event_name, priority, audio_data, haptic_data)

        # Adjacent-play dedupe: drop the request if it would immediately follow
        # a copy of itself. "Adjacent" = tail of the queue when non-empty,
        # else the currently-playing item. Does not stop legitimate repeats
        # separated by other callouts (only cancels immediate duplication).
        if self.dedupe:
            adjacent = self._queue[-1] if self._queue else self._currently_playing
            if adjacent is not None and adjacent.event_name == event_name:
                return False

        # Determine current maximum priority (consider both playing and queued)
        max_priority = 0
        if self._currently_playing:
            max_priority = self._currently_playing.priority
        if self._queue:
            max_priority = max(max_priority, max(req.priority for req in self._queue))

        # If new request has lower priority, drop it
        if priority < max_priority:
            return False

        # If new request has higher priority, clear queue
        if priority > max_priority:
            self._queue.clear()

        # Queue the request (same or higher priority)
        self._queue.append(request)
        return True

    def get_next(self) -> Optional[VoiceRequest]:
        """
        Get the next voice request to play (if ready)

        Returns:
            Next VoiceRequest to play, or None if not ready
        """
        current_time = time.time()

        # If currently playing, check if it's done
        if self._currently_playing:
            # Still playing audio
            if self._playback_end_time and current_time < self._playback_end_time:
                return None
            # In post-pause period
            if self._pause_end_time and current_time < self._pause_end_time:
                return None
            # Done with pause, clear current
            self._currently_playing = None
            self._playback_end_time = None
            self._pause_end_time = None

        # Return next item from queue
        if self._queue:
            return self._queue.pop(0)

        return None

    def mark_playing(self, request: VoiceRequest, duration: float):
        """
        Mark a request as currently playing

        Args:
            request: The voice request now playing
            duration: Duration of the audio in seconds
        """
        self._currently_playing = request
        current_time = time.time()
        self._playback_end_time = current_time + duration
        self._pause_end_time = current_time + duration + self.post_pause

    def is_playing(self) -> bool:
        """Check if a voice callout is currently playing or in post-pause"""
        if not self._currently_playing:
            return False

        current_time = time.time()
        return (self._pause_end_time is not None and
                current_time < self._pause_end_time)

    def reset(self, now: bool = False):
        """
        Reset the voice queue

        Args:
            now: If True, immediately clear everything. If False, let current finish.
        """
        self._queue.clear()
        if now:
            self._currently_playing = None
            self._playback_end_time = None
            self._pause_end_time = None

    def clear_pending_in_class(self, class_name: str,
                                class_lookup: Callable[[str], Optional[str]]) -> int:
        """
        Drop queued (not-yet-playing) requests whose audio class matches
        class_name. The currently-playing voice is untouched and will finish
        naturally. Used at game-over and similar pivots when a stack of
        already-queued status callouts should not keep narrating after the
        game state has moved on.

        Args:
            class_name: Audio class to filter on (e.g. 'voice').
            class_lookup: Callable mapping an event_name to its class string;
                          supplied by AudioManager so VoiceQueue stays
                          decoupled from the library config.

        Returns:
            Number of pending requests removed from the queue.
        """
        kept: List[VoiceRequest] = []
        removed = 0
        for req in self._queue:
            if class_lookup(req.event_name) == class_name:
                removed += 1
            else:
                kept.append(req)
        self._queue = kept
        return removed

    def ready(self) -> bool:
        """Check if voice queue is ready (nothing playing, queue empty)"""
        return not self.is_playing() and len(self._queue) == 0
