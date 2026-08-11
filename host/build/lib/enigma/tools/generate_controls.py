#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
# SPDX-License-Identifier: MIT

"""
generate_controls.py - Generate type-safe control constants from config files

Generates instance-based controls with .value and .scheme properties for clean syntax.

Usage:
    python tools/generate_controls.py --config-dir configs/ --output controls.py
"""

import argparse
import json
import signal
from pathlib import Path
from typing import Dict, Set, List
import sys

# Add project root to path for imports
_script_path = Path(__file__).resolve()
_project_root = _script_path.parent.parent.parent
sys.path.insert(0, str(_project_root))

from enigma.colors import print_error, print_warning

from enigma.config import ConfigManager
from enigma.boards import get_board_handler


def sanitize_class_name(name: str) -> str:
    """Convert a name to a valid Python class name preserving case"""
    # Remove spaces and invalid characters, preserve case
    sanitized = ''.join(c if c.isalnum() else '' for c in name)
    # Ensure doesn't start with digit
    if sanitized and sanitized[0].isdigit():
        sanitized = '_' + sanitized
    return sanitized


def sanitize_identifier(name: str) -> str:
    """Convert a name to a valid Python identifier (uppercase)"""
    # Replace invalid characters with underscore
    sanitized = ''.join(c if c.isalnum() else '_' for c in name)
    # Ensure doesn't start with digit
    if sanitized[0].isdigit():
        sanitized = '_' + sanitized
    return sanitized.upper()


def generate_control_class(control, device_class_name: str, board_type: str, board_id: str, control_list: List = None) -> List[str]:
    """Generate an instance-based control class

    Args:
        control: Primary control config (used for name, desc)
        device_class_name: Name of parent device class
        board_type: Board type (SW14, QD04, etc)
        board_id: The board ID this control lives on
        control_list: Optional list of all controls with same name (for merging values)
    """

    if control_list is None:
        control_list = [control]

    control_name = control.name
    class_name = sanitize_class_name(control_name)

    # Use a generic description if multiple controls, otherwise use first control's desc
    if len(control_list) > 1:
        description = f"{control_name} control ({len(control_list)} physical controls)"
    else:
        description = control.desc or control_name

    lines = []
    lines.append(f"class _{class_name}(ControlValue):")
    lines.append(f'    """Control: {description}"""')
    lines.append(f'    NAME = "{control_name}"')
    lines.append(f'    BOARD_ID = "{board_id}"')
    if board_type in ('QD04', 'AN08') and hasattr(control, 'min_value') and hasattr(control, 'max_value'):
        lines.append(f'    MIN = {control.min_value!r}')
        lines.append(f'    MAX = {control.max_value!r}')
    lines.append("")
    lines.append("    def __init__(self, device_class):")
    lines.append("        self._device_class = device_class")
    lines.append("        self._last_value = None")
    lines.append("        self._changed_this_cycle = False")
    lines.append("        self._hardware_origin = False")
    if board_type == 'QD04':
        lines.append("        self._last_button = None")
        lines.append("        self._button_changed_this_cycle = False")
    lines.append("")

    # Collect values from states across ALL controls with this name
    values = {}
    for ctrl in control_list:
        if hasattr(ctrl, 'states'):
            for state_num, state in ctrl.states.items():
                if hasattr(state, 'value') and state.value:
                    # Store all unique values
                    if state.value not in values:
                        values[state.value] = state_num

    # Generate Values class
    if values:
        lines.append("    class Values:")
        for value in sorted(values.keys()):
            value_const = sanitize_identifier(value)
            lines.append(f'        {value_const} = "{value}"')
        lines.append("")

    # Collect schemes for this control across ALL controls with this name
    control_schemes = set(['default'])
    for ctrl in control_list:
        if hasattr(ctrl, 'schemes'):
            control_schemes.update(ctrl.schemes.keys())

    # Generate control-level Schemes class
    if control_schemes:
        lines.append("    class Schemes:")
        for scheme in sorted(control_schemes):
            scheme_const = sanitize_identifier(scheme)
            lines.append(f'        {scheme_const} = "{scheme}"')
        lines.append("")

    # Value property (get/set)
    lines.append("    @property")
    lines.append("    def value(self):")
    lines.append('        """Get current value"""')
    lines.append("        from enigma.manager import get_manager")
    lines.append(f"        val = get_manager().get_control_value(self._device_class.NAME, self.NAME)")
    lines.append("        return val")
    lines.append("")
    lines.append("    @value.setter")
    lines.append("    def value(self, val):")
    lines.append('        """Set value"""')
    lines.append("        from enigma.manager import get_manager")
    lines.append(f"        get_manager().set_control_value(self._device_class.NAME, self.NAME, val)")
    lines.append("")

    # For AN08, add raw property (integer 0-1023, used for changed() tracking)
    if board_type == 'AN08':
        lines.append("    @property")
        lines.append("    def raw(self):")
        lines.append('        """Get raw post-pipeline ADC value (0-1023). None if device disconnected."""')
        lines.append("        from enigma.manager import get_manager")
        lines.append(f"        device = get_manager().get_device(self.BOARD_ID)")
        lines.append("        if not device or not device.handler or not device.handler.config:")
        lines.append("            return None")
        lines.append(f"        ctrl = device.handler.config.get_control_by_name(self.NAME)")
        lines.append("        if not ctrl:")
        lines.append("            return None")
        lines.append(f"        state = device.get_control_state(ctrl.control_num)")
        lines.append("        if state:")
        lines.append(f"            parsed = device.handler._parse_state(state, ctrl.control_num)")
        lines.append("            return parsed.raw")
        lines.append("        return 0")
        lines.append("")

    # For QD04, add button and position properties
    if board_type == 'QD04':
        lines.append("    @property")
        lines.append("    def button(self):")
        lines.append('        """Get button state: 0=released, 1=pressed, None=device disconnected"""')
        lines.append("        from enigma.manager import get_manager")
        lines.append(f"        device = get_manager().get_device(self.BOARD_ID)")
        lines.append("        if not device or not device.handler:")
        lines.append("            return None  # Device disconnected")
        lines.append(f"        control_num = device.handler.config.get_control_by_name(self.NAME).control_num")
        lines.append(f"        state = device.get_control_state(control_num)")
        lines.append("        if state:")
        lines.append("            parsed = device.handler._parse_state(state, control_num)")
        lines.append("            return parsed.button")
        lines.append("        return 0")
        lines.append("")
        lines.append("    @button.setter")
        lines.append("    def button(self, val):")
        lines.append('        """Set button state: 0 or 1"""')
        lines.append("        from enigma.manager import get_manager")
        lines.append(f"        device = get_manager().get_device(self.BOARD_ID)")
        lines.append("        if device and device.handler:")
        lines.append(f"            control_num = device.handler.config.get_control_by_name(self.NAME).control_num")
        lines.append(f"            state = device.get_control_state(control_num)")
        lines.append("            position = 0")
        lines.append("            if state:")
        lines.append("                parsed = device.handler._parse_state(state, control_num)")
        lines.append("                position = parsed.position")
        lines.append("            from enigma.boards.qd04 import QD04ControlState")
        lines.append("            device.handler.set_control_state(control_num, QD04ControlState(position=position, button=int(val)))")
        lines.append("")
        lines.append("    def button_changed(self):")
        lines.append('        """Check if button changed this update cycle"""')
        lines.append("        # If we already detected a change this cycle, return True")
        lines.append("        if self._button_changed_this_cycle:")
        lines.append("            return True")
        lines.append("        ")
        lines.append("        # Check if button changed")
        lines.append("        current = self.button")
        lines.append("        if current is None:")
        lines.append("            return False  # Device disconnected, don't report as change")
        lines.append("        if self._last_button is None:")
        lines.append("            self._last_button = current")
        lines.append("            return False")
        lines.append("        ")
        lines.append("        if current != self._last_button:")
        lines.append("            self._last_button = current")
        lines.append("            self._button_changed_this_cycle = True")
        lines.append("            return True")
        lines.append("        ")
        lines.append("        return False")
        lines.append("")
        lines.append("    @property")
        lines.append("    def position(self):")
        lines.append('        """Get encoder position (0 to num_leds-1, or tracked position for incremental). None if device disconnected."""')
        lines.append("        from enigma.manager import get_manager")
        lines.append(f"        device = get_manager().get_device(self.BOARD_ID)")
        lines.append("        if not device or not device.handler:")
        lines.append("            return None  # Device disconnected")
        lines.append(f"        control_num = device.handler.config.get_control_by_name(self.NAME).control_num")
        lines.append(f"        state = device.get_control_state(control_num)")
        lines.append("        if state:")
        lines.append("            parsed = device.handler._parse_state(state, control_num)")
        lines.append("            return parsed.position")
        lines.append("        return 0")
        lines.append("")

    # Scheme property (set only)
    lines.append("    @property")
    lines.append("    def Scheme(self):")
    lines.append('        """Scheme property (write-only)"""')
    lines.append("        return None")
    lines.append("")
    lines.append("    @Scheme.setter")
    lines.append("    def Scheme(self, val):")
    lines.append('        """Set indicator scheme"""')
    lines.append("        from enigma.manager import get_manager")
    lines.append(f"        device = get_manager().get_device(self.BOARD_ID)")
    lines.append("        if device and device.handler:")
    lines.append(f"            device.handler.set_indicator_scheme(val, self.NAME)")
    lines.append("")

    # Enabled property (get/set)
    lines.append("    @property")
    lines.append("    def Enabled(self):")
    lines.append('        """Check if control is enabled (reports state changes)"""')
    lines.append("        from enigma.manager import get_manager")
    lines.append(f"        device = get_manager().get_device(self.BOARD_ID)")
    lines.append("        if device and device.handler and device.handler.config:")
    lines.append(f"            ctrl = device.handler.config.get_control_by_name(self.NAME)")
    lines.append("            if ctrl:")
    lines.append("                return device.handler.is_control_enabled(ctrl.control_num)")
    lines.append("        return True")
    lines.append("")
    lines.append("    @Enabled.setter")
    lines.append("    def Enabled(self, val):")
    lines.append('        """Enable or disable control (affects state change reporting)"""')
    lines.append("        from enigma.manager import get_manager")
    lines.append(f"        device = get_manager().get_device(self.BOARD_ID)")
    lines.append("        if device and device.handler:")
    lines.append("            if val:")
    lines.append(f"                device.handler.enable_controls_by_name([self.NAME])")
    lines.append("            else:")
    lines.append(f"                device.handler.disable_controls_by_name([self.NAME])")
    lines.append("")

    # Changed method - use position for QD04, raw for AN08, value for others
    lines.append("    def changed(self, hardware_only=False):")
    lines.append('        """Check if value changed this update cycle.')
    lines.append('        If hardware_only=True, only returns True for changes from physical controls,')
    lines.append('        not programmatic sets."""')
    lines.append("        # If we already detected a change this cycle, check origin filter")
    lines.append("        if self._changed_this_cycle:")
    lines.append("            if hardware_only:")
    lines.append("                return self._hardware_origin")
    lines.append("            return True")
    lines.append("        ")
    lines.append("        # Check if value changed")
    if board_type == 'QD04':
        lines.append("        current = self.position  # Use position for encoder")
    elif board_type == 'AN08':
        lines.append("        current = self.raw  # Use integer raw for reliable change detection")
    else:
        lines.append("        current = self.value")
    lines.append("        if current is None:")
    lines.append("            return False  # Device disconnected, don't report as change")
    lines.append("        if self._last_value is None:")
    lines.append("            self._last_value = current")
    lines.append("            return False  # First check doesn't count as change")
    lines.append("        ")
    lines.append("        if current != self._last_value:")
    lines.append("            self._last_value = current")
    lines.append("            self._changed_this_cycle = True")
    lines.append("            # Check if this change originated from hardware")
    lines.append("            self._hardware_origin = self._check_hardware_origin()")
    lines.append("            if hardware_only:")
    lines.append("                return self._hardware_origin")
    lines.append("            return True")
    lines.append("        ")
    lines.append("        return False")
    lines.append("")

    # Hardware origin check helper
    lines.append("    def _check_hardware_origin(self):")
    lines.append('        """Check if any physical control with this name had a hardware change."""')
    lines.append("        from enigma.manager import get_manager")
    lines.append(f"        device = get_manager().get_device(self.BOARD_ID)")
    lines.append("        if not device or not device.handler or not device.handler.config:")
    lines.append("            return False")
    lines.append("        for cnum, cfg in device.handler.config.controls.items():")
    lines.append("            if cfg.name == self.NAME and device.handler.is_hardware_changed(cnum):")
    lines.append("                return True")
    lines.append("        return False")
    lines.append("")


    # String representation
    if board_type == 'QD04':
        lines.append("    def __str__(self):")
        lines.append('        """String representation"""')
        lines.append("        return f\"pos={self.position}, btn={self.button}\"")
        lines.append("")
        lines.append("    def __repr__(self):")
        lines.append('        """Debug representation"""')
        lines.append("        return f\"{self.NAME}(pos={self.position}, btn={self.button})\"")
        lines.append("")
    elif board_type == 'AN08':
        lines.append("    def __str__(self):")
        lines.append('        """String representation"""')
        lines.append("        v = self.value")
        lines.append("        return f\"raw={self.raw}, value={v:.4f}\" if v is not None else f\"raw={self.raw}\"")
        lines.append("")
        lines.append("    def __repr__(self):")
        lines.append('        """Debug representation"""')
        lines.append("        return f\"{self.NAME}(raw={self.raw})\"")
        lines.append("")
    else:
        lines.append("    def __str__(self):")
        lines.append('        """String representation"""')
        lines.append("        return str(self.value)")
        lines.append("")
        lines.append("    def __repr__(self):")
        lines.append('        """Debug representation"""')
        lines.append("        return f\"{self.NAME}={self.value}\"")
        lines.append("")

    return lines


