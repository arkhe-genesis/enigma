# Mapping Files

Three JSON files in `configs/` wire the library together. They are all expected
to live in the same directory.

---

## control_mappings.json

Maps physical HID devices to their board config files. When a board connects
over USB, the library looks it up here to know which config to load.

### Format

```json
{
  "BOARD-NN": "ConfigName",
  ...
}
```

`BOARD` is the board type identifier; `NN` is the board's **decimal** address
(00-15), set via physical DIP switches on the board. Every board of the same
type must have a unique address; you cannot have two `SW14-03` boards on the
same bus. Addresses are independent across types, so `SW14-11` and `QD04-11`
can coexist without conflict.

### Board type identifiers

| Type | Board |
|------|-------|
| `SW14` | 14-switch illuminated panel |
| `QD04` | 4-channel quadrature encoder with LED rings |
| `AN08` | 8-channel 10-bit analog ADC |
| `T16K` | Thrustmaster T.16000M joystick |
| `GPRO` | Logitech G Pro keyboard |

### Example

```json
{
  "SW14-00": "PortEngineSwitches",
  "SW14-01": "StarboardEngineSwitches",
  "SW14-02": "PowerCorePanel",
  "SW14-04": "FtlSwitches",
  "SW14-11": "LifeSupportSwitches",

  "QD04-00": "FtlKnobs",
  "QD04-01": "MainScreenKnobs",
  "QD04-02": "LifeSupportKnobs1",
  "QD04-03": "LifeSupportKnobs2",

  "AN08-00": "Pedals",

  "T16K-00": "PortStick",
  "T16K-01": "StarboardStick",

  "GPRO-00": "Keyboard"
}
```

`SW14-11` means an SW14 board with DIP switches set to address 11 (decimal).

### Panel aggregation

When multiple config files share the same `name` field, the code generator
merges them into one class. Use this to group controls that are logically
related into a single convenient panel class, regardless of how many physical
boards they span.

```json
// LifeSupportKnobs1.json   ->  "name": "LifeSupport"
// LifeSupportKnobs2.json   ->  "name": "LifeSupport"
// LifeSupportSwitches.json ->  "name": "LifeSupport"
```

Panel name is the only aggregation key; address and board type don't matter.
Any boards with the same `name` are merged.

Control names must be unique across all boards sharing the same panel name.
If two boards both define a control called `PowerEnable`, the generator will
have a collision. Use distinct names for every control within an aggregated
panel.

---

## device_mappings.json

Maps logical spec names to their definition files. Multiple logical specs can
share the same definition file while maintaining independent runtime state.

```json
{
  "PowerCoreSpec":      "PowerCoreSpec.json",
  "PortEngineSpec":     "EngineSpec.json",
  "StarboardEngineSpec":"EngineSpec.json",
  "ShipSpec":           "ShipSpec.json",
  "FtlSpec":      "FtlSpec.json"
}
```

Here `PortEngineSpec` and `StarboardEngineSpec` both use `EngineSpec.json` but
hold separate values at runtime.

See [DEVICE_SPECS.md](DEVICE_SPECS.md) for the spec file format.

---

## display_mappings.json

Maps display names to their config files.

```json
{
  "PowerCoreDisplay": "PowerCoreDisplay.json",
  "FtlDisplay": "FtlDisplay.json",
  "MainDisplay":      "MainDisplay.json"
}
```

See [DISPLAY_CONFIG.md](DISPLAY_CONFIG.md) for the display config format.

---

## How the files relate

```
control_mappings.json     device_mappings.json    display_mappings.json
         |                        |                        |
         v                        v                        v
  Board configs           Spec definitions          Display configs
  (SW14, QD04, ...)         (EngineSpec, ...)           (PowerCoreDisplay, ...)
         |                        |                        |
         v                        v                        v
  generate_controls.py    generate_devices.py       DisplayManager
         |                        |
         v                        v
  generated/controls.py   generated/devices.py


audio_classes.json  -+
audio_library.json  -+->  generate_audio.py  -->  generated/audio_events.py

audio_devices.json  -->  AudioManager (output device selection, runtime only)
```

---

## See Also

- [SW14_CONFIG.md](SW14_CONFIG.md): switch panel config reference
- [QD04_CONFIG.md](QD04_CONFIG.md): encoder board config reference
- [AN08_CONFIG.md](AN08_CONFIG.md): analog input board config reference
- [DEVICE_SPECS.md](DEVICE_SPECS.md): spec var format and usage
- [DISPLAY_CONFIG.md](DISPLAY_CONFIG.md): display config format
- [AUDIO_CONFIG.md](AUDIO_CONFIG.md): audio config format
