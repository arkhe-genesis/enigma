# Audio System Configuration

The audio system is driven by three JSON files: device configuration, class
definitions, and the event library. Together they control every sound the sim
produces, including background music, voice callouts, ambient loops, UI clicks,
and haptic feedback.

---

## audio_devices.json

Declares the two output streams. Both are standard OS audio devices; the haptic
output is typically a bass shaker or rumble transducer driven as a second stereo
output.

```json
{
  "audio_device": "External Headphones",
  "haptic_device": "USB Advanced Audio Device"
}
```

| Property | Required | Description |
|----------|----------|-------------|
| `audio_device` | Yes | OS audio device name, or `"default"` |
| `haptic_device` | No | OS audio device name for haptic output. If absent or not found, haptic output is silently skipped. |

Device names must match your OS audio device names exactly. On macOS, run
`system_profiler SPAudioDataType` to list them.

### Haptic file auto-discovery

The library finds haptic tracks automatically; no explicit field is needed in
event definitions. For any audio file, it looks for a matching file in a `haptic/`
subdirectory at the same level, with the same base name and any supported extension:

```
sounds/
  events/
    explosion.wav        <- audio output
    haptic/
      explosion.wav      <- haptic output, discovered automatically
```

If no haptic sibling exists, audio plays normally with no haptic output. Haptic
volume is controlled by a dedicated master (`set_master_haptic_volume()`)
independent of the speaker master, so you can silence the speakers without killing
the shakers.

---

## audio_classes.json

Defines how sounds in each class behave. The library ships with six standard
classes; you can add more or change them.

```json
{
  "base_path": "./sounds/",
  "classes": {
    "music":   { "max_simultaneous": 1, "supports_crossfade": true,  "crossfade_time": 2.0, "max_volume": 0.5 },
    "ambient": { "max_simultaneous": -1,"supports_crossfade": true,  "crossfade_time": 1.0, "max_volume": 0.7 },
    "voice":   { "max_simultaneous": 1, "supports_priority": true,   "post_pause": 0.3,     "max_volume": 1.0, "dedupe": true },
    "event":   { "max_simultaneous": -1,"supports_crossfade": false,                         "max_volume": 0.8 },
    "ui":      { "max_simultaneous": -1,"supports_crossfade": false,                         "max_volume": 0.8 },
    "alerts":  { "max_simultaneous": -1,"supports_crossfade": false,                         "max_volume": 0.8 }
  },
  "reset_fadeout_time": 5.0
}
```

### Top-level properties

| Property | Description |
|----------|-------------|
| `base_path` | Root directory for all audio files |
| `reset_fadeout_time` | Seconds to fade out all audio on `Audio.reset()` |

### Class properties

| Property | Default | Description |
|----------|---------|-------------|
| `max_simultaneous` | `-1` | Max concurrent sounds in this class. `-1` = unlimited. |
| `supports_crossfade` | `false` | Fade the previous sound out while the new one fades in. |
| `crossfade_time` | `1.0` | Default crossfade duration in seconds. |
| `supports_priority` | `false` | Enable priority-based queuing (see below). |
| `post_pause` | `0.0` | Silence after each sound before the next can begin. |
| `max_volume` | `1.0` | Hard ceiling on this class's output level. All runtime `set_class_volume()` calls are scaled against this value, so it acts as a permanent mix-level bake-in. Use it to keep music from overwhelming voice regardless of the operator's volume knob. |
| `dedupe` | `false` | Enable adjacent-play dedupe (see below). Only meaningful for queued classes (currently `voice`). |

### Example classes

Class names are user-defined; the library imposes no fixed set. The following
are the classes used in the reference implementation and are a reasonable
starting point for most projects.

| Class | Purpose |
|-------|---------|
| `music` | Background music: single looping track or shuffled playlist with crossfade |
| `ambient` | Environmental loops: engine hum, reactor noise, life support fans |
| `voice` | Voice callouts: sequential, priority-queued, one at a time |
| `event` | One-shot sound effects: explosions, impacts |
| `ui` | Interface feedback: clicks, toggles, knob detents |
| `alerts` | Warning tones: persistent or repeating alert sounds |

### Priority queuing

When `supports_priority: true` and `max_simultaneous` limits concurrent playback,
the class maintains a single priority queue. Higher numbers win. Any class can
use priority queuing; it is not restricted to voice.

On each new request the library computes the **high-water-mark priority**: the
highest of the currently-playing clip and any clips already in the queue. Then:

- New request **below** high-water-mark: dropped silently.
- New request **above** high-water-mark: queue is cleared, new clip is added.
- New request **equal** to high-water-mark: added to the end of the queue.
- The currently playing clip always finishes regardless of what arrives.

Same-priority clips therefore accumulate in order; a higher-priority clip wipes
the queue first. The queue at any point contains only clips of the current
high-water-mark priority.

**Example** (voice, `max_simultaneous: 1`):