def get_board_type(board_id: str) -> str:
    """Determine board type from board_id"""
    if board_id.startswith('SW14-'):
        return 'SW14'
    elif board_id.startswith('QD04-') or board_id.startswith('QD08-'):
        return 'QD04'
    elif board_id.startswith('AN08-'):
        return 'AN08'
    elif board_id.startswith('T16K-'):
        return 'T16K'
    else:
        return 'UNKNOWN'


def generate_device_class(device_name: str, board_configs: List[dict]) -> str:
    """Generate a device class with controls aggregated from multiple boards

    Args:
        device_name: The shared name for this device (from config "name" field)
        board_configs: List of (board_id, board_type, board_config) tuples
    """

    class_name = sanitize_class_name(device_name)
    board_ids = [bc[0] for bc in board_configs]

    lines = []
    lines.append(f"class _{class_name}(_DeviceBase):")
    if len(board_configs) > 1:
        lines.append(f'    """Auto-generated from {len(board_configs)} boards: {", ".join(board_ids)}"""')
    else:
        lines.append(f'    """Auto-generated from {device_name}.json"""')
    lines.append(f'    NAME = "{device_name}"')
    lines.append(f'    BOARD_IDS = {board_ids}')
    lines.append("")

    # Collect all schemes across all controls from all boards
    all_schemes = set(['default'])
    for board_id, board_type, board_config in board_configs:
        for control_num, control in board_config.controls.items():
            if hasattr(control, 'schemes'):
                all_schemes.update(control.schemes.keys())

    # Generate device-level Schemes class
    if all_schemes:
        lines.append("    class Schemes:")
        for scheme in sorted(all_schemes):
            scheme_const = sanitize_identifier(scheme)
            lines.append(f'        {scheme_const} = "{scheme}"')
        lines.append("")

    # Device-level scheme property - loops through all boards
    lines.append("    @property")
    lines.append("    def Scheme(self):")
    lines.append('        """Scheme property (write-only)"""')
    lines.append("        return None")
    lines.append("")
    lines.append("    @Scheme.setter")
    lines.append("    def Scheme(self, val):")
    lines.append('        """Set scheme for all controls on all boards"""')
    lines.append("        from enigma.manager import get_manager")
    lines.append("        for board_id in self.BOARD_IDS:")
    lines.append("            device = get_manager().get_device(board_id)")
    lines.append("            if device and device.handler:")
    lines.append("                device.handler.set_indicator_scheme(val)")
    lines.append("")

    # Device-level enable/disable methods
    # Note: enable_all(), disable_all(), enable(), disable(), pop_enable() inherited from _DeviceBase

    # Collect controls from all boards, grouping by name
    # Each entry: control_name -> [(board_id, board_type, control), ...]
    controls_by_name = {}
    for board_id, board_type, board_config in board_configs:
        for control_num in sorted(board_config.controls.keys()):
            control = board_config.controls[control_num]
            if control.name not in controls_by_name:
                controls_by_name[control.name] = []
            controls_by_name[control.name].append((board_id, board_type, control))

    # all_controls(): every control object in the panel, across all boards.
    # Handy for panel-wide operations (e.g. disabling everything but a few).
    _all_control_names = sorted(controls_by_name.keys())
    lines.append("    def all_controls(self):")
    lines.append('        """Return every control in this panel, across all boards.')
    lines.append("")
    lines.append("        A control that spans multiple boards appears once. Useful for")
    lines.append("        panel-wide operations such as disabling everything but a few.")
    lines.append('        """')
    lines.append("        return [" + ", ".join(f"self.{n}" for n in _all_control_names) + "]")
    lines.append("")

    # Validate: warn about duplicate control names (but allow grouped controls)
    for control_name, entries in controls_by_name.items():
        if len(entries) > 1:
            # Group entries by board
            by_board = {}
            for board_id, board_type, control in entries:
                if board_id not in by_board:
                    by_board[board_id] = []
                by_board[board_id].append(control)

            # Check for same-board duplicates that aren't in a group
            for board_id, controls in by_board.items():
                if len(controls) > 1:
                    # Check if they all share the same group
                    groups = set(getattr(c, 'group', None) for c in controls)
                    if None in groups or len(groups) > 1:
                        # Some controls have no group, or different groups - that's an error
                        ungrouped = [c for c in controls if not getattr(c, 'group', None)]
                        if ungrouped:
                            nums = ', '.join(str(c.control_num) for c in ungrouped)
                            print_error(f"  ERROR: Duplicate control name '{control_name}' on board {board_id}!")
                            print(f"         Ungrouped control numbers: {nums}")

            # Check for cross-board duplicates with different types (suspicious)
            board_types = set(bt for _, bt, _ in entries)
            if len(board_types) > 1:
                board_list = ', '.join(f"{bid} ({bt})" for bid, bt, _ in entries)
                print_warning(f"  WARNING: Control '{control_name}' exists on multiple board types: {board_list}")
                print(f"           (This is OK for composite controls, but verify it's intentional)")

    # Generate control classes (nested, private) - one per unique name
    for control_name in sorted(controls_by_name.keys()):
        control_entries = controls_by_name[control_name]
        # Use first control as template
        first_board_id, first_board_type, first_control = control_entries[0]
        # Collect all controls for value merging
        control_list = [entry[2] for entry in control_entries]
        control_lines = generate_control_class(first_control, class_name, first_board_type, first_board_id, control_list)
        lines.extend(['    ' + line for line in control_lines])
        lines.append("")

    # Generate __init__ to create control instances (deduplicate by name)
    lines.append("    def __init__(self):")
    for control_name in sorted(controls_by_name.keys()):
        control_class = sanitize_class_name(control_name)
        lines.append(f"        self._{control_class}_obj = self._{control_class}(self)")
    lines.append("")

    # Generate properties that forward to the control objects
    for control_name in sorted(controls_by_name.keys()):
        control_class = sanitize_class_name(control_name)
        lines.append(f"    @property")
        lines.append(f"    def {control_class}(self):")
        lines.append(f"        return self._{control_class}_obj")
        lines.append("")

    # Add __setattr__ to intercept assignments and forward to .value
    lines.append("    def __setattr__(self, name, value):")
    lines.append("        # Check if this is a control property")
    all_control_classes = sorted(set(sanitize_class_name(cn) for cn in controls_by_name.keys()))
    lines.append(f"        control_names = {all_control_classes}")
    lines.append("        if name in control_names:")
    lines.append("            # Forward to the control's .value setter")
    lines.append("            getattr(self, name).value = value")
    lines.append("        else:")
    lines.append("            # Normal attribute assignment")
    lines.append("            object.__setattr__(self, name, value)")
    lines.append("")

    # Generate clear_changed_flags method
    lines.append("    def clear_changed_flags(self):")
    lines.append('        """Clear changed-this-cycle flags"""')
    # Track which control types we have (for button_changed flag)
    has_qd04 = any(bt == 'QD04' for _, bt, _ in board_configs)
    for control_name in sorted(controls_by_name.keys()):
        control_class = sanitize_class_name(control_name)
        control_entries = controls_by_name[control_name]
        first_board_type = control_entries[0][1]
        lines.append(f"        self._{control_class}_obj._changed_this_cycle = False")
        lines.append(f"        self._{control_class}_obj._hardware_origin = False")
        if first_board_type == 'QD04':
            lines.append(f"        self._{control_class}_obj._button_changed_this_cycle = False")
    lines.append("")

    # Generate reset_change_tracking method (for use during reset_all)
    lines.append("    def reset_change_tracking(self):")
    lines.append('        """Reset change tracking state (call on reset)"""')
    for control_name in sorted(controls_by_name.keys()):
        control_class = sanitize_class_name(control_name)
        control_entries = controls_by_name[control_name]
        first_board_type = control_entries[0][1]
        lines.append(f"        self._{control_class}_obj._last_value = None")
        lines.append(f"        self._{control_class}_obj._changed_this_cycle = False")
        if first_board_type == 'QD04':
            lines.append(f"        self._{control_class}_obj._last_button = None")
            lines.append(f"        self._{control_class}_obj._button_changed_this_cycle = False")
    lines.append("")

    # Determine what board types we have for generating appropriate methods
    board_types_present = set(bt for _, bt, _ in board_configs)
    unique_control_names = sorted(controls_by_name.keys())

    # Generate state change detection methods based on board types present
    if 'SW14' in board_types_present:
        # Build a map of control names to their state 0 values (from SW14 controls)
        state_zero_values = {}
        for board_id, board_type, board_config in board_configs:
            if board_type == 'SW14':
                for control_num, control in board_config.controls.items():
                    control_class = sanitize_class_name(control.name)
                    if control_class not in state_zero_values:
                        if hasattr(control, 'states') and 0 in control.states:
                            state_0 = control.states[0]
                            if hasattr(state_0, 'value') and state_0.value:
                                state_zero_values[control_class] = state_0.value

        # Get unique SW14 control names
        sw14_control_names = sorted(set(
            sanitize_class_name(control.name)
            for _, bt, bc in board_configs if bt == 'SW14'
            for control in bc.controls.values()
        ))

        lines.append("    def any_switch_activated(self, hardware_only=False):")
        lines.append('        """Check if any switch/button went from inactive to active state this frame.')
        lines.append('        If hardware_only=True, ignores programmatic control changes."""')

        first = True
        for control_class in sw14_control_names:
            if control_class in state_zero_values:
                zero_value = state_zero_values[control_class]
                if first:
                    lines.append(f"        if self.{control_class}.changed(hardware_only) and self.{control_class}.value != {repr(zero_value)}:")
                    first = False
                else:
                    lines.append(f"        elif self.{control_class}.changed(hardware_only) and self.{control_class}.value != {repr(zero_value)}:")
                lines.append("            return True")
            else:
                if first:
                    lines.append(f"        if self.{control_class}.changed(hardware_only):")
                    first = False
                else:
                    lines.append(f"        elif self.{control_class}.changed(hardware_only):")
                lines.append("            return True")
        lines.append("        return False")
        lines.append("")

        lines.append("    def any_switch_deactivated(self, hardware_only=False):")
        lines.append('        """Check if any switch/button went from active to inactive state this frame.')
        lines.append('        If hardware_only=True, ignores programmatic control changes."""')

        first = True
        for control_class in sw14_control_names:
            if control_class in state_zero_values:
                zero_value = state_zero_values[control_class]
                if first:
                    lines.append(f"        if self.{control_class}.changed(hardware_only) and self.{control_class}.value == {repr(zero_value)}:")
                    first = False
                else:
                    lines.append(f"        elif self.{control_class}.changed(hardware_only) and self.{control_class}.value == {repr(zero_value)}:")
                lines.append("            return True")
        lines.append("        return False")
        lines.append("")

    if 'AN08' in board_types_present:
        # Get unique AN08 control names
        an08_control_names = sorted(set(
            sanitize_class_name(control.name)
            for _, bt, bc in board_configs if bt == 'AN08'
            for control in bc.controls.values()
        ))

        lines.append("    def any_axis_changed(self):")
        lines.append('        """Check if any ADC axis value changed this frame"""')
        lines.append(f"        controls = [{', '.join(f'self.{name}' for name in an08_control_names)}]")
        lines.append("        for control in controls:")
        lines.append("            if control.changed():")
        lines.append("                return True")
        lines.append("        return False")
        lines.append("")

    if 'QD04' in board_types_present:
        # Get unique QD04 control names
        qd04_control_names = sorted(set(
            sanitize_class_name(control.name)
            for _, bt, bc in board_configs if bt == 'QD04'
            for control in bc.controls.values()
        ))

        lines.append("    def any_knob_changed(self):")
        lines.append('        """Check if any encoder position changed this frame"""')
        lines.append(f"        controls = [{', '.join(f'self.{name}' for name in qd04_control_names)}]")
        lines.append("        for control in controls:")
        lines.append("            if control.changed():")
        lines.append("                return True")
        lines.append("        return False")
        lines.append("")

        lines.append("    def any_button_pressed(self):")
        lines.append('        """Check if any encoder button went from 0 to 1 this frame"""')
        lines.append(f"        controls = [{', '.join(f'self.{name}' for name in qd04_control_names)}]")
        lines.append("        for control in controls:")
        lines.append("            # Check if button changed and is now pressed (1)")
        lines.append("            if control.button_changed() and control.button == 1:")
        lines.append("                return True")
        lines.append("        return False")
        lines.append("")

        lines.append("    def any_button_released(self):")
        lines.append('        """Check if any encoder button went from 1 to 0 this frame"""')
        lines.append(f"        controls = [{', '.join(f'self.{name}' for name in qd04_control_names)}]")
        lines.append("        for control in controls:")
        lines.append("            # Check if button changed and is now released (0)")
        lines.append("            if control.button_changed() and control.button == 0:")
        lines.append("                return True")
        lines.append("        return False")
        lines.append("")

    return '\n'.join(lines)


