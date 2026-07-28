# SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
# SPDX-License-Identifier: MIT

"""
AN08 board variant handler - 8-channel 10-bit ADC (MCP3008T-I/SL)

Pure analog input board. No LEDs, no buttons, no schemes.
Each channel maps raw ADC values (post firmware pipeline) to a float range.

SETCONFIG payload (10 bytes, stored in NVS):
  control_num(1)  sensor_min_mv(2)  sensor_max_mv(2)  deadband(1)
  gamma_x1000(2)  invert(1)  enabled(1)

  sensor_min_mv / sensor_max_mv are voltage * 1000 (integer millivolts, 0-3300).
  The firmware converts to ADC counts using its known reference voltage.

REPORTSTATE payload (2 bytes):
  raw_value(2) uint16 LE  0-1023, post-pipeline (clamp+remap+gamma+invert)

SETSTATE / SETINDICATOR / SETBLANKING / SETBRIGHTNESS: NOP on this board.
"""

import struct
from .base import BoardVariantHandler, BoardConfig, ControlConfig, ControlState
from . import register_board_variant
from enigma.colors import print_error, print_warning


class AN08ControlState(ControlState):
    """State object for AN08 control.

    Attributes:
        raw:   Post-pipeline ADC value, 0-1023 (firmware has already applied
               sensor remapping, gamma, and invert).
        value: Float mapped to [min_value, max_value] by the host.
    """

    def __init__(self, raw=0, value=None):
        super().__init__(scheme="default")
        self.raw = raw
        self.value = value

    def __str__(self):
        if self.value is not None:
            return f"raw={self.raw}, value={self.value:.4f}"
        return f"raw={self.raw}"

    def __repr__(self):
        return self.__str__()

    def __eq__(self, other):
        if not isinstance(other, AN08ControlState):
            return False
        return self.raw == other.raw


class AN08ControlConfig(ControlConfig):
    """Configuration for one AN08 channel."""

    def __init__(self, control_num, name=None, desc=None,
                 sensor_min_v=0.0, sensor_max_v=3.3, deadband=2,
                 gamma=1.0, invert=False, enabled=True,
                 min_value=0.0, max_value=1.0):
        super().__init__(control_num, name, desc, enabled=enabled)
        self.sensor_min_v = float(sensor_min_v)
        self.sensor_max_v = float(sensor_max_v)
        self.deadband     = int(deadband)
        self.gamma        = float(gamma)
        self.invert       = bool(invert)
        self.min_value    = float(min_value)
        self.max_value    = float(max_value)

    def to_setconfig_payload(self):
        """Pack into SETCONFIG payload bytes (10 bytes).

        Layout:
          control_num(B) sensor_min_mv(H) sensor_max_mv(H) deadband(B)
          gamma_x1000(H) invert(B) enabled(B)

        Voltages are packed as integer millivolts (v * 1000).
        The firmware converts to ADC counts using its known reference voltage.
        """
        sensor_min_mv = int(round(self.sensor_min_v * 1000))
        sensor_max_mv = int(round(self.sensor_max_v * 1000))
        gamma_x1000   = int(round(self.gamma * 1000))
        gamma_x1000   = max(100, min(65535, gamma_x1000))  # guard extremes
        return struct.pack('<BHHBHBB',
                           self.control_num,
                           sensor_min_mv,
                           sensor_max_mv,
                           self.deadband,
                           gamma_x1000,
                           1 if self.invert else 0,
                           1 if self.enabled else 0)

    def raw_to_value(self, raw):
        """Map post-pipeline raw (0-1023) to host float range."""
        norm = raw / 1023.0
        return self.min_value + norm * (self.max_value - self.min_value)

    def get_state_value(self, state_dict):
        """Return human-readable value string (used by logging)."""
        if isinstance(state_dict, dict):
            raw = state_dict.get('raw', 0)
        else:
            raw = int(state_dict)
        return f"{self.raw_to_value(raw):.4f}"


class AN08BoardConfig(BoardConfig):
    """AN08-specific board configuration."""

    VALID_BOARD_KEYS = {'name', 'controls', 'comment'}

    def __init__(self, config_data):
        super().__init__(config_data)

        unknown = set(config_data.keys()) - self.VALID_BOARD_KEYS
        if unknown:
            print_warning(f"WARNING: AN08 board '{self.name}': Unknown keys: {unknown}")