1. Priority 2 "Forward shields raised" starts playing. High-water-mark: 2.
2. Priority 5 "Aft shields down" arrives. 5 > 2, queue cleared (empty anyway), clip queued. HWM: 5.
3. Priority 3 "Hull integrity restored" arrives. 3 < 5, dropped.
4. Priority 5 "Starboard thruster offline" arrives. 5 == 5, added to queue.
5. Priority 10 "Antimatter pressure critical" arrives. 10 > 5, queue cleared, clip queued. HWM: 10.

Result: priority-2 finishes, then priority-10 plays. The priority-5 and
priority-3 clips are never heard.

### Adjacent-play dedupe

When `dedupe: true`, the queue rejects any incoming request whose clip name
matches the immediately adjacent clip: that is, the last clip already in the
queue, or the currently-playing clip if the queue is empty. Prevents
rapid-fire duplicates from stacking into narration that repeats the same line
three or five times back to back.

The rule is deliberately narrow: it only cancels *consecutive* repeats.
Interleaved sequences still play in full: a stream of `X, Y, X` all queue,
because when the second `X` arrives the tail is `Y`, not `X`. Only the
immediate re-request of the same clip gets dropped.

**Example** (voice, `max_simultaneous: 1`, `dedupe: true`):

1. "Hull breach detected" arrives. Queue empty, nothing playing -> queued.
2. Same clip arrives again. Tail matches -> dropped.
3. Same clip arrives a third time. Tail still matches -> dropped.
4. "Shield integrity degraded" arrives. Different clip -> queued.
5. "Hull breach detected" arrives. Tail is now the shield clip -> queued.

Only meaningful for classes that maintain a queue (`max_simultaneous: 1` plus
`supports_priority`). Fire-and-forget classes like `event` and `ambient`
ignore the flag.

---

## audio_library.json

Defines every named audio event. Each key is an event name; the value is a config
object.

### Common event properties

| Property | Default | Description |
|----------|---------|-------------|
| `class` | Required | Audio class (must match a key in audio_classes.json) |
| `audio` | (none) | Path to audio file or directory, relative to `base_path` |
| `volume` | `1.0` | Playback volume: float or `[min, max]` for random variation |
| `priority` | none | Priority level for queued classes (voice) |
| `playback_mode` | `"overlap"` | How to handle concurrent plays (see below) |
| `shuffle` | `false` | Auto-advance through directory files as a jukebox playlist |
| `fade_in` | `0.0` | Fade-in duration per track, in seconds |

### File resolution

The `audio` path is always resolved by the library regardless of whether an
extension is specified. If you write `"path/file.wav"` and only `file.mp3`
exists, the library plays the mp3. The extension in the path is a hint, not a
requirement.

| Value | Behavior |
|-------|-----------|
| `"path/file.wav"` | Resolves to the first matching file with any supported extension |
| `"path/name"` | Same: finds `name.wav`, `.ogg`, `.flac`, or `.mp3`, whichever exists |
| `"path/dir/"` | Directory: picks a **random file** from the directory on each play |

The directory form is ideal for voice lines with multiple takes, or UI sounds that
benefit from natural variation. Add files to the directory; the library discovers
them automatically at runtime.

### Volume randomisation

`volume` can be a float or a `[min, max]` pair. With a range, a random value is
chosen on each play:

```json
"button_click": { "volume": [0.3, 0.6] }
```

Repeated sounds feel organic without any device code involvement.

### Playback modes

| Mode | Behavior |
|------|-----------|
| `"overlap"` | New play stacks alongside any currently playing instances (default) |
| `"replace"` | Stop the currently playing instance, start the new one |
| `"ignore"` | Skip if this event is already playing |

### Jukebox mode

Set `"shuffle": true` on a directory-backed event. The library plays all tracks
in a randomly shuffled order with no repeats until every clip has been heard, then
reshuffles and continues. The first track of each new cycle differs from the last
of the previous one (when more than one track exists).

```json
"combat_music": {
  "class": "music",
  "audio": "music/combat",
  "shuffle": true,
  "volume": 0.7,
  "fade_in": 2.0
}
```

### Looping ambient sounds

Simple looping sounds (fans, idle hum, background atmosphere) are started and
stopped via the API. No special config property is needed; a class with
`supports_crossfade: true` handles smooth looping automatically.

```json
"life_support_fans": {
  "class": "ambient",
  "audio": "ambient/fans",
  "volume": 0.25
}
```

Game code:

```python
Ambient.life_support_fans.start()   # begins looping
Ambient.life_support_fans.stop()    # stops
```

### Watched ambient sounds (spec-driven volume)

For ambient sounds whose volume should track a spec variable (engine noise that
scales with thrust, reactor hum that rises with power), declare a `watch_spec`
and `thresholds`. The audio system watches the variable and crossfades between
audio files as the value moves through the declared ranges.