def generate_keyboard_control_class(keyboard_config_path: Path) -> str:
    """Generate special Keyboard text input control class"""

    # Load keyboard config to extract schemes
    schemes = set(['default'])
    try:
        with open(keyboard_config_path, 'r') as f:
            keyboard_data = json.load(f)
            if 'schemes' in keyboard_data:
                schemes.update(keyboard_data['schemes'].keys())
    except Exception as e:
        print_warning(f"  Warning: Could not read schemes from Keyboard.json: {e}")

    lines = []
    lines.append('class _Keyboard:')
    lines.append('    """Keyboard text input control - supports text aggregation from G Pro keyboard"""')
    lines.append('    NAME = "Keyboard"')
    lines.append('    BOARD_ID = "GPRO-00"')
    lines.append('')

    # Generate Schemes class
    lines.append('    class Schemes:')
    for scheme in sorted(schemes):
        scheme_const = sanitize_identifier(scheme)
        lines.append(f'        {scheme_const} = "{scheme}"')
    lines.append('')

    # Generate Allow class for input filtering
    lines.append('    class Allow:')
    lines.append('        """Character filter presets for start(). Combine with | operator."""')
    lines.append("        ALPHA = frozenset('ABCDEFGHIJKLMNOPQRSTUVWXYZ ')")
    lines.append("        NUMERIC = frozenset('0123456789-+')")
    lines.append('        ALPHANUMERIC = ALPHA | NUMERIC')
    lines.append("        PUNCTUATION = frozenset(\"`[]\\\\;',./~{}|:\\\"<>?_\")")
    lines.append('        ALL = None  # No filtering (default)')
    lines.append('')

    lines.append('    def __init__(self):')
    lines.append('        self._last_value = None')
    lines.append('        self._changed_this_cycle = False')
    lines.append('')
    lines.append('    @property')
    lines.append('    def value(self):')
    lines.append('        """Get current text buffer"""')
    lines.append('        from enigma.manager import get_manager')
    lines.append('        device = get_manager().get_device(self.BOARD_ID)')
    lines.append('        if device and device.handler:')
    lines.append('            return device.handler.get_text_buffer()')
    lines.append('        return ""')
    lines.append('')
    lines.append('    @value.setter')
    lines.append('    def value(self, text):')
    lines.append('        """Set text buffer"""')
    lines.append('        from enigma.manager import get_manager')
    lines.append('        device = get_manager().get_device(self.BOARD_ID)')
    lines.append('        if device and device.handler:')
    lines.append('            device.handler.set_text_buffer(text)')
    lines.append('')
    lines.append('    @property')
    lines.append('    def Scheme(self):')
    lines.append('        """Scheme property (write-only)"""')
    lines.append('        return None')
    lines.append('')
    lines.append('    @Scheme.setter')
    lines.append('    def Scheme(self, val):')
    lines.append('        """Set keyboard LED scheme"""')
    lines.append('        from enigma.manager import get_manager')
    lines.append('        device = get_manager().get_device(self.BOARD_ID)')
    lines.append('        if device and device.handler:')
    lines.append('            device.handler.set_scheme(val)')
    lines.append('')
    lines.append('    def changed(self):')
    lines.append('        """Check if buffer changed this update cycle"""')
    lines.append('        if self._changed_this_cycle:')
    lines.append('            return True')
    lines.append('        current = self.value')
    lines.append('        if self._last_value is None:')
    lines.append('            self._last_value = current')
    lines.append('            return False')
    lines.append('        if current != self._last_value:')
    lines.append('            self._last_value = current')
    lines.append('            self._changed_this_cycle = True')
    lines.append('            return True')
    lines.append('        return False')
    lines.append('')
    lines.append('    def __eq__(self, other):')
    lines.append('        """Enable comparisons: Keyboard == "text" """')
    lines.append('        return self.value == other')
    lines.append('')
    lines.append('    def __ne__(self, other):')
    lines.append('        return self.value != other')
    lines.append('')
    lines.append('    def __add__(self, other):')
    lines.append('        """Enable: Keyboard + " suffix" """')
    lines.append('        return self.value + other')
    lines.append('')
    lines.append('    def __radd__(self, other):')
    lines.append('        """Enable: "prefix " + Keyboard"""')
    lines.append('        return other + self.value')
    lines.append('')
    lines.append('    def __contains__(self, item):')
    lines.append('        """Enable: "x" in Keyboard"""')
    lines.append('        return item in self.value')
    lines.append('')
    lines.append('    def __len__(self):')
    lines.append('        """Enable: len(Keyboard)"""')
    lines.append('        return len(self.value)')
    lines.append('')
    lines.append('    def __str__(self):')
    lines.append('        """Enable str(Keyboard) and f-strings"""')
    lines.append('        return self.value')
    lines.append('')
    lines.append('    def __repr__(self):')
    lines.append('        return f"Keyboard={repr(self.value)}"')
    lines.append('')
    lines.append('    def didSubmit(self):')
    lines.append('        """Returns True if ENTER was pressed (one-shot, cleared next cycle)"""')
    lines.append('        from enigma.manager import get_manager')
    lines.append('        device = get_manager().get_device(self.BOARD_ID)')
    lines.append('        if device and device.handler:')
    lines.append('            return device.handler.keyboard_did_submit()')
    lines.append('        return False')
    lines.append('')
    lines.append('    def didCancel(self):')
    lines.append('        """Returns True if ESC was pressed (one-shot, cleared next cycle)"""')
    lines.append('        from enigma.manager import get_manager')
    lines.append('        device = get_manager().get_device(self.BOARD_ID)')
    lines.append('        if device and device.handler:')
    lines.append('            return device.handler.keyboard_did_cancel()')
    lines.append('        return False')
    lines.append('')
    lines.append('    def start(self, allowed=None, capture_arrows=True):')
    lines.append('        """Start keyboard input mode')
    lines.append('')
    lines.append('        Args:')
    lines.append('            allowed: Optional character filter. Use Allow presets:')
    lines.append('                     Keyboard.Allow.ALPHA - Letters and space')
    lines.append('                     Keyboard.Allow.NUMERIC - Numbers and -, + (0-9, -, +)')
    lines.append('                     Keyboard.Allow.ALPHANUMERIC - Letters and numbers')
    lines.append('                     Keyboard.Allow.PUNCTUATION - Punctuation characters')
    lines.append('                     Keyboard.Allow.ALL or None - No filtering (default)')
    lines.append('                     Combine with |: Allow.ALPHA | Allow.NUMERIC')
    lines.append('            capture_arrows: When True (default) LEFT/RIGHT/UP/DOWN move the buffer cursor.')
    lines.append('                            When False, arrows are reserved for the app - read them via')
    lines.append('                            Keyboard.lastKey(). Useful when arrows drive highlight/selection.')
    lines.append('        """')
    lines.append('        from enigma.manager import get_manager')
    lines.append('        device = get_manager().get_device(self.BOARD_ID)')
    lines.append('        if device and device.handler:')
    lines.append('            device.handler.keyboard_start_input(allowed, capture_arrows=capture_arrows)')
    lines.append('')
    lines.append('    def end(self):')
    lines.append('        """End keyboard input mode"""')
    lines.append('        from enigma.manager import get_manager')
    lines.append('        device = get_manager().get_device(self.BOARD_ID)')
    lines.append('        if device and device.handler:')
    lines.append('            device.handler.keyboard_end_input()')
    lines.append('')
    lines.append('    def position(self):')
    lines.append('        """Get cursor position"""')
    lines.append('        from enigma.manager import get_manager')
    lines.append('        device = get_manager().get_device(self.BOARD_ID)')
    lines.append('        if device and device.handler:')
    lines.append('            return device.handler.keyboard_cursor_position()')
    lines.append('        return 0')
    lines.append('')
    lines.append('    def cursor_to_end(self):')
    lines.append('        """Snap the caret to the end of the current buffer. Call after')
    lines.append('        setting Keyboard.value when you want the caret at the end of the')
    lines.append('        restored text rather than the position 0 default."""')
    lines.append('        from enigma.manager import get_manager')
    lines.append('        device = get_manager().get_device(self.BOARD_ID)')
    lines.append('        if device and device.handler:')
    lines.append('            device.handler.keyboard_cursor_to_end()')
    lines.append('')
    lines.append('    def lastKey(self):')
    lines.append('        """Get last key pressed this cycle (None if no key pressed)"""')
    lines.append('        from enigma.manager import get_manager')
    lines.append('        device = get_manager().get_device(self.BOARD_ID)')
    lines.append('        if device and device.handler:')
    lines.append('            return device.handler.keyboard_last_key()')
    lines.append('        return None')
    lines.append('')

    return '\n'.join(lines)


