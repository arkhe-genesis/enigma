# SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
# SPDX-License-Identifier: MIT

"""
Thrustmaster T.16000M board variant handler
"""

import struct
from enum import IntEnum
from .base import BoardVariantHandler, BoardConfig, ControlConfig, ControlState
from . import register_board_variant
from enigma.colors import print_error, print_warning

# Thrustmaster VID/PID
THRUSTMASTER_VID = 0x044f
THRUSTMASTER_PID = 0xb10a

# Control types
class ControlType(IntEnum):
    AXIS = 0
    BUTTON = 1
    HAT = 2

# Hat direction encoding to bitset mapping
# Input: 0=up, 1=up-right, 2=right, 3=down-right, 4=down, 5=down-left, 6=left, 7=up-left, F=center
# Output: bit 0=up, bit 1=right, bit 2=down, bit 3=left
HAT_TO_BITSET = {
    0x0: 0b0001,  # up
    0x1: 0b0011,  # up-right
    0x2: 0b0010,  # right
    0x3: 0b0110,  # down-right
    0x4: 0b0100,  # down
    0x5: 0b1100,  # down-left
    0x6: 0b1000,  # left
    0x7: 0b1001,  # up-left
    0xF: 0b0000,  # center
}

class ThrustmasterControlState(ControlState):
    """State object for Thrustmaster control
    
    Attributes:
        value: Control value (float for axis, bool for button, int bitset for hat)
        scheme: Always "default" for Thrustmaster (included for uniformity)
    
    For axes: value is -1.0 to 1.0
    For buttons: value is True/False
    For hat: value is bitset (bit0=up, bit1=right, bit2=down, bit3=left)
    """
    
    def __init__(self, value=None, scheme="default"):
        super().__init__(scheme=scheme)
        self.value = value
    
    def __str__(self):
        """String representation for debugging/CLI"""
        if isinstance(self.value, float):
            # Axis
            return f"{self.value:.4f}"
        elif isinstance(self.value, bool):
            # Button
            return "pressed" if self.value else "released"
        elif isinstance(self.value, int):
            # Hat bitset
            dirs = []
            if self.value & 0b0001:
                dirs.append("up")
            if self.value & 0b0010:
                dirs.append("right")
            if self.value & 0b0100:
                dirs.append("down")
            if self.value & 0b1000:
                dirs.append("left")
            return "+".join(dirs) if dirs else "center"
        else:
            return str(self.value)
    
    def __eq__(self, other):
        if not isinstance(other, ThrustmasterControlState):
            return False
        return self.value == other.value

class ThrustmasterControlConfig(ControlConfig):
    """Configuration for a Thrustmaster control"""
    
    def __init__(self, control_num, name=None, desc=None, control_type=ControlType.BUTTON,
                 report_byte=None, report_bytes=None, bit=None, deadzone=0.0, enabled=True):
        super().__init__(control_num, name, desc, enabled=enabled)
        self.control_type = control_type
        self.report_byte = report_byte
        self.report_bytes = report_bytes  # For multi-byte values like axes
        self.bit = bit  # For button bits
        self.deadzone = deadzone
        self.last_value = None  # Track last value for change detection
    
    def to_setconfig_payload(self):
        """Thrustmaster is read-only, no config to send"""
        return b''
    
    def get_state_value(self, state_dict):
        """Get value string for state reporting"""
        # state_dict is actually a ThrustmasterControlState object when called from format_state_change
        if isinstance(state_dict, ThrustmasterControlState):
            return str(state_dict)
        # Fallback for dict
        return str(state_dict.get('value'))
    
    def parse_from_report(self, report):
        """Parse this control's value from a raw HID report
        
        Returns:
            ThrustmasterControlState if value changed, None otherwise
        """
        if self.control_type == ControlType.AXIS:
            if self.report_bytes and len(self.report_bytes) == 2:
                # 16-bit axis (X, Y)
                if len(report) > max(self.report_bytes):
                    raw = struct.unpack('<H', bytes([report[self.report_bytes[0]], 
                                                     report[self.report_bytes[1]]]))[0]
                    value = (raw - 8192) / 8192.0

                    # Apply deadzone with smooth scaling
                    if abs(value) < self.deadzone:
                        value = 0.0
                    elif self.deadzone < 1.0:
                        # Scale remaining range to 0..1 / -1..0
                        if value > 0:
                            value = (value - self.deadzone) / (1.0 - self.deadzone)
                        else:
                            value = (value + self.deadzone) / (1.0 - self.deadzone)

                    # Check for change
                    if self.last_value is None or abs(value - self.last_value) > 0.001:
                        self.last_value = value
                        return ThrustmasterControlState(value=value)
            elif self.report_byte is not None:
                # 8-bit axis (Z/twist)
                if len(report) > self.report_byte:
                    raw = report[self.report_byte]
                    value = (raw - 128) / 128.0

                    # Apply deadzone with smooth scaling
                    if abs(value) < self.deadzone:
                        value = 0.0
                    elif self.deadzone < 1.0:
                        # Scale remaining range to 0..1 / -1..0
                        if value > 0:
                            value = (value - self.deadzone) / (1.0 - self.deadzone)
                        else:
                            value = (value + self.deadzone) / (1.0 - self.deadzone)

                    # Check for change
                    if self.last_value is None or abs(value - self.last_value) > 0.001:
                        self.last_value = value
                        return ThrustmasterControlState(value=value)
        
        elif self.control_type == ControlType.BUTTON:
            if self.report_byte is not None and self.bit is not None:
                if len(report) > self.report_byte:
                    value = bool(report[self.report_byte] & (1 << self.bit))
                    
                    # Check for change
                    if self.last_value is None or value != self.last_value:
                        self.last_value = value
                        return ThrustmasterControlState(value=value)
        
        elif self.control_type == ControlType.HAT:
            if self.report_byte is not None:
                if len(report) > self.report_byte:
                    hat_byte = report[self.report_byte]
                    hat_direction = hat_byte & 0x0F

                    # Convert to bitset
                    value = HAT_TO_BITSET.get(hat_direction, 0)

                    # Check for change
                    if self.last_value is None or value != self.last_value:
                        self.last_value = value
                        return ThrustmasterControlState(value=value)
        
        return None  # No change

