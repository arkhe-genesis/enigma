#!/usr/bin/env bash
#
# mk.sh - regenerate Enigma code and docs from your JSON configs.
#
# Enigma is config-driven: you describe your controls, device specs, and audio
# in JSON, and three generators turn that JSON into importable Python (the typed
# classes your application code uses) AND a plain-text reference listing every
# identifier they generated. Run this whenever you change a config.
#
# This is a convenience wrapper, nothing more. It runs the three generators
# together with a consistent set of paths. A Makefile, or calling the generators
# directly, works exactly the same -- the name is just habit (typing "make" is
# apparently hard). Copy this into your own project and point the paths below at
# your directories.
#
# Requires the library installed:  (cd host && pip install .)
#
set -euo pipefail

CONFIGS=configs        # directory holding your *.json board / spec / audio configs
OUTDIR=generated       # where the generated .py modules are written
DOCDIR=docs            # where the generated .txt reference files are written

mkdir -p "$OUTDIR" "$DOCDIR"

# Each generator reads --config-dir and writes BOTH:
#   --output : the importable Python module
#   --docs   : a human-readable reference of everything it generated
python3 -m enigma.tools.generate_controls --config-dir "$CONFIGS" --output "$OUTDIR/controls.py"     --docs "$DOCDIR/controls.txt"
python3 -m enigma.tools.generate_devices  --config-dir "$CONFIGS" --output "$OUTDIR/devices.py"      --docs "$DOCDIR/devices.txt"
python3 -m enigma.tools.generate_audio    --config-dir "$CONFIGS" --output "$OUTDIR/audio_events.py" --docs "$DOCDIR/audio.txt"

echo "Generated code -> $OUTDIR/   reference docs -> $DOCDIR/"