def generate_controls_file(config_dir: Path, output_file: Path):
    """Generate the complete controls file"""

    print(f"Reading configs from {config_dir}")
    config_manager = ConfigManager(config_dir)

    lines = []
    lines.append('"""')
    lines.append('Auto-generated control constants from Enigma device configurations')
    lines.append('')
    lines.append('DO NOT EDIT THIS FILE MANUALLY')
    lines.append('Generated by: tools/generate_controls.py')
    lines.append('')
    lines.append('Usage:')
    lines.append('    from generated.controls import PowerCore')
    lines.append('    ')
    lines.append('    # Read value')
    lines.append('    if PowerCore.Auto == PowerCore.Auto.Values.MANUAL:')
    lines.append('        ...')
    lines.append('    ')
    lines.append('    # Write value')
    lines.append('    PowerCore.Auto.value = PowerCore.Auto.Values.AUTO')
    lines.append('    ')
    lines.append('    # Set scheme')
    lines.append('    PowerCore.Auto.Scheme = "danger"')
    lines.append('    ')
    lines.append('    # Check for changes')
    lines.append('    if PowerCore.Auto.changed():')
    lines.append('        ...')
    lines.append('    ')
    lines.append('    # Keyboard text input (if GPRO keyboard present)')
    lines.append('    Keyboard = "Enter name: "')
    lines.append('    if Keyboard.didSubmit():')
    lines.append('        name = str(Keyboard)')
    lines.append('    ')
    lines.append('    # Enable/disable controls')
    lines.append('    Device.enable_all()                              # Enable all controls')
    lines.append('    Device.disable_all()                             # Disable all controls')
    lines.append('    Device.enable(Device.Ctrl1, Device.Ctrl2)       # Enable specific controls')
    lines.append('    Device.disable(Device.Ctrl1, Device.Ctrl2)      # Disable specific controls')
    lines.append('    Device.Ctrl1.Enabled = True                     # Enable single control')
    lines.append('')
    lines.append('    # Push/pop enable state (for modal states like attract/pause):')
    lines.append('    Device.disable_all(pushState=True)              # Save state, then disable all')
    lines.append('    Device.enable(Device.Ctrl1)                     # Re-enable specific controls')
    lines.append('    Device.pop_enable()                             # Restore saved state')
    lines.append('"""')
    lines.append('')
    lines.append('from enigma.control_value import ControlValue')
    lines.append('')

    # Generate base class for device classes
    lines.append('')
    lines.append('class _DeviceBase:')
    lines.append('    """Base class for generated device classes with common enable/disable methods."""')
    lines.append('')
    lines.append('    # Subclasses must define BOARD_IDS')
    lines.append('    BOARD_IDS = []')
    lines.append('')
    lines.append('    def enable_all(self, pushState=False):')
    lines.append('        """Enable all controls on all boards')
    lines.append('')
    lines.append('        Args:')
    lines.append('            pushState: If True, save current enable state before modifying (use pop_enable() to restore)')
    lines.append('        """')
    lines.append('        from enigma.manager import get_manager')
    lines.append('        for board_id in self.BOARD_IDS:')
    lines.append('            device = get_manager().get_device(board_id)')
    lines.append('            if device and device.handler:')
    lines.append('                device.handler.enable_all(pushState=pushState)')
    lines.append('')
    lines.append('    def disable_all(self, pushState=False):')
    lines.append('        """Disable all controls on all boards')
    lines.append('')
    lines.append('        Args:')
    lines.append('            pushState: If True, save current enable state before modifying (use pop_enable() to restore)')
    lines.append('        """')
    lines.append('        from enigma.manager import get_manager')
    lines.append('        for board_id in self.BOARD_IDS:')
    lines.append('            device = get_manager().get_device(board_id)')
    lines.append('            if device and device.handler:')
    lines.append('                device.handler.disable_all(pushState=pushState)')
    lines.append('')
    lines.append('    def enable(self, *controls, pushState=False):')
    lines.append('        """Enable multiple controls (batch operation to reduce HID traffic)')
    lines.append('')
    lines.append('        Args:')
    lines.append('            *controls: Control objects to enable (e.g., self.MissileCount, self.JettisonMines)')
    lines.append('            pushState: If True, save current enable state before modifying (use pop_enable() to restore)')
    lines.append('        """')
    lines.append('        from enigma.manager import get_manager')
    lines.append('        # Group by board_id')
    lines.append('        by_board = {}')
    lines.append('        for ctrl in controls:')
    lines.append('            board_id = ctrl.BOARD_ID')
    lines.append('            if board_id not in by_board:')
    lines.append('                by_board[board_id] = []')
    lines.append('            by_board[board_id].append(ctrl.NAME)')
    lines.append('        # Group names by board and call set_controls_enabled per board')
    lines.append('        first = True')
    lines.append('        for board_id, names in by_board.items():')
    lines.append('            device = get_manager().get_device(board_id)')
    lines.append('            if device and device.handler:')
    lines.append('                device.handler.set_controls_enabled(names, True, pushState=(pushState and first))')
    lines.append('                first = False')
    lines.append('')
    lines.append('    def disable(self, *controls, pushState=False):')
    lines.append('        """Disable multiple controls (batch operation to reduce HID traffic)')
    lines.append('')
    lines.append('        Args:')
    lines.append('            *controls: Control objects to disable (e.g., self.MissileCount, self.JettisonMines)')
    lines.append('            pushState: If True, save current enable state before modifying (use pop_enable() to restore)')
    lines.append('        """')
    lines.append('        from enigma.manager import get_manager')
    lines.append('        # Group by board_id')
    lines.append('        by_board = {}')
    lines.append('        for ctrl in controls:')
    lines.append('            board_id = ctrl.BOARD_ID')
    lines.append('            if board_id not in by_board:')
    lines.append('                by_board[board_id] = []')
    lines.append('            by_board[board_id].append(ctrl.NAME)')
    lines.append('        # Group names by board and call set_controls_enabled per board')
    lines.append('        first = True')
    lines.append('        for board_id, names in by_board.items():')
    lines.append('            device = get_manager().get_device(board_id)')
    lines.append('            if device and device.handler:')
    lines.append('                device.handler.set_controls_enabled(names, False, pushState=(pushState and first))')
    lines.append('                first = False')
    lines.append('')
    lines.append('    def pop_enable(self):')
    lines.append('        """Restore previously saved enable state (from a pushState=True call)')
    lines.append('')
    lines.append('        Warns if no state was previously pushed.')
    lines.append('        """')
    lines.append('        from enigma.manager import get_manager')
    lines.append('        for board_id in self.BOARD_IDS:')
    lines.append('            device = get_manager().get_device(board_id)')
    lines.append('            if device and device.handler:')
    lines.append('                device.handler.pop_enable_mask()')
    lines.append('')
    lines.append('    def set_scheme(self, *controls, scheme, pushState=False):')
    lines.append('        """Set indicator scheme on specific controls.')
    lines.append('')
    lines.append('        Args:')
    lines.append('            *controls: Control objects to update')
    lines.append('            scheme: Scheme name to apply')
    lines.append('            pushState: If True, save current schemes before modifying (use pop_scheme() to restore)')
    lines.append('        """')
    lines.append('        from enigma.manager import get_manager')
    lines.append('        by_board = {}')
    lines.append('        for ctrl in controls:')
    lines.append('            board_id = ctrl.BOARD_ID')
    lines.append('            if board_id not in by_board:')
    lines.append('                by_board[board_id] = []')
    lines.append('            by_board[board_id].append(ctrl.NAME)')
    lines.append('        first = True')
    lines.append('        for board_id, names in by_board.items():')
    lines.append('            device = get_manager().get_device(board_id)')
    lines.append('            if device and device.handler:')
    lines.append('                if pushState and first:')
    lines.append('                    device.handler.push_scheme(names)')
    lines.append('                    first = False')
    lines.append('                for name in names:')
    lines.append('                    device.handler.set_indicator_scheme(scheme, name)')
    lines.append('')
    lines.append('    def pop_scheme(self):')
    lines.append('        """Restore previously saved scheme state (from a set_scheme(..., pushState=True) call).')
    lines.append('')
    lines.append('        Warns if no state was previously pushed.')
    lines.append('        """')
    lines.append('        from enigma.manager import get_manager')
    lines.append('        for board_id in self.BOARD_IDS:')
    lines.append('            device = get_manager().get_device(board_id)')
    lines.append('            if device and device.handler:')
    lines.append('                device.handler.pop_scheme()')
    lines.append('')
    lines.append('    def set_blanking(self, mode, duration_tenths=0):')
    lines.append('        """Set LED blanking on all boards for this device.')
    lines.append('')
    lines.append('        Args:')
    lines.append('            mode: 0=off, 1=on (all dark), 2=disruption')
    lines.append('            duration_tenths: For disruption mode, duration before full blank (0-255)')
    lines.append('        """')
    lines.append('        from enigma.manager import get_manager')
    lines.append('        from enigma.hid_protocol import EnigmaDevice, BlankingMode')
    lines.append('        for board_id in self.BOARD_IDS:')
    lines.append('            device = get_manager().get_device(board_id)')
    lines.append('            if device and isinstance(device, EnigmaDevice):')
    lines.append('                device.set_blanking(BlankingMode(mode), duration_tenths)')
    lines.append('')
    lines.append('    def restore_enable_defaults(self):')
    lines.append('        """Restore enable masks to config defaults on all boards for this device."""')
    lines.append('        from enigma.manager import get_manager')
    lines.append('        for board_id in self.BOARD_IDS:')
    lines.append('            device = get_manager().get_device(board_id)')
    lines.append('            if device and device.handler:')
    lines.append('                default_mask = getattr(device.handler, "_config_default_mask", 0xFFFF)')
    lines.append('                device.handler.set_enable_mask(default_mask)')
    lines.append('')
    lines.append('')

    # First pass: collect all configs and group by device name
    # device_name -> [(board_id, board_type, board_config), ...]
    configs_by_name = {}

    for board_id, config_name in sorted(config_manager.board_mappings.items()):
        config_file = config_manager.get_config_file(board_id)
        if not config_file:
            continue

        with open(config_file, 'r') as f:
            config_data = json.load(f)

        # Determine handler and board type
        board_type = get_board_type(board_id)
        if board_id.startswith('SW14-'):
            from enigma.boards.sw14 import SW14Handler
            handler_class = SW14Handler
        elif board_id.startswith('QD04-') or board_id.startswith('QD08-'):
            from enigma.boards.qd04 import QD04Handler
            handler_class = QD04Handler
        elif board_id.startswith('AN08-'):
            from enigma.boards.an08 import AN08Handler
            handler_class = AN08Handler
        elif board_id.startswith('T16K-'):
            from enigma.boards.thrustmaster import ThrustmasterHandler
            handler_class = ThrustmasterHandler
        else:
            continue

        # Parse config using the handler
        handler = handler_class(None)
        board_config = handler.parse_config(config_data)
        device_name = board_config.name

        if device_name not in configs_by_name:
            configs_by_name[device_name] = []
        configs_by_name[device_name].append((board_id, board_type, board_config))

    # Second pass: generate one class per unique device name
    device_classes = []
    for device_name in sorted(configs_by_name.keys()):
        board_configs = configs_by_name[device_name]
        board_ids = [bc[0] for bc in board_configs]

        if len(board_configs) > 1:
            print(f"  Aggregating {len(board_configs)} boards into {device_name}: {', '.join(board_ids)}")

        device_code = generate_device_class(device_name, board_configs)
        lines.append(device_code)
        lines.append("")

        class_name = sanitize_class_name(device_name)
        device_classes.append(class_name)

    # Generate Keyboard control if GPRO keyboard config exists
    keyboard_config = config_dir / 'Keyboard.json'
    if keyboard_config.exists():
        print(f"  Found Keyboard.json - generating Keyboard control")
        keyboard_code = generate_keyboard_control_class(keyboard_config)
        lines.append(keyboard_code)
        lines.append("")
        device_classes.append('Keyboard')

    # Create singleton instances
    lines.append("# Create singleton instances")
    for class_name in device_classes:
        if class_name == 'Keyboard':
            lines.append(f"{class_name} = _{class_name}()")
        else:
            lines.append(f"{class_name} = _{class_name}()")
    lines.append("")

    # Write file
    output_file.write_text('\n'.join(lines))
    print(f"Generated {output_file}")
    print(f"  {len(device_classes)} devices")


