# enigma (package)

The importable Enigma library. See the [host README](../README.md) for install
instructions and the full package map; start with [`docs/`](docs/) for reference
documentation.

- [`docs/`](docs/): design guide, board configs, wire protocol, API reference
- [`audio/`](audio/): the layered audio engine
- [`boards/`](boards/): per-board drivers (SW14, QD04, AN08, plus stick and keyboard)
- [`tools/`](tools/): code generators and command-line utilities
- Core modules: `manager.py`, `config.py`, `device.py`, `panelmanager.py`,
  `displaymanager.py`, `hid_protocol.py`, `colors.py`, `control_value.py`
