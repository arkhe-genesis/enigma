# Halcyon Dawn Audio System Usage

## Overview

The audio system provides multi-channel audio playback with support for:
- Background music with crossfading
- UI sound effects (clicks, toggles, etc.)
- Ambient/looping sounds with dynamic volume (engines, reactor hum)
- Event-based sounds with haptic feedback (damage, explosions)
- Priority-based voice callouts
- Dual output (main audio + USB haptic device)

## Setup

1. Install dependencies:
   ```bash
   pip install sounddevice soundfile numpy
   ```

2. Generate audio events from config:
   ```bash
   python enigma/tools/generate_audio.py
   ```

3. Initialize in your main application:
   ```python
   from enigma.audio import AudioManager

   # Initialize AudioManager
   audio_manager = AudioManager(config_manager)

   # In main loop, call update:
   while running:
       # ... other updates ...
       audio_manager.update(delta_time)
   ```

## Usage Examples

### Simple Sounds (UI, Events)

```python
from generated.audio_events import Ui, Event

# Play UI sounds
Ui.button_click()
Ui.switch_toggle()

# Play event sounds (with haptic feedback)
Event.missile_impact()
Event.laser_hit()
```

### Voice Callouts (Priority-based)

```python
from generated.audio_events import Voice

# High priority (10) - will interrupt lower priority
Voice.voice_antimatter_critical()

# Low priority (2) - can be dropped if higher priority playing
Voice.voice_docking_complete()
```

### Looping Sounds (Music)

```python
from generated.audio_events import Music

# Start background music
Music.combat_music()

# Later, stop it
Music.stop_combat_music()

# Switch to different music (crossfades automatically)
Music.exploration_music()
```

### Watched Audio (Dynamic)

Watched audio automatically adjusts based on a monitored value (like throttle or reactor power):

```python
from generated.audio_events import Ambient

class MyDevice(SimulatorDevice):
    def __init__(self):
        super().__init__()

        # Initialize watched audio - auto-starts and monitors value
        Ambient.PortEngine(self.port_engine_throttle)
        Ambient.StarboardEngine(self.starboard_engine_throttle)
        Ambient.ReactorHum(self.reactor_power_level)

    def emergency_shutdown(self):
        # Stop engine sounds
        Ambient.PortEngine.stop()
        Ambient.StarboardEngine.stop()
```

The audio manager automatically:
- Monitors the watched value each update
- Crossfades between threshold sounds when value changes
- Interpolates volume based on position within threshold

### Volume Controls

```python
from generated.audio_events import Music, Ui, Audio

# Set class volumes (0.0 to 1.0)
Music.volume(0.3)  # Quiet music
Ui.volume(0.8)     # Louder UI sounds

# Set master volumes
Audio.master_audio_volume(0.9)   # Main speakers
Audio.master_haptic_volume(1.0)  # USB haptic amp
```

### Reset

```python
from generated.audio_events import Audio, Music

# Graceful reset with 5-second fadeout
Audio.reset()
while not Audio.ready():
    time.sleep(0.1)

# Immediate reset (emergency shutdown)
Audio.reset(now=True)

# Reset just one class
Music.reset()
```

## Configuration

### audio_classes.json

Defines behavior for each audio class:
- `max_simultaneous`: How many sounds can play at once (-1 = unlimited)
- `supports_crossfade`: Whether class supports crossfading
- `crossfade_time`: Default crossfade duration in seconds
- `max_volume`: Effective ceiling for the class (0.0-1.0). All `set_class_volume(class, v)` calls are scaled by this; `v` is operator-side in [0..1] and the resulting mix gain is `v x max_volume`.

### audio_library.json

Defines all sound events:

**Simple one-shot sound:**
```json
"button_click": {
  "class": "ui",
  "audio": "ui/clicks",
  "volume": [0.7, 0.9]  // Random between 0.7-0.9
}
```

**Looping sound with fade-in:**
```json
"combat_music": {
  "class": "music",
  "audio": "music/combat",
  "loops": true,
  "volume": 0.6,
  "fade_in": 2.0  // Fade in over 2 seconds when started
}
```