```json
"port_engine": {
  "class": "ambient",
  "watch_spec": "PortEngineSpec.Thrust",
  "crossfade_time": 0.5,
  "thresholds": [
    { "value_range": [0.0,      100000.0], "audio": "engines/port/idle",   "volume_range": [0.0, 0.3] },
    { "value_range": [100000.0, 500000.0], "audio": "engines/port/cruise", "volume_range": [0.3, 0.7] },
    { "value_range": [500000.0, 1.0e7],   "audio": "engines/port/full",   "volume_range": [0.7, 1.0] }
  ]
}
```

**Threshold properties:**

| Property | Description |
|----------|-------------|
| `value_range` | `[min, max]` spec value range this entry covers |
| `audio` | Audio file or directory to play in this range |
| `volume_range` | `[min, max]` range; volume is linearly interpolated across the range |

Within a threshold, volume interpolates as the spec value moves across the range.
At a boundary between thresholds, the library crossfades between the two audio
files over `crossfade_time` seconds.

Watched ambient events start and stop automatically; setting the spec variable is all device code has to do.

### Watched voice events (auto-triggered on threshold crossing)

Voice callouts can fire automatically when a spec value crosses a threshold:

```json
"voice_reactor_critical": {
  "class": "voice",
  "audio": "voice/powercore/reactor_critical.wav",
  "watch_spec": "PowerCoreSpec.Temperature",
  "watch_condition": "rising >= 175",
  "priority": 8,
  "volume": 1.0
}
```

**`watch_condition` format:** `direction operator value`

| Direction | Fires when... |
|-----------|---------------|
| `rising` | Value crosses the threshold from below |
| `falling` | Value crosses the threshold from above |

Standard comparison operators: `>`, `<`, `>=`, `<=`, `==`.

The callout fires once per crossing; it does not re-trigger while the value
remains above (or below) the threshold.

---

## Volume cascade

Final output volume is the product of three independent levels:

```
output = master_volume * class_max_volume * event_volume
```

| Level | Set via |
|-------|---------|
| `master_volume` | `Audio.master_audio_volume(v)` at runtime |
| `class_max_volume` | `max_volume` in audio_classes.json (permanent ceiling) |
| `event_volume` | `volume` in audio_library.json (float or random range) |

`class_max_volume` is a baked ceiling; the operator cannot exceed it through the
runtime volume control. It keeps music from drowning out voice.

---

## Event examples

### UI click with randomised volume

```json
"button_click": {
  "class": "ui",
  "audio": "ui/clicks",
  "volume": [0.3, 0.6],
  "playback_mode": "replace"
}
```

### Prioritized voice callout

```json
"voice_engine_fault": {
  "class": "voice",
  "audio": "voice/engine_fault.wav",
  "priority": 10,
  "volume": 1.0
}
```

### Shuffled music playlist

```json
"exploration_music": {
  "class": "music",
  "audio": "music/exploration",
  "shuffle": true,
  "volume": 0.4,
  "fade_in": 3.0
}
```

### Simple looping ambient

```json
"idle_hum": {
  "class": "ambient",
  "audio": "ambient/idle_hum",
  "volume": 0.4
}
```

### Watched ambient (spec-driven volume, multi-threshold crossfade)

```json
"reactor_hum": {
  "class": "ambient",
  "watch_spec": "PowerCoreSpec.ReactorPowerLevel",
  "crossfade_time": 2.0,
  "thresholds": [
    { "value_range": [0.0, 0.5], "audio": "reactor/startup", "volume_range": [0.0, 0.6] },
    { "value_range": [0.5, 0.9], "audio": "reactor/normal",  "volume_range": [0.6, 0.8] },
    { "value_range": [0.9, 1.0], "audio": "reactor/overload","volume_range": [0.8, 1.0] }
  ]
}
```

### Watched voice (auto-trigger on value crossing)

```json
"voice_overheat_warning": {
  "class": "voice",
  "audio": "voice/overheat_warning.wav",
  "watch_spec": "EngineSpec.Temperature",
  "watch_condition": "rising >= 1000",
  "priority": 7,
  "volume": 1.0
}
```

---

## File layout

```
configs/
+-- audio_classes.json
+-- audio_library.json
`-- audio_devices.json

sounds/
+-- ui/
|   +-- clicks/            <- directory -> random pick per play
|   `-- toggles/
+-- music/
|   `-- combat/            <- directory -> shuffle jukebox
+-- ambient/
|   `-- idle_hum.wav
+-- engines/
|   `-- port/
|       +-- idle.wav
|       +-- cruise.wav
|       +-- full.wav
|       `-- haptic/
|           `-- full.wav   <- auto-discovered haptic for engines/port/full
+-- voice/
|   `-- engine_fault.wav
`-- events/
    +-- explosion.wav
    `-- haptic/
        `-- explosion.wav  <- auto-discovered haptic for events/explosion
```

## See Also

- [CONTROL_MAPPINGS.md](CONTROL_MAPPINGS.md): Generated audio event class usage
- `enigma/audio/`: Runtime implementation
