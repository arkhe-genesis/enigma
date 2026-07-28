# Generated code (checked in as an example)

The `*.py` files here (`devices.py`, `controls.py`, `audio_events.py` as applicable)
and the `*.txt` references are produced from the JSON configs in `../configs/` by the
enigma generators. Generated code is normally a build artifact and is not committed;
this copy is checked in **on purpose**, as part of the example.

The point is to let you read the exact Spec / Control / audio classes the application
code imports (`PortEngineSpec.Thrust`, `EngineControl.Throttle.value`,
`Ui.knob_adjust()`, and so on) without installing the toolchain and running the
generators first. The `*.txt` files are the generators' human-readable reference
output (their `--docs` mode): a plain catalogue of every spec, control, and audio
event with types, defaults, and usage.

Do not edit these by hand. Regenerate from the configs with `make gen` (or the
individual `python3 -m enigma.tools.generate_*` commands).