class ThrustmasterBoardConfig(BoardConfig):
    """Thrustmaster-specific board configuration"""
    
    def __init__(self, config_data):
        super().__init__(config_data)
        self.side_switch = config_data.get('side_switch', 0)
    
    def format_state_change(self, control_num, control_state):
        """Override to handle ThrustmasterControlState objects"""
        control = self.get_control(control_num)
        if not control:
            return f"{self.name}.Control{control_num} = {control_state}"
        
        # control_state is a ThrustmasterControlState object
        return f"{self.name}.{control.name} = {control_state}"

class ThrustmasterHandler(BoardVariantHandler):
    """Handler for Thrustmaster T.16000M joystick"""
    
    VARIANT_ID = 255  # Use 255 for non-Enigma devices
    TYPE_STR = "T16K"
    NUM_CONTROLS = 8  # 3 axes + 4 buttons + 1 hat
    
    def __init__(self, device):
        super().__init__(device)
        self.variant_id = self.VARIANT_ID
        self.type_str = self.TYPE_STR
        self.side_switch_value = None  # Will be set on first report
    
    def create_blank_config(self, control_num):
        """Thrustmaster doesn't need blank configs"""
        return ThrustmasterControlConfig(control_num, name=f"Control{control_num}")
    
    def parse_config(self, config_data):
        """Parse Thrustmaster config JSON"""
        board_config = ThrustmasterBoardConfig(config_data)
        
        controls = config_data.get('controls', [])
        
        VALID_CONTROL_KEYS = {'comment', 'control_num', 'name', 'desc', 'type',
                             'report_byte', 'report_bytes', 'bit', 'deadzone', 'enabled'}
        
        for ctrl_data in controls:
            try:
                # Validate control keys
                unknown_keys = set(ctrl_data.keys()) - VALID_CONTROL_KEYS
                if unknown_keys:
                    print_warning(f"WARNING: Thrustmaster control config: Unknown keys: {unknown_keys}")
                
                control_num = ctrl_data.get('control_num')
                if not control_num or control_num < 1 or control_num > self.NUM_CONTROLS:
                    print_error(f"[enigma] ERROR: Invalid control_num: {control_num}")
                    continue
                
                name = ctrl_data.get('name')
                desc = ctrl_data.get('desc')
                
                # Parse type
                type_str = ctrl_data.get('type', 'button').lower()
                type_map = {
                    'axis': ControlType.AXIS,
                    'button': ControlType.BUTTON,
                    'hat': ControlType.HAT
                }
                if type_str not in type_map:
                    print_error(f"[enigma] ERROR: Control {control_num}: Invalid type '{type_str}'. "
                          f"Valid types: {list(type_map.keys())}. Defaulting to 'button'")
                    type_str = 'button'
                control_type = type_map[type_str]
                
                # Parse report byte(s)
                report_byte = ctrl_data.get('report_byte')
                report_bytes = ctrl_data.get('report_bytes')
                bit = ctrl_data.get('bit')
                deadzone = ctrl_data.get('deadzone', 0.0)
                enabled = ctrl_data.get('enabled', True)

                # Validate configuration
                if control_type == ControlType.AXIS:
                    if not report_bytes and not report_byte:
                        print_error(f"[enigma] ERROR: Control {control_num}: Axis requires 'report_byte' or 'report_bytes'")
                        continue
                elif control_type == ControlType.BUTTON:
                    if report_byte is None or bit is None:
                        print_error(f"[enigma] ERROR: Control {control_num}: Button requires 'report_byte' and 'bit'")
                        continue
                elif control_type == ControlType.HAT:
                    if report_byte is None:
                        print_error(f"[enigma] ERROR: Control {control_num}: Hat requires 'report_byte'")
                        continue
                
                control = ThrustmasterControlConfig(
                    control_num, name, desc, control_type,
                    report_byte, report_bytes, bit, deadzone, enabled=enabled
                )
                
                board_config.controls[control_num] = control
                
            except Exception as e:
                print_error(f"[enigma] Error parsing control {ctrl_data.get('control_num')}: {e}")
                import traceback
                traceback.print_exc()
        
