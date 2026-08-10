# SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
# SPDX-License-Identifier: MIT

"""
Audio Player - Multi-stream playback with dual output

Handles low-level audio playback using PyAudio:
- Multiple simultaneous streams per class
- Dual output support (main audio + haptic device)
- Volume mixing (event -> class -> master)
- Looping support
- Crossfading between sounds
"""

import numpy as np
import pyaudio
from typing import Optional, List
from dataclasses import dataclass
import threading

from enigma.colors import print_error


@dataclass
class PlayingSound:
    """Represents a currently playing sound"""
    sound_id: int
    audio_data: np.ndarray
    haptic_data: Optional[np.ndarray]
    samplerate: int
    volume: float  # Event-level volume
    loops: bool
    position: int = 0
    finished: bool = False
    fade_in_samples: int = 0
    fade_out_samples: int = 0
    current_fade_sample: int = 0
    # Dynamic volume calculation
    volume_callback: Optional[callable] = None  # Returns (audio_vol, haptic_vol)


class AudioPlayer:
    """Low-level audio playback engine using PyAudio"""

    def __init__(self, audio_device: str = "default", haptic_device: Optional[str] = None):
        """
        Initialize audio player

        Args:
            audio_device: Name of audio output device (or "default")
            haptic_device: Name of haptic output device (or None to disable)
        """
        self.audio_device = audio_device
        self.haptic_device = haptic_device

        # Active sounds
        self._playing_sounds: List[PlayingSound] = []
        self._next_sound_id = 0
        self._lock = threading.Lock()

        # PyAudio instance
        self._pyaudio: Optional[pyaudio.PyAudio] = None

        # Output streams
        self._audio_stream = None
        self._haptic_stream = None
        self._audio_device_index: Optional[int] = None
        self._haptic_device_index: Optional[int] = None
        self._sample_rate = 44100
        self._initialized = False

    def initialize(self):
        """Initialize output devices and streams"""
        if self._initialized:
            return

        try:
            self._pyaudio = pyaudio.PyAudio()

            # Find devices
            self._audio_device_index = self._find_device(self.audio_device)
            self._haptic_device_index = None
            if self.haptic_device:
                self._haptic_device_index = self._find_device(self.haptic_device)

            # Resolve outputs. "default" is allowed as an explicit opt-in to
            # the system default device; a configured-but-missing named
            # device is a hard failure on either stream. Falling back from
            # a missing named device to the system default risks routing
            # one stream onto the other's device - frying mids with sub-bass
            # content authored for a transducer, or sending bass-only
            # haptic material into headphones.
            if self._audio_device_index is not None:
                audio_info = self._pyaudio.get_device_info_by_index(self._audio_device_index)
            elif self.audio_device == "default":
                audio_info = self._pyaudio.get_default_output_device_info()
                self._audio_device_index = audio_info['index']
            else:
                print_error(f"[enigma] [Audio] ERROR: Configured audio device '{self.audio_device}' "
                            f"not found. Audio playback disabled (fallback intentionally removed).")
                self._initialized = True
                return

            if (self.haptic_device
                    and self._haptic_device_index is None
                    and self.haptic_device != "default"):
                print_error(f"[enigma] [Audio] ERROR: Configured haptic device '{self.haptic_device}' "
                            f"not found. Audio playback disabled (fallback intentionally removed).")
                self._initialized = True
                return

            self._sample_rate = int(audio_info['defaultSampleRate'])

            # Callback streams: CoreAudio pulls data exactly when the hardware
            # asks, so there is no ring-buffer pre-fill delay. This is essential
            # for BT devices whose defaultHighOutputLatency can be 1-2 s, which
            # would cause blocking-write streams to pre-buffer that much silence.
            self._audio_stream = self._pyaudio.open(
                format=pyaudio.paFloat32,
                channels=2,
                rate=self._sample_rate,
                output=True,
                output_device_index=self._audio_device_index,
                frames_per_buffer=1024,
                stream_callback=self._audio_callback
            )
            self._audio_stream.start_stream()

            if self._haptic_device_index is not None:
                haptic_info = self._pyaudio.get_device_info_by_index(self._haptic_device_index)
                self._haptic_stream = self._pyaudio.open(
                    format=pyaudio.paFloat32,
                    channels=2,
                    rate=self._sample_rate,
                    output=True,
                    output_device_index=self._haptic_device_index,
                    frames_per_buffer=1024,
                    stream_callback=self._haptic_callback
                )
                self._haptic_stream.start_stream()

            print(f"[enigma] [Audio] Initialized audio device: {audio_info['name']}")
            if self._haptic_device_index is not None:
                haptic_info = self._pyaudio.get_device_info_by_index(self._haptic_device_index)
                print(f"[enigma] [Audio] Initialized haptic device: {haptic_info['name']}")

            self._initialized = True

        except Exception as e:
            print_error(f"[enigma] [Audio] ERROR: Failed to initialize audio devices: {e}")
            print_error(f"[enigma] [Audio] Audio playback will be disabled")
            self._initialized = True

    def _find_device(self, device_name: str) -> Optional[int]:
        """Find device ID by name"""
        if device_name == "default":
            return None

        if not self._pyaudio:
            return None

        device_count = self._pyaudio.get_device_count()
        for i in range(device_count):
            try:
                info = self._pyaudio.get_device_info_by_index(i)
                if device_name.lower() in info['name'].lower():
                    if info['maxOutputChannels'] > 0:
                        return i
            except Exception:
                continue

        print_error(f"[enigma] [Audio] ERROR: Device '{device_name}' not found.")
        return None

    def play(self, audio_data: tuple, haptic_data: Optional[tuple] = None,
             volume: float = 1.0, loops: bool = False,
             fade_in: float = 0.0, volume_callback=None) -> int:
        """
        Play a sound

        Args:
            audio_data: Tuple of (numpy_array, samplerate)
            haptic_data: Optional haptic audio data
            volume: Event-level volume (0.0 to 1.0)
            loops: Whether to loop the sound
            fade_in: Fade in duration in seconds
            volume_callback: Optional callback that returns (audio_vol, haptic_vol)

        Returns:
            Sound ID for controlling playback
        """
        if not self._initialized:
            self.initialize()

        if not self._audio_stream:
            return -1

        audio_array, samplerate = audio_data

        if not isinstance(audio_array, np.ndarray):
            audio_array = np.array(audio_array)

        if samplerate != self._sample_rate:
            audio_array = self._resample(audio_array, samplerate, self._sample_rate)

        if len(audio_array.shape) == 1:
            audio_array = np.column_stack([audio_array, audio_array])
        elif audio_array.shape[1] == 1:
            audio_array = np.column_stack([audio_array, audio_array])

        audio_array = audio_array.astype(np.float32)

        haptic_array = None
        if haptic_data:
            haptic_array, haptic_sr = haptic_data
            if not isinstance(haptic_array, np.ndarray):
                haptic_array = np.array(haptic_array)

            if haptic_sr != self._sample_rate:
                haptic_array = self._resample(haptic_array, haptic_sr, self._sample_rate)

            if len(haptic_array.shape) == 1:
                haptic_array = np.column_stack([haptic_array, haptic_array])
            elif haptic_array.shape[1] == 1:
                haptic_array = np.column_stack([haptic_array, haptic_array])

            haptic_array = haptic_array.astype(np.float32)

        fade_in_samples = int(fade_in * self._sample_rate)

        with self._lock:
            sound_id = self._next_sound_id
            self._next_sound_id += 1

            self._playing_sounds.append(PlayingSound(
                sound_id=sound_id,
                audio_data=audio_array,
                haptic_data=haptic_array,
                samplerate=self._sample_rate,
                volume=volume,
                loops=loops,
                fade_in_samples=fade_in_samples,
                volume_callback=volume_callback
            ))

        return sound_id

    def _resample(self, audio: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
        """Simple resampling using linear interpolation"""
        if from_rate == to_rate:
            return audio

        duration = len(audio) / from_rate
        new_length = int(duration * to_rate)

        if len(audio.shape) == 1:
            return np.interp(
                np.linspace(0, len(audio) - 1, new_length),
                np.arange(len(audio)),
                audio
            )
        else:
            resampled = np.zeros((new_length, audio.shape[1]))
            for ch in range(audio.shape[1]):
                resampled[:, ch] = np.interp(
                    np.linspace(0, len(audio) - 1, new_length),
                    np.arange(len(audio)),
                    audio[:, ch]
                )
            return resampled

    def stop(self, sound_id: int, fade_out: float = 0.0):
        """Stop a playing sound"""
        with self._lock:
            for sound in self._playing_sounds:
                if sound.sound_id == sound_id:
                    if fade_out > 0:
                        sound.fade_out_samples = int(fade_out * sound.samplerate)
                        sound.current_fade_sample = 0
                    else:
                        sound.finished = True
                    break

    def stop_all(self, fade_out: float = 0.0):
        """Stop all playing sounds"""
        with self._lock:
            for sound in self._playing_sounds:
                if fade_out > 0:
                    sound.fade_out_samples = int(fade_out * sound.samplerate)
                    sound.current_fade_sample = 0
                else:
                    sound.finished = True

    def is_playing(self, sound_id: int) -> bool:
        """Return True if the sound is still actively playing (not finished)."""
        with self._lock:
            return any(s.sound_id == sound_id and not s.finished
                       for s in self._playing_sounds)

    def set_volume(self, sound_id: int, volume: float):
        """Set volume for a playing sound"""
        with self._lock:
            for sound in self._playing_sounds:
                if sound.sound_id == sound_id:
                    sound.volume = max(0.0, min(1.0, volume))
                    break

    def _audio_callback(self, in_data, frame_count, time_info, status):
        """Audio output callback - mixes all playing sounds"""
        outdata = np.zeros((frame_count, 2), dtype=np.float32)

        with self._lock:
            sounds_to_remove = []

            for sound in self._playing_sounds:
                if sound.finished:
                    sounds_to_remove.append(sound)
                    continue

                event_volume = sound.volume
                if sound.volume_callback:
                    try:
                        audio_vol, _ = sound.volume_callback()
                        event_volume = audio_vol
                    except:
                        pass

                samples_needed = frame_count
                output_pos = 0

                while samples_needed > 0 and not sound.finished:
                    samples_available = len(sound.audio_data) - sound.position
                    samples_to_copy = min(samples_needed, samples_available)

                    if samples_to_copy <= 0:
                        if sound.loops:
                            sound.position = 0
                            continue
                        else:
                            sound.finished = True
                            break

                    chunk = sound.audio_data[sound.position:sound.position + samples_to_copy]
                    vol = np.full(samples_to_copy, event_volume, dtype=np.float32)

                    if sound.fade_in_samples > 0 and sound.position < sound.fade_in_samples:
                        n_fi = min(samples_to_copy, sound.fade_in_samples - sound.position)
                        positions = np.arange(sound.position, sound.position + n_fi, dtype=np.float32)
                        vol[:n_fi] *= positions / sound.fade_in_samples

                    if sound.fade_out_samples > 0:
                        cfs = sound.current_fade_sample
                        fos = sound.fade_out_samples
                        remaining = fos - cfs
                        if remaining <= 0:
                            sound.finished = True
                            break
                        n_fo = min(samples_to_copy, remaining)
                        vol[:n_fo] *= np.linspace(
                            1.0 - cfs / fos, 1.0 - (cfs + n_fo) / fos,
                            n_fo, dtype=np.float32
                        )
                        sound.current_fade_sample += n_fo
                        if sound.current_fade_sample >= fos:
                            samples_to_copy = n_fo
                            sound.finished = True

                    outdata[output_pos:output_pos + samples_to_copy] += \
                        chunk[:samples_to_copy] * vol[:samples_to_copy, np.newaxis]

                    sound.position += samples_to_copy
                    output_pos += samples_to_copy
                    samples_needed -= samples_to_copy

            for sound in sounds_to_remove:
                self._playing_sounds.remove(sound)

        outdata[:] = np.tanh(outdata * 1.1) / np.tanh(np.float32(1.1))
        return (outdata.tobytes(), pyaudio.paContinue)

    def _haptic_callback(self, in_data, frame_count, time_info, status):
        """Haptic output callback - mixes haptic data"""
        outdata = np.zeros((frame_count, 2), dtype=np.float32)

        with self._lock:
            for sound in self._playing_sounds:
                if sound.finished or sound.haptic_data is None:
                    continue

                event_volume = sound.volume
                if sound.volume_callback:
                    try:
                        _, haptic_vol = sound.volume_callback()
                        event_volume = haptic_vol
                    except:
                        pass

                samples_needed = frame_count
                output_pos = 0

                while samples_needed > 0 and not sound.finished:
                    samples_available = len(sound.haptic_data) - sound.position
                    samples_to_copy = min(samples_needed, samples_available)

                    if samples_to_copy <= 0:
                        if sound.loops:
                            sound.position = 0
                            continue
                        else:
                            break

                    chunk = sound.haptic_data[sound.position:sound.position + samples_to_copy]
                    outdata[output_pos:output_pos + samples_to_copy] += chunk * event_volume
                    output_pos += samples_to_copy
                    samples_needed -= samples_to_copy

        outdata[:] = np.tanh(outdata * 1.1) / np.tanh(np.float32(1.1))
        return (outdata.tobytes(), pyaudio.paContinue)

    def shutdown(self):
        """Shutdown audio player and close streams"""
        if self._audio_stream:
            self._audio_stream.stop_stream()
            self._audio_stream.close()
            self._audio_stream = None

        if self._haptic_stream:
            self._haptic_stream.stop_stream()
            self._haptic_stream.close()
            self._haptic_stream = None

        if self._pyaudio:
            self._pyaudio.terminate()
            self._pyaudio = None

        self._initialized = False