def main():
    # Route Ctrl-\ through KeyboardInterrupt instead of SIGQUIT's default core
    # dump, which triggers macOS's crash dialog (see hd.py).
    signal.signal(signal.SIGQUIT, signal.default_int_handler)

    parser = argparse.ArgumentParser(description='Generate control constants from config files')
    parser.add_argument('--config-dir', type=Path, default=Path('configs'),
                       help='Directory containing config files (default: configs)')
    parser.add_argument('--output', type=Path, default=Path('halcyon_controls.py'),
                       help='Output file (default: halcyon_controls.py)')
    parser.add_argument('--docs', type=Path, default=None,
                       help='Optional documentation output file (e.g., controls_reference.txt)')

    args = parser.parse_args()

    if not args.config_dir.exists():
        print_error(f"ERROR: Config directory not found: {args.config_dir}")
        sys.exit(1)

    generate_controls_file(args.config_dir, args.output)

    if args.docs:
        generate_documentation(args.config_dir, args.docs)


def generate_documentation(config_dir: Path, output_file: Path):
    """Generate human-readable documentation with copy-paste examples"""

    print(f"\nGenerating documentation: {output_file}")
    config_manager = ConfigManager(config_dir)

    lines = []
    lines.append("=" * 80)
    lines.append("ENIGMA CONTROL REFERENCE")
    lines.append("=" * 80)
    lines.append("")
    lines.append("This file contains all available devices, controls, values, and schemes")
    lines.append("with fully-qualified paths for easy copy-paste into your code.")
    lines.append("")

    # Track first control/value for example code
    first_device = None
    first_control = None
    first_value = None
    first_value_path = None
    first_scheme = None

    for board_id, config_name in sorted(config_manager.board_mappings.items()):
        config_file = config_manager.get_config_file(board_id)
        if not config_file:
            continue

        with open(config_file, 'r') as f:
            config_data = json.load(f)

        # Determine handler and board type for docs
        board_type = None
        if board_id.startswith('SW14-'):
            from enigma.boards.sw14 import SW14Handler
            handler_class = SW14Handler
            board_type = 'SW14'
        elif board_id.startswith('QD04-') or board_id.startswith('QD08-'):
            from enigma.boards.qd04 import QD04Handler
            handler_class = QD04Handler
            board_type = 'QD04'
        elif board_id.startswith('AN08-'):
            from enigma.boards.an08 import AN08Handler
            handler_class = AN08Handler
            board_type = 'AN08'
        elif board_id.startswith('T16K-'):
            from enigma.boards.thrustmaster import ThrustmasterHandler
            handler_class = ThrustmasterHandler
            board_type = 'T16K'
        else:
            continue

        handler = handler_class(None)
        board_config = handler.parse_config(config_data)

        device_name = board_config.name
        device_class = sanitize_class_name(device_name)

        if first_device is None:
            first_device = device_class

        lines.append("=" * 80)
        lines.append(f"DEVICE: {device_name}")
        lines.append("=" * 80)
        lines.append(f"Board ID: {board_id}")
        lines.append(f"Instance: {device_class}")
        lines.append("")

        # Device-level schemes
        all_schemes = set(['default'])
        for control_num, control in board_config.controls.items():
            if hasattr(control, 'schemes'):
                all_schemes.update(control.schemes.keys())

        lines.append("Device Schemes:")
        for scheme in sorted(all_schemes):
            scheme_const = sanitize_identifier(scheme)
            lines.append(f"  {device_class}.Schemes.{scheme_const}")
            if first_device == device_class and first_scheme is None:
                first_scheme = f"{device_class}.Schemes.{scheme_const}"
        lines.append("")
        lines.append("Set device-wide scheme:")
        lines.append(f"  {device_class}.Scheme = {device_class}.Schemes.DEFAULT")
        lines.append("")

        # Controls
        lines.append("Controls:")
        lines.append("")

        # Group controls by name (for radio buttons)
        controls_by_name = {}
        for control_num, control in board_config.controls.items():
            name = control.name
            if name not in controls_by_name:
                controls_by_name[name] = []
            controls_by_name[name].append((control_num, control))

        # Sort control groups alphabetically by name
        for control_name in sorted(controls_by_name.keys(), key=lambda x: x.lower()):
            control_list = controls_by_name[control_name]
            control_class = sanitize_class_name(control_name)

            if first_device == device_class and first_control is None:
                first_control = control_class

            # Check if this is a radio group (multiple controls with same name)
            is_radio_group = len(control_list) > 1

            # For display purposes, assume multiple buttons are a radio group
            # (momoffmom switches will still show all their values)

            lines.append(f"  {control_class}:")
            lines.append(f"    Name: {control_name}")
            lines.append(f"    Path: {device_class}.{control_class}")

            # Use first control for description
            first_control_obj = control_list[0][1]
            lines.append(f"    Description: {first_control_obj.desc or 'N/A'}")

            if is_radio_group:
                lines.append(f"    Type: Grouped control ({len(control_list)} physical controls)")

            # For SW14, show default state
            if board_type == 'SW14' and hasattr(first_control_obj, 'default_state'):
                default_val = None
                if hasattr(first_control_obj, 'states') and first_control_obj.default_state in first_control_obj.states:
                    state_config = first_control_obj.states[first_control_obj.default_state]
                    if hasattr(state_config, 'value') and state_config.value:
                        default_val = state_config.value
                        default_const = sanitize_identifier(default_val)
                        lines.append(f"    Default: {device_class}.{control_class}.Values.{default_const}")

            # For QD04, show range and mode properties
            if board_type == 'QD04' and hasattr(first_control_obj, 'min_value') and hasattr(first_control_obj, 'max_value'):
                from enigma.boards.qd04 import CountMode, BackgroundMode, ActiveMode

                units = getattr(first_control_obj, 'units', '')
                units_str = f" {units}" if units else ""
                lines.append(f"    Range: {first_control_obj.min_value}{units_str} to {first_control_obj.max_value}{units_str}")

                # Show count_mode
                count_mode = getattr(first_control_obj, 'count_mode', CountMode.ABSOLUTE)
                mode_name = 'incremental' if count_mode == CountMode.INCREMENTAL else 'absolute'
                lines.append(f"    Count Mode: {mode_name}")

                # Show num_leds (resolution for incremental)
                num_leds = getattr(first_control_obj, 'num_leds', 20)
                if count_mode == CountMode.INCREMENTAL:
                    lines.append(f"    Resolution: {num_leds} steps (min to max)")
                else:
                    lines.append(f"    LEDs: {num_leds}")

                # Show wrap
                wrap = getattr(first_control_obj, 'wrap', False)
                if wrap:
                    lines.append(f"    Wrap: enabled (values wrap at min/max)")

                # Show reverse
                reverse = getattr(first_control_obj, 'reverse', False)
                if reverse:
                    lines.append(f"    Reverse: enabled (A/B wiring reversed)")

                # Show acceleration config
                acceleration = getattr(first_control_obj, 'acceleration', None)
                if acceleration:
                    lines.append(f"    Acceleration:")
                    lines.append(f"      Max Multiplier: {acceleration.max_multiplier}x")
                    lines.append(f"      Ramp Speed: {acceleration.ramp_speed} reports/sec")
                    lines.append(f"      Dead Zone: {acceleration.dead_zone} reports/sec (fine control)")

                # Show dial display modes
                dial = getattr(first_control_obj, 'dial', None)
                if dial:
                    bg_mode = getattr(dial, 'background_mode', BackgroundMode.GRADIENT)
                    active_mode = getattr(dial, 'active_mode', ActiveMode.BAR)
                    bg_name = 'ranged' if bg_mode == BackgroundMode.RANGED else 'gradient'
                    active_name = 'tick' if active_mode == ActiveMode.TICK else 'bar'
                    lines.append(f"    Background Mode: {bg_name}")
                    lines.append(f"    Active Mode: {active_name}")

                lines.append(f"    Button: {device_class}.{control_class}.button and .button_changed()")

            # AN08-specific info
            if board_type == 'AN08' and hasattr(first_control_obj, 'min_value') and hasattr(first_control_obj, 'max_value'):
                units_str = ""
                lines.append(f"    Range: {first_control_obj.min_value} to {first_control_obj.max_value}{units_str}")
                lines.append(f"    Sensor range: {first_control_obj.sensor_min_v}V-{first_control_obj.sensor_max_v}V")
                gamma = getattr(first_control_obj, 'gamma', 1.0)
                if gamma != 1.0:
                    lines.append(f"    Gamma: {gamma} (response curve)")
                invert = getattr(first_control_obj, 'invert', False)
                if invert:
                    lines.append(f"    Invert: yes")
                lines.append(f"    Raw property: {device_class}.{control_class}.raw (0-1023, int)")

            lines.append("")

            # Collect values from all controls in group (for radio groups)
            values = {}
            for _, control in control_list:
                if hasattr(control, 'states'):
                    for state_num, state in control.states.items():
                        if hasattr(state, 'value') and state.value:
                            values[state.value] = state_num

            if values:
                lines.append("    Values:")
                for value in sorted(values.keys()):
                    value_const = sanitize_identifier(value)
                    lines.append(f"      {device_class}.{control_class}.Values.{value_const}")
                    if first_device == device_class and first_control == control_class and first_value is None:
                        first_value = value_const
                        first_value_path = f"{device_class}.{control_class}.Values.{value_const}"
                lines.append("")

            # Control schemes - collect from all controls in group
            control_schemes = set(['default'])
            for _, control in control_list:
                if hasattr(control, 'schemes'):
                    control_schemes.update(control.schemes.keys())

            if len(control_schemes) > 1:
                lines.append("    Control Schemes:")
                for scheme in sorted(control_schemes):
                    scheme_const = sanitize_identifier(scheme)
                    lines.append(f"      {device_class}.{control_class}.Schemes.{scheme_const}")
                lines.append("")

            # Usage examples
            lines.append("    Usage:")
            if values:
                # Get first value for example
                first_val = sorted(values.keys())[0]
                first_val_const = sanitize_identifier(first_val)

                lines.append(f"      # Read and compare value")
                lines.append(f"      if {device_class}.{control_class} == {device_class}.{control_class}.Values.{first_val_const}:")
                lines.append(f"          ...")
                lines.append(f"      ")
                lines.append(f"      # Write value")
                lines.append(f"      {device_class}.{control_class}.value = {device_class}.{control_class}.Values.{first_val_const}")
            lines.append(f"      ")
            lines.append(f"      # Set scheme")
            if len(control_schemes) > 1:
                first_scheme = sorted(control_schemes)[0]
                first_scheme_const = sanitize_identifier(first_scheme)
                lines.append(f"      {device_class}.{control_class}.Scheme = {device_class}.{control_class}.Schemes.{first_scheme_const}")
            else:
                lines.append(f"      {device_class}.{control_class}.Scheme = {device_class}.Schemes.DEFAULT")
            lines.append(f"      ")
            lines.append(f"      # Check for changes")
            if values:
                lines.append(f"      if {device_class}.{control_class}.changed() and {device_class}.{control_class} == {device_class}.{control_class}.Values.{first_val_const}:")
                lines.append(f"          ...")
            else:
                lines.append(f"      if {device_class}.{control_class}.changed():")
                lines.append(f"          ...")

            # Add button examples for QD04
            if board_type == 'QD04':
                lines.append(f"      ")
                lines.append(f"      # Check button")
                lines.append(f"      if {device_class}.{control_class}.button == 1:")
                lines.append(f"          ...")
                lines.append(f"      ")
                lines.append(f"      # Check if button changed")
                lines.append(f"      if {device_class}.{control_class}.button_changed():")
                lines.append(f"          if {device_class}.{control_class}.button == 1:")
                lines.append(f"              print('Pressed!')")

            # Add raw access examples for AN08
            if board_type == 'AN08':
                lines.append(f"      ")
                lines.append(f"      # Read mapped float value")
                lines.append(f"      throttle = {device_class}.{control_class}.value")
                lines.append(f"      ")
                lines.append(f"      # Read raw ADC value (0-1023)")
                lines.append(f"      raw = {device_class}.{control_class}.raw")
                lines.append(f"      ")
                lines.append(f"      # Detect changes")
                lines.append(f"      if {device_class}.{control_class}.changed():")
                lines.append(f"          print(f'Axis: {{throttle:.3f}}')")

            lines.append("")

    # Add Keyboard control documentation if present
    keyboard_config = config_dir / 'Keyboard.json'
    if keyboard_config.exists():
        lines.append("=" * 80)
        lines.append("DEVICE: Keyboard (G Pro Text Input)")
        lines.append("=" * 80)
        lines.append("Board ID: GPRO-00")
        lines.append("Instance: Keyboard")
        lines.append("")
        lines.append("Description:")
        lines.append("  Virtual control for text input from Logitech G Pro keyboard.")
        lines.append("  Aggregates keystrokes into a text buffer with cursor support.")
        lines.append("")

        # Load schemes from keyboard config
        keyboard_schemes = set(['default'])
        try:
            with open(keyboard_config, 'r') as f:
                keyboard_data = json.load(f)
                if 'schemes' in keyboard_data:
                    keyboard_schemes.update(keyboard_data['schemes'].keys())
        except:
            pass

        lines.append("Schemes:")
        for scheme in sorted(keyboard_schemes):
            scheme_const = sanitize_identifier(scheme)
            lines.append(f"  Keyboard.Schemes.{scheme_const}")
        lines.append("")

        lines.append("Input Filters (for start()):")
        lines.append("  Keyboard.Allow.ALPHA        - Letters and space (A-Z, space)")
        lines.append("  Keyboard.Allow.NUMERIC      - Numbers (0-9, -, +)")
        lines.append("  Keyboard.Allow.ALPHANUMERIC - Letters and numbers")
        lines.append("  Keyboard.Allow.PUNCTUATION  - Punctuation characters")
        lines.append("  Keyboard.Allow.ALL          - No filtering (default)")
        lines.append("  Combine with |: Keyboard.Allow.ALPHA | Keyboard.Allow.NUMERIC")
        lines.append("")

        lines.append("Properties:")
        lines.append("  Keyboard.value         - Get/set text buffer (string)")
        lines.append("  Keyboard.Scheme        - Set keyboard LED scheme (write-only)")
        lines.append("  Keyboard.position()    - Get cursor position (int)")
        lines.append("  Keyboard.lastKey()     - Get last key pressed this cycle (str or None)")
        lines.append("")
        lines.append("Methods:")
        lines.append("  Keyboard.start()              - Begin input (all keys allowed)")
        lines.append("  Keyboard.start(filter)        - Begin input with character filter")
        lines.append("  Keyboard.end()                - End keyboard input mode")
        lines.append("  Keyboard.didSubmit()   - True if ENTER pressed this cycle")
        lines.append("  Keyboard.didCancel()   - True if ESC pressed this cycle")
        lines.append("  Keyboard.changed()     - True if buffer changed this cycle")
        lines.append("")
        lines.append("Usage:")
        lines.append("  # Set initial text")
        lines.append("  Keyboard = \"Enter name: \"")
        lines.append("  ")
        lines.append("  # Set LED scheme")
        lines.append("  Keyboard.Scheme = Keyboard.Schemes.DEFAULT")
        lines.append("  ")
        lines.append("  # Read text")
        lines.append("  text = Keyboard.value          # Explicit property access")
        lines.append("  print(Keyboard)                # Prints string automatically")
        lines.append("  print(f\"Text: {Keyboard}\")    # F-string automatically")
        lines.append("  message = \"User: \" + Keyboard  # String concat automatically")
        lines.append("  ")
        lines.append("  # Comparisons")
        lines.append("  if Keyboard == \"secret\":")
        lines.append("      unlock_door()")
        lines.append("  ")
        lines.append("  # Check contents")
        lines.append("  if \"password\" in Keyboard:")
        lines.append("      print(\"Contains password!\")")
        lines.append("  ")
        lines.append("  # Check for submit/cancel")
        lines.append("  if Keyboard.didSubmit():")
        lines.append("      save_data(str(Keyboard))")
        lines.append("      Keyboard.Scheme = Keyboard.Schemes.DEFAULT  # Reset scheme")
        lines.append("  if Keyboard.didCancel():")
        lines.append("      Keyboard = \"\"  # Clear buffer")
        lines.append("  ")
        lines.append("  # Advanced usage")
        lines.append("  Keyboard.start()                        # Begin input (all chars)")
        lines.append("  Keyboard.start(Keyboard.Allow.ALPHA)    # Letters only")
        lines.append("  Keyboard.start(Keyboard.Allow.NUMERIC)  # Numbers only")
        lines.append("  cursor_pos = Keyboard.position()        # Get cursor")
        lines.append("  key = Keyboard.lastKey()                # Last key pressed")
        lines.append("")
        lines.append("Note:")
        lines.append("  - ENTER and ESC automatically call Keyboard.end()")
        lines.append("  - Arrow keys: LEFT/RIGHT move cursor, UP/DOWN jump to start/end")
        lines.append("  - BACKSPACE deletes character before cursor")
        lines.append("  - didSubmit() and didCancel() are one-shot flags (cleared next cycle)")
        lines.append("")

    # Add enable/disable documentation
    lines.append("=" * 80)
    lines.append("ENABLE/DISABLE CONTROLS")
    lines.append("=" * 80)
    lines.append("")
    lines.append("Controls can be enabled or disabled to control whether they report state changes.")
    lines.append("Disabled controls still display their LED indicators but won't trigger changed() events.")
    lines.append("This is useful for greying out controls that aren't relevant in the current mode.")
    lines.append("")
    lines.append("Note: Devices that don't support the ENABLE HID command (sticks, keyboard) will")
    lines.append("silently ignore enable/disable calls - the methods exist but do nothing.")
    lines.append("")
    lines.append("Device-level methods (batch operations, one HID command per board):")
    lines.append("  Device.enable_all()                           # Enable all controls")
    lines.append("  Device.disable_all()                          # Disable all controls")
    lines.append("  Device.enable(Device.Ctrl1, Device.Ctrl2)     # Enable specific controls")
    lines.append("  Device.disable(Device.Ctrl1, Device.Ctrl2)    # Disable specific controls")
    lines.append("")
    lines.append("Control-level property (individual control):")
    lines.append("  Device.Control.Enabled = True                 # Enable single control")
    lines.append("  Device.Control.Enabled = False                # Disable single control")
    lines.append("  if Device.Control.Enabled:                    # Check if enabled")
    lines.append("      ...")
    lines.append("")
    lines.append("Push/pop enable state (for modal states like attract/pause):")
    lines.append("  Device.disable_all(pushState=True)            # Save state, then disable all")
    lines.append("  Device.enable(Device.Ctrl1)                   # Re-enable specific controls (no push)")
    lines.append("  Device.pop_enable()                           # Restore saved state")
    lines.append("")
    lines.append("  pushState=True can be used on any enable/disable method to save state first.")
    lines.append("  The stack supports nesting (multiple pushes). reset() clears the stack.")
    lines.append("")
    lines.append("Example - weapon mode switching:")
    lines.append("  # When entering missile mode, enable missile controls")
    lines.append("  if mode == 'MISSILES':")
    lines.append("      ConsoleSwitches.MissileCount.Scheme = ConsoleSwitches.MissileCount.Schemes.ENABLED")
    lines.append("      ConsoleSwitches.JettisonMines.Scheme = ConsoleSwitches.JettisonMines.Schemes.ENABLED")
    lines.append("      ConsoleSwitches.enable(ConsoleSwitches.MissileCount, ConsoleSwitches.JettisonMines)")
    lines.append("  else:")
    lines.append("      ConsoleSwitches.MissileCount.Scheme = ConsoleSwitches.MissileCount.Schemes.DEFAULT")
    lines.append("      ConsoleSwitches.JettisonMines.Scheme = ConsoleSwitches.JettisonMines.Schemes.DEFAULT")
    lines.append("      ConsoleSwitches.disable(ConsoleSwitches.MissileCount, ConsoleSwitches.JettisonMines)")
    lines.append("")

    # Add example code
    lines.append("=" * 80)
    lines.append("EXAMPLE CODE")
    lines.append("=" * 80)
    lines.append("")
    lines.append("import time")
    lines.append("from pathlib import Path")
    lines.append("from enigma import EnigmaManager, ConfigManager")

    # Add imports
    keyboard_exists = keyboard_config.exists()
    if keyboard_exists and first_device:
        lines.append(f"from generated.controls import {first_device}, Keyboard")
    elif keyboard_exists:
        lines.append("from generated.controls import Keyboard")
    elif first_device:
        lines.append(f"from generated.controls import {first_device}")

    lines.append("")
    lines.append("# Initialize")
    lines.append("config_manager = ConfigManager(Path('configs'))")
    lines.append("manager = EnigmaManager(config_manager)")
    lines.append("manager.start()")
    lines.append("")
    lines.append("# Main loop")
    lines.append("try:")
    lines.append("    while True:")
    lines.append("        manager.update()  # Process HID events")
    lines.append("")
    if first_control and first_value:
        lines.append(f"        # Check for changes")
        lines.append(f"        if {first_device}.{first_control}.changed():")
        lines.append(f"            # Compare using == operator")
        lines.append(f"            if {first_device}.{first_control} == {first_value_path}:")
        lines.append(f"                print(\"Control is now {first_value}\")")
        lines.append(f"                {first_device}.{first_control}.Scheme = {first_scheme}")
    if keyboard_exists:
        lines.append("")
        lines.append("        # Keyboard input example")
        lines.append("        if Keyboard.didSubmit():")
        lines.append("            entered_text = str(Keyboard)")
        lines.append("            print(f\"User entered: {entered_text}\")")
        lines.append("            Keyboard = \"\"  # Clear for next input")
    lines.append("")
    lines.append("        time.sleep(0.01)  # 100Hz")
    lines.append("except KeyboardInterrupt:")
    lines.append("    manager.stop()")
    lines.append("")

    # Write file
    output_file.write_text('\n'.join(lines))
    print(f"Documentation written to {output_file}")


if __name__ == '__main__':
    main()