**Sound with haptic feedback:**
```json
"missile_impact": {
  "class": "event",
  "audio": "damage/missile",
  "haptic": "damage/missile/haptic",
  "volume": 1.0
}
```

**Voice callout:**
```json
"voice_antimatter_critical": {
  "class": "voice",
  "audio": "voice/antimatter_critical.wav",
  "priority": 10,
  "volume": 1.0
}
```

**Watched audio with thresholds:**
```json
"port_engine": {
  "class": "ambient",
  "watch_spec": "ShipSpec.PortEngineThrottle",
  "crossfade_time": 1.5,
  "thresholds": [
    {
      "value_range": [0.0, 0.3],
      "audio": "engines/port/idle",
      "volume_range": [0.3, 0.5]  // Interpolates based on position in range
    },
    {
      "value_range": [0.3, 0.7],
      "audio": "engines/port/cruise",
      "volume_range": [0.5, 0.7]
    },
    {
      "value_range": [0.7, 1.0],
      "audio": "engines/port/full",
      "volume_range": [0.7, 1.0]
    }
  ]
}
```

### audio_devices.json

Defines output devices:
```json
{
  "audio_device": "default",
  "haptic_device": "USB Audio Device"
}
```

Use `"default"` for system default device, or specify device name substring.

## File Organization

```
sounds/                  # Base path (configurable)
+-- ui/
|   +-- clicks/         # Directory - random file selected
|   |   +-- click1.wav
|   |   `-- click2.wav
|   `-- toggles/
+-- music/
|   +-- combat/
|   `-- exploration/
+-- engines/
|   `-- port/
|       +-- idle.wav
|       +-- cruise.wav
|       `-- full.wav
`-- voice/
    `-- antimatter_critical.wav  # Specific file
```

- If path has extension -> play that specific file
- If path is directory -> randomly select from available audio files
- Supports: .wav, .ogg, .flac, .mp3

## Volume Hierarchy

Final volume = event_volume x class_volume x master_volume

Example: `missile_impact` with event volume 1.0:
- Audio output: 1.0 x 1.0 (event class) x 0.8 (master audio) = 0.8
- Haptic output: 1.0 x 1.0 (event class) x 1.0 (master haptic) = 1.0

## Running out-of-process (the GIL problem)

By default the audio engine runs **in-process**: a background thread services the
update loop (watched-audio polling, queue, fades) and the mixing happens in
PyAudio's stream callback, which CoreAudio pulls on its own thread. That callback
still executes Python and holds the GIL while it runs, so sustained heavy CPU work
elsewhere in the same interpreter can delay it and cause audible dropouts or
buffer underruns. For light workloads it is a non-issue; under a busy game loop it
is not acceptable.

The fix is built into the library: `AudioManager.spawn()` runs the whole engine in
its **own OS process**, so the mixer gets an independent GIL and scheduling slice
and the parent's load cannot starve it. This is transparent to your code. Instead
of constructing the manager, spawn it:

```python
from enigma.audio import AudioManager

# In-process (default):
#   audio = AudioManager(config_manager)
#
# Out-of-process (mixer on its own core):
audio = AudioManager.spawn(project_root=".")   # forks the audio daemon

# ...from here the two are used identically...
audio.update(dt)   # call each tick
audio.shutdown()   # call at exit (stops and reaps the child)
```

`spawn()` starts `python -m enigma.audio.daemon` as a child, which owns the real
`AudioManager` and runs the mix loop, and installs a lightweight client as the
singleton in this process. **The generated `Voice` / `Event` / `Ambient` / `Music`
/ `Ui` / `Alerts` proxies keep working unchanged**: each call is serialized to
the child over a pipe instead of executing locally. You do not manage the process,
the protocol, or the proxies; the only client-visible difference from in-process
use is the one-line swap above.

Notes:

- `project_root` is the directory holding `configs/` and `sounds/` (defaults to
  the current directory); the child resolves audio paths relative to it.
- `audio.update(dt)` per tick ships changed watched-audio values (engine load,
  reactor level, etc.) to the child so its `WatchedAudio` can crossfade. It goes
  exactly where an in-process `AudioManager.update()` would.
- If the child dies, calls degrade to silent no-ops rather than crashing the
  parent; a one-line notice is printed to stderr.
