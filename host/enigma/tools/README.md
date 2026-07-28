# enigma.tools

Code generators and command-line utilities.

- `generate_controls.py`, `generate_devices.py`, `generate_audio.py`: turn the
  JSON configs into Python classes and reference docs. Run all three via
  [`mk.sh`](../../mk.sh); see [CODE_GENERATION.md](../docs/CODE_GENERATION.md).
- `enigma_cli.py`: inspect and exercise connected boards from a shell.
- `hid_monitor.py`: watch raw HID traffic to and from a board.
- `gpro-daemon-*.sh`: build, install, and manage the G Pro keyboard daemon.
