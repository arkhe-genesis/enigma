# Code Generation

Enigma is config-driven. You describe your controls, device specs, and audio in
JSON, then run three generators that turn that JSON into:

1. **Importable Python**: the typed classes your application code uses (control
   classes, device `Spec` classes, audio event classes), with `.Values`,
   `.Schemes`, and threshold constants baked in.
2. **A plain-text reference doc**: a human-readable listing of every identifier
   that was generated (names, values, schemes), so you can see what is available
   without reading the generated code.

Every generator produces **both** outputs in one run: the `.py` module via
`--output` and the reference via `--docs`.

## The generators

| Tool | Reads | Generates |
|------|-------|-----------|
| `enigma.tools.generate_controls` | control-board configs (SW14 / QD04 / AN08 / ...) | control classes + reference |
| `enigma.tools.generate_devices`  | device spec configs | spec classes + reference |
| `enigma.tools.generate_audio`    | audio library config | audio event classes + reference |

## Switches (all three share the same set)

| Switch | Required | Description |
|--------|----------|-------------|
| `--config-dir DIR` | No (default `configs`) | Directory holding your `*.json` configs |
| `--output FILE` | Recommended | Path for the generated `.py` module |
| `--docs FILE` | No | Path for the generated plain-text reference; omit to skip the doc |

## Running them

With the library installed (`pip install .` from `host/`), invoke as modules:

```
python3 -m enigma.tools.generate_controls --config-dir configs --output generated/controls.py     --docs docs/controls.txt
python3 -m enigma.tools.generate_devices  --config-dir configs --output generated/devices.py      --docs docs/devices.txt
python3 -m enigma.tools.generate_audio    --config-dir configs --output generated/audio_events.py --docs docs/audio.txt
```

Run all three whenever a config changes, then import the generated modules from
your application code.

## mk.sh

Because you re-run all three together, the repo ships a convenience wrapper,
[`host/mk.sh`](../../mk.sh), that does exactly the above with a few path
variables at the top. Copy it into your project, adjust the paths, and run
`./mk.sh`. It is only a wrapper; a Makefile or the raw commands above are
equivalent.

## Related tools (not generators)

- `enigma.tools.enigma_cli`: interactive device-management / connection tool
  (a thin CLI over `EnigmaManager`).
- `enigma.tools.hid_monitor`: raw HID-report monitor, useful for debugging
  wiring and confirming a board is reporting.
