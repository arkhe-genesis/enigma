# SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
# SPDX-License-Identifier: MIT

"""
Sound Library - File discovery and random selection

Handles loading audio files from disk with support for:
- Directory-based random selection
- Explicit file paths
- File caching for performance
"""

import os
import random
from pathlib import Path
from typing import Optional, List, Dict
import soundfile as sf

from enigma.colors import print_error, print_warning


class SoundLibrary:
    """Manages audio file discovery and loading"""

    def __init__(self, base_path: str):
        """
        Initialize the sound library

        Args:
            base_path: Base directory for all sound files (e.g., "./sounds/")
        """
        self.base_path = Path(base_path)
        self._file_cache: Dict[str, List[Path]] = {}
        self._data_cache: Dict[Path, tuple] = {}   # path -> (ndarray, samplerate)
        self._warned_paths: set = set()  # Track paths we've already warned about

    def get_random_file(self, path: str) -> Optional[Path]:
        """
        Get a random audio file from the given path

        If path points to a file, returns that file.
        If path has an extension, looks for any audio file with that base name.
        If path points to a directory, returns a random file from that directory.

        Args:
            path: Relative path from base_path (e.g., "ui/clicks" or "voice/critical.wav")

        Returns:
            Full path to audio file, or None if not found
        """
        full_path = self.base_path / path

        # Check if it's a direct file reference that exists
        if full_path.is_file():
            return full_path

        # Check if it's a directory
        if full_path.is_dir():
            # Use cache if available
            cache_key = str(full_path)
            if cache_key not in self._file_cache:
                # Find all audio files in directory (non-recursive), excluding haptic subdir
                audio_files = []
                for ext in ['*.wav', '*.ogg', '*.flac', '*.mp3']:
                    audio_files.extend(full_path.glob(ext))

                if not audio_files:
                    if path not in self._warned_paths:
                        print_warning(f"[Audio] WARNING: No audio files found in {full_path}")
                        self._warned_paths.add(path)
                    return None

                self._file_cache[cache_key] = audio_files

            # Return random file from cache
            files = self._file_cache[cache_key]
            return random.choice(files) if files else None

        # Not a file or directory - try to find file with any supported extension
        # This handles both "file.wav" and "file" (no extension) cases
        base_name = full_path.stem if '.' in full_path.name else full_path.name
        parent_dir = full_path.parent

        # Look for any audio file with this base name
        for ext in ['.wav', '.ogg', '.flac', '.mp3']:
            candidate = parent_dir / (base_name + ext)
            if candidate.is_file():
                return candidate

        # No file found with any supported extension
        if path not in self._warned_paths:
            print_warning(f"[Audio] WARNING: No audio file found for '{base_name}' in {parent_dir}")
            self._warned_paths.add(path)
        return None

    def get_all_files(self, path: str) -> List[Path]:
        """
        Return all audio files for the given path.

        If path is a directory, returns every audio file in it (populating
        the cache as a side effect, same as get_random_file).
        If path resolves to a single file, returns [that file].
        Returns an empty list if nothing is found.
        """
        full_path = self.base_path / path

        if full_path.is_file():
            return [full_path]

        if full_path.is_dir():
            cache_key = str(full_path)
            if cache_key not in self._file_cache:
                audio_files = []
                for ext in ['*.wav', '*.ogg', '*.flac', '*.mp3']:
                    audio_files.extend(full_path.glob(ext))
                if not audio_files:
                    if path not in self._warned_paths:
                        print_warning(f"[Audio] WARNING: No audio files found in {full_path}")
                        self._warned_paths.add(path)
                    return []
                self._file_cache[cache_key] = audio_files
            return list(self._file_cache[cache_key])

        return []

    def get_audio_with_haptic(self, path: str) -> tuple:
        """
        Get audio file and auto-discover paired haptic file.

        Haptic files are discovered by convention: if audio is at parent/foo.wav,
        looks for parent/haptic/foo.* with any supported extension.

        Args:
            path: Relative path from base_path (e.g., "ui/clicks" or "damage/missile")

        Returns:
            Tuple of (audio_path, haptic_path) - haptic_path may be None
        """
        audio_file = self.get_random_file(path)
        if not audio_file:
            return (None, None)

        # Look for haptic sibling: same directory + /haptic/ + same base name
        haptic_dir = audio_file.parent / "haptic"
        if haptic_dir.is_dir():
            base_name = audio_file.stem
            for ext in ['.wav', '.ogg', '.flac', '.mp3']:
                haptic_candidate = haptic_dir / (base_name + ext)
                if haptic_candidate.is_file():
                    return (audio_file, haptic_candidate)

        return (audio_file, None)

    def load_audio_file(self, file_path: Path) -> Optional[tuple]:
        """
        Load an audio file into memory, returning a cached copy on repeat calls.

        Args:
            file_path: Full path to audio file

        Returns:
            Tuple of (audio_data, sample_rate) or None if failed
        """
        if file_path in self._data_cache:
            return self._data_cache[file_path]
        try:
            data, samplerate = sf.read(str(file_path))
            result = (data, samplerate)
            self._data_cache[file_path] = result
            return result
        except Exception as e:
            print_error(f"[enigma] [Audio] ERROR: Failed to load {file_path}: {e}")
            return None

    def clear_cache(self):
        """Clear the file cache (useful if files are added/removed at runtime)"""
        self._file_cache.clear()
