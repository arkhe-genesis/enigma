# Audio Classes

The code generator produces one class per audio class declared in
`audio_classes.json`. Each class exposes class-level volume and reset controls
plus one method or nested class per event declared in `audio_library.json`.

Three event patterns exist: **one-shot** (play and forget), **looping** (start
and stop explicitly), and **watched** (spec-driven, volume follows a value).

---

## Class-level methods

Every generated audio class has these four methods.

---

### `ClassName.volume(level)`

Set the runtime volume for this class. Scaled against the class's `max_volume`
ceiling from `audio_classes.json`; the operator cannot exceed that ceiling
regardless of what value is passed here.

```python
Voice.volume(0.8)
Music.volume(0.3)
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `level` | `float` | Volume from `0.0` (silent) to `1.0` (class ceiling). |

---

### `ClassName.reset(now=False)`

Stop all currently playing and queued sounds in this class.

```python
Music.reset()          # fade out over reset_fadeout_time
Music.reset(now=True)  # stop immediately
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `now` | `bool` | If `True`, stop immediately. If `False`, fade out over `reset_fadeout_time`. Default `False`. |

---

### `ClassName.ready()`

Returns `True` if nothing in this class is currently playing or queued.

```python
if Voice.ready():
    Voice.voice_mission_briefing()
```

---

### `ClassName.clear_pending()`

Drop all queued (not-yet-playing) requests in this class. The currently playing
sound finishes normally. Returns the number of requests removed.

```python
count = Voice.clear_pending()
```

---

## One-shot events

Events with no `loop` or `shuffle` key play once and stop. The generated method
name matches the event name from `audio_library.json`.

```python
Event.explosion()
Ui.button_click()
Voice.voice_engine_fault()
```

No parameters. No return value.

---

## Looping events

Events with `shuffle: true` start a jukebox playlist; others loop a single
track. The generated method starts the loop; a paired `stop_*` method stops it.

```python
Music.combat_music()           # start
Music.stop_combat_music()      # stop
```

Looping events that support jukebox mode shuffle all tracks in the directory,
exhausting the list before repeating any. The playlist reshuffles each cycle,
avoiding the same track back-to-back at cycle boundaries.

---

## Watched events

Watched events are driven by a spec var value rather than explicit API calls.
Each watched event is a nested class that must be instantiated once at startup
with the spec var (or any object with a `.value` property) to watch.

```python
# Startup wiring (once, at init time)
Ambient.EngineHum(PortEngineSpec.Thrust)
```

After that, the audio system polls the value automatically and adjusts volume
and track selection according to the thresholds in `audio_library.json`. No
further calls are needed from device code; just update the spec var normally.

### Methods on watched event instances

All watched events expose the same class methods:

---

#### `WatchedEvent.start()`

Activate the watched event. Usually called at startup after instantiation.

```python
Ambient.EngineHum.start()
```

---

#### `WatchedEvent.stop()`

Stop the watched event and release its audio resources.

```python
Ambient.EngineHum.stop()
```

---

#### `WatchedEvent.pause()`

Pause volume updates without stopping the underlying audio.

```python
Ambient.EngineHum.pause()
```

---

#### `WatchedEvent.reset(now=False)`

Stop and reset this watched event.

```python
Ambient.EngineHum.reset()
Ambient.EngineHum.reset(now=True)
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `now` | `bool` | Immediate stop if `True`, fade if `False`. |

---

#### `WatchedEvent.ready()`

Returns `True` if the watched event is not currently active.

```python
if Ambient.EngineHum.ready():
    Ambient.EngineHum.start()
```
