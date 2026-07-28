# Examples

Runnable examples of building with the Enigma host library. Both drive the same
`PortEngineSpec` onto the same web display; they differ only in where the values
come from.

- [`engine-sw/`](engine-sw/): the **output** side, no hardware. A real enigma app
  (an `EnigmaManager` plus a device that owns a spec), its JSON spec and display
  config, a Flask browser display, a Unity receiver, and optional audio. A synthetic
  device animates the values, and an interactive controls page lets you drive them
  by hand. The smallest full "state to screen" slice of Enigma.
- [`engine-full/`](engine-full/): the **input+output** side. The same spec and display, now
  driven by real Enigma boards (an AN08 pot, an SW14 switch panel, a QD04 encoder)
  read through a generated panel. Shows control-to-spec reading, LED schemes, and
  runtime enable/disable off the spec state. Needs the boards; to play without
  hardware, use engine-sw's controls page.

## Elsewhere in the repo
- [Host library](../README.md): the package these examples use
- [Documentation](../enigma/docs/): config formats, code generation, API reference
- [Repository overview](../../README.md): what Enigma is, top-level map
