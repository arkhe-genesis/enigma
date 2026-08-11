# SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
# SPDX-License-Identifier: MIT

"""
Halcyon Dawn Audio Subsystem

Provides multi-channel audio playback with support for:
- Background music with crossfading
- UI sound effects
- Ambient/looping sounds with dynamic volume/crossfading
- Event-based sounds (damage, alerts, etc.)
- Priority-based voice callouts
- Dual output (main audio + haptic feedback via USB amp)
"""

from .audio_manager import AudioManager

__all__ = ['AudioManager']