#        print(f"Loaded config '{board_config.name}' with {len(board_config.controls)} controls")
        return board_config
    
    def process_report(self, report):
        """Process raw HID report and trigger state changes

        Args:
            report: bytes of HID report (9 bytes for T.16000M)

        Returns:
            True if report should be processed (side_switch matches address)
        """
        if len(report) < 9:
            return False

        # Check side switch (bit 5 of byte 2)
        report_side_switch = (report[2] & 0x20) >> 5

        # Store side_switch value on first report
        if self.side_switch_value is None:
            self.side_switch_value = report_side_switch

        # Note: We no longer filter by side_switch here.
        # The device was identified by side_switch on first report, so if user
        # flips the switch mid-session, reports would be rejected. Since each
        # physical stick has its own USB path and device object, filtering isn't
        # needed for multi-stick setups either.

        # Process each control
        if not self.config:
            print_warning(f"WARNING: Thrustmaster handler has no config!")
            return False

        for control_num, control in self.config.controls.items():
            # Skip disabled controls
            if not self.is_control_enabled(control_num):
                continue

            control_state = control.parse_from_report(report)

            if control_state is not None:
                # Value changed - store and trigger callback
                self.device.current_states[control_num] = control_state

                # Call device's state change handler
                if hasattr(self.device, 'on_state_change'):
                    # Pack state for compatibility (handler expects bytes)
                    state_data = self._pack_state(control_state)
                    self.device.on_state_change(control_num, state_data)

        return True
    
    # Low-level pack/parse (internal use)
    
    def _pack_state(self, control_state):
        """Pack ThrustmasterControlState into bytes"""
        if not isinstance(control_state, ThrustmasterControlState):
            raise TypeError(f"Expected ThrustmasterControlState, got {type(control_state).__name__}")
        
        value = control_state.value
        
        if isinstance(value, float):
            # Pack float as 4 bytes
            return struct.pack('<f', value)
        elif isinstance(value, bool):
            # Pack bool as 1 byte
            return struct.pack('<B', 1 if value else 0)
        elif isinstance(value, int):
            # Pack int as 1 byte
            return struct.pack('<B', value)
        else:
            return b'\x00'
    
    def _parse_state(self, state_data, control_num=None):
        """Parse bytes into ThrustmasterControlState"""
        if len(state_data) == 4:
            # Float (axis)
            value = struct.unpack('<f', state_data)[0]
        elif len(state_data) == 1:
            byte_val = state_data[0]
            # Check control type if we have the config
            if control_num is not None and self.config:
                control = self.config.controls.get(control_num)
                if control:
                    if control.control_type == ControlType.BUTTON:
                        value = bool(byte_val)
                    elif control.control_type == ControlType.HAT:
                        value = byte_val  # Hat bitset, keep as int
                    else:
                        value = byte_val
                else:
                    # Fallback heuristic
                    value = bool(byte_val) if byte_val in (0, 1) else byte_val
            else:
                # Fallback heuristic
                value = bool(byte_val) if byte_val in (0, 1) else byte_val
        else:
            value = None

        return ThrustmasterControlState(value=value)
    
    def get_control_count(self):
        return self.NUM_CONTROLS
    
    def calculate_config_crc(self):
        """Thrustmaster devices don't have config CRC - always return 0"""
        return 0x00000000
    
    def get_control_value(self, control_num):
        """Get the last cached value for a control
        
        Args:
            control_num: Control number to query
            
        Returns:
            ThrustmasterControlState or None if no value yet
        """
        if not self.config:
            return None
        
        control = self.config.get_control(control_num)
        if not control or control.last_value is None:
            return None
        
        return ThrustmasterControlState(value=control.last_value)
    
    # Thrustmaster is read-only, so set_control_state raises an error
    
    def set_control_state(self, control_num, control_state):
        """Thrustmaster devices are read-only - silently does nothing"""
        return False
    
    def set_control_by_value(self, control_num, value):
        """Thrustmaster devices are read-only - silently does nothing"""
        return False

# Register this variant
register_board_variant(ThrustmasterHandler.VARIANT_ID, ThrustmasterHandler.TYPE_STR, ThrustmasterHandler)
