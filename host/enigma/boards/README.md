# enigma.boards

Host-side drivers for each board variant. A driver parses that board's JSON
config, serializes config and state to the firmware's wire format, and decodes
incoming reports.

- `sw14.py`: illuminated switches with RGB indicators
- `qd04.py`: quadrature encoders with LED rings
- `an08.py`: analog inputs
- `thrustmaster.py`, `gpro.py`: the two supported third-party inputs

To add support for a new board type, see
[NEW_BOARD_HANDLER.md](../docs/NEW_BOARD_HANDLER.md). The wire format is in
[HID_PROTOCOL.md](../docs/HID_PROTOCOL.md).