class AN08Handler(BoardVariantHandler):
    """Handler for AN08 (8-channel 10-bit ADC)."""

    VARIANT_ID  = 3
    TYPE_STR    = "AN08"
    NUM_CHANNELS = 8

    def __init__(self, device):
        super().__init__(device)
        self.variant_id = self.VARIANT_ID
        self.type_str   = self.TYPE_STR

    # ------------------------------------------------------------------
    # BoardVariantHandler interface
    # ------------------------------------------------------------------

    def get_control_count(self):
        return self.NUM_CHANNELS

    def create_blank_config(self, control_num):
        """Blank config for unconfigured channels: pass-through defaults, disabled."""
        return AN08ControlConfig(
            control_num,
            name=f"Unused{control_num}",
            desc="Unconfigured channel",
            sensor_min_v=0.0, sensor_max_v=3.3,
            deadband=2, gamma=1.0,
            invert=False, enabled=False,
            min_value=0.0, max_value=1.0,
        )

    def parse_config(self, config_data):
        """Parse AN08 config JSON into AN08BoardConfig."""
        board_config = AN08BoardConfig(config_data)
        controls = config_data.get('controls', [])

        VALID_KEYS = {
            'comment', 'control_num', 'name', 'desc',
            'sensor_min_v', 'sensor_max_v', 'deadband',
            'gamma', 'invert', 'enabled',
            'min_value', 'max_value',
        }

        for ctrl_data in controls:
            try:
                unknown = set(ctrl_data.keys()) - VALID_KEYS
                if unknown:
                    print_warning(f"WARNING: AN08 control: Unknown keys: {unknown}")

                control_num = ctrl_data.get('control_num')
                if not control_num or control_num < 1 or control_num > self.NUM_CHANNELS:
                    print_error(f"[enigma] ERROR: AN08: Invalid control_num: {control_num}")
                    continue

                name          = ctrl_data.get('name')
                if not name:
                    print_error(f"[enigma] ERROR: AN08 CH{control_num}: 'name' is required. Skipping.")
                    continue
                desc          = ctrl_data.get('desc', '')
                sensor_min_v  = float(ctrl_data.get('sensor_min_v', 0.0))
                sensor_max_v  = float(ctrl_data.get('sensor_max_v', 3.3))
                deadband      = ctrl_data.get('deadband', 2)
                gamma         = ctrl_data.get('gamma', 1.0)
                invert        = ctrl_data.get('invert', False)
                enabled       = ctrl_data.get('enabled', True)
                min_value     = float(ctrl_data.get('min_value', 0.0))
                max_value     = float(ctrl_data.get('max_value', 1.0))

                # --- Validation ---
                if not (0.0 <= sensor_min_v <= 3.3):
                    print_error(f"[enigma] ERROR: AN08 CH{control_num}: sensor_min_v {sensor_min_v} out of [0.0, 3.3]. Defaulting to 0.0.")
                    sensor_min_v = 0.0
                if not (0.0 <= sensor_max_v <= 3.3):
                    print_error(f"[enigma] ERROR: AN08 CH{control_num}: sensor_max_v {sensor_max_v} out of [0.0, 3.3]. Defaulting to 3.3.")
                    sensor_max_v = 3.3
                if sensor_max_v <= sensor_min_v:
                    print_error(f"[enigma] ERROR: AN08 CH{control_num}: sensor_max_v ({sensor_max_v}) must be > sensor_min_v ({sensor_min_v}). Resetting to defaults.")
                    sensor_min_v, sensor_max_v = 0.0, 3.3
                if not (0 <= deadband <= 255):
                    print_warning(f"WARNING: AN08 CH{control_num}: deadband {deadband} out of [0,255]. Defaulting to 2.")
                    deadband = 2
                if gamma <= 0:
                    print_warning(f"WARNING: AN08 CH{control_num}: gamma must be > 0, got {gamma}. Defaulting to 1.0.")
                    gamma = 1.0
                if not isinstance(invert, bool):
                    print_warning(f"WARNING: AN08 CH{control_num}: 'invert' must be true/false, got {invert!r}. Defaulting to false.")
                    invert = False
                if min_value >= max_value:
                    print_error(f"[enigma] ERROR: AN08 CH{control_num}: min_value ({min_value}) must be < max_value ({max_value}). Swapping.")
                    min_value, max_value = max_value, min_value

                control = AN08ControlConfig(
                    control_num, name, desc,
                    sensor_min_v, sensor_max_v, deadband,
                    gamma, invert, enabled,
                    min_value, max_value,
                )
                board_config.controls[control_num] = control

            except Exception as e:
                print_error(f"[enigma] Error parsing AN08 control {ctrl_data.get('control_num')}: {e}")
                import traceback
                traceback.print_exc()

        return board_config

    # ------------------------------------------------------------------
    # Low-level pack / parse
    # ------------------------------------------------------------------

    def _pack_state(self, control_state):
        """Pack AN08ControlState into bytes (used by set_control_state, effectively a NOP)."""
        if not isinstance(control_state, AN08ControlState):
            raise TypeError(f"Expected AN08ControlState, got {type(control_state).__name__}")
        return struct.pack('<H', min(1023, max(0, control_state.raw)))

    def _parse_state(self, state_data, control_num=None):
        """Parse 2-byte REPORTSTATE payload into AN08ControlState."""
        if len(state_data) < 2:
            return AN08ControlState(raw=0)

        raw = struct.unpack_from('<H', state_data, 0)[0]
        raw = min(1023, raw)

        value = None
        if control_num and self.config:
            cfg = self.config.controls.get(control_num)
            if cfg:
                value = cfg.raw_to_value(raw)

        return AN08ControlState(raw=raw, value=value)

    # ------------------------------------------------------------------
    # High-level overrides
    # ------------------------------------------------------------------

    def set_control_by_value(self, control_num, value):
        """AN08 is read-only hardware - SETSTATE is a NOP."""
        return False

    def reset(self, full_reset=False, send_to_hardware=True):
        """AN08 has no output state to reset."""
        super().reset(full_reset=full_reset)


# Register this variant
register_board_variant(AN08Handler.VARIANT_ID, AN08Handler.TYPE_STR, AN08Handler)
