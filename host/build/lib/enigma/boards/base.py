# SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
# SPDX-License-Identifier: MIT

"""
Base class for board variant handlers
"""

import json
import struct
from pathlib import Path

from enigma.colors import print_error

class ControlState:
    """Base class for control state objects

    Subclasses provide board-specific state representations.
    All subclasses should have 'scheme' attribute for uniformity.
    """

    def __init__(self, scheme="default"):
        self.scheme = scheme

    def __str__(self):
        """String representation for debugging/CLI"""
        raise NotImplementedError("Subclass must implement __str__")

    def __repr__(self):
        return self.__str__()

class ControlConfig:
    """Base class for control configuration"""

    def __init__(self, control_num, name=None, desc=None, enabled=True):
        self.control_num = control_num
        self.name = name or f"Control{control_num}"
        self.desc = desc or ""
        self.enabled = enabled

    def to_setconfig_payload(self):
        """Pack this config into SETCONFIG payload bytes
        Returns bytes to send (board-variant specific)
        """
        raise NotImplementedError("Subclass must implement to_setconfig_payload")

    def get_state_value(self, state_dict):
        """Get the value string for a given state (for reporting)
        Returns None if state doesn't report or doesn't exist

        Args:
            state_dict: Parsed state dictionary from handler
        """
        raise NotImplementedError("Subclass must implement get_state_value")

class BoardConfig:
    """Base class for board configuration (collection of controls)"""

    def __init__(self, config_data):
        self.name = config_data.get('name', 'Unknown')
        self.controls = {}  # control_num -> ControlConfig

    def get_control(self, control_num):
        """Get config for a specific control"""
        return self.controls.get(control_num)

    def get_control_by_name(self, name):
        """Get first control config with matching name

        Args:
            name: Control name to find

        Returns:
            ControlConfig or None if not found
        """
        for ctrl in self.controls.values():
            if ctrl.name == name:
                return ctrl
        return None

    def format_state_change(self, control_num, control_state):
        """Format a state change for logging
        Returns string like "PortEngine.AMFA = arm"

        Args:
            control_num: Control number
            control_state: ControlState object
        """
        control = self.get_control(control_num)
        if not control:
            return f"{self.name}.Control{control_num} = {control_state}"

        return f"{self.name}.{control.name} = {control_state}"

class BoardVariantHandler:
    """Base class for board-specific protocol handling"""

    def __init__(self, device):
        self.device = device
        self.variant_id = None
        self.type_str = None
        self.config = None  # BoardConfig instance
        self._cached_states = {}  # control_num -> packed state bytes
        self._hardware_changed = set()  # control_nums changed by hardware this cycle

    def calculate_config_crc(self):
        """Calculate CRC32 of all control configs (matching MCU)"""
        import zlib

        if not self.config:
            return 0

        all_data = b''

        # Iterate through ALL possible control numbers
        for control_num in range(1, self.get_control_count() + 1):
            if control_num in self.config.controls:
                control_config = self.config.controls[control_num]
            else:
                control_config = self.create_blank_config(control_num)

            payload = control_config.to_setconfig_payload()
            all_data += payload

        if len(all_data) == 0:
            return 0

        crc = zlib.crc32(all_data) & 0xFFFFFFFF
        return crc

    def load_config(self, config_file):
        """Load configuration from JSON file

        Args:
            config_file: Path to JSON config file

        Returns:
            True if successful
        """
        try:
            with open(config_file, 'r') as f:
                config_data = json.load(f)

            self.config = self.parse_config(config_data)
            return True
        except Exception as e:
            print_error(f"[enigma] Error loading config {config_file}: {e}")
            return False

    def parse_config(self, config_data):
        """Parse config JSON into BoardConfig (variant-specific)

        Args:
            config_data: Parsed JSON dict

        Returns:
            BoardConfig subclass instance
        """
        raise NotImplementedError("Subclass must implement parse_config")

    def send_all_configs(self, delay_ms=100, send_blanks=False):
        """Send all control configs to device

        Args:
            delay_ms: Delay between config sends
            send_blanks: If True, send blank configs for unconfigured controls

        Returns:
            True if all configs sent successfully
        """
        if not self.config:
            return False

        import time
        success = True

        for control_num in range(1, self.get_control_count() + 1):
            if control_num in self.config.controls:
                control_config = self.config.controls[control_num]
            elif send_blanks:
                control_config = self.create_blank_config(control_num)
            else:
                continue

            payload = control_config.to_setconfig_payload()

            # Send through device (no callback, fire and forget)
            try:
                self.device.set_config(payload)
                time.sleep(delay_ms / 1000.0)  # Give MCU time to process and store
            except Exception as e:
                print_error(f"[enigma] Failed to send config for control {control_num}: {e}")
                success = False

        return success

    def create_blank_config(self, control_num):
        """Create a blank/default config for an unused control

        Subclass should override to create appropriate default
        """
        raise NotImplementedError("Subclass must implement create_blank_config")

    # Low-level pack/parse methods (internal use)

    def _pack_state(self, control_state):
        """Pack ControlState object into bytes for wire protocol (LOW-LEVEL)

        Args:
            control_state: Board-specific ControlState subclass instance

        Returns:
            bytes to send as SETSTATE payload (after control number)
        """
        raise NotImplementedError("Subclass must implement _pack_state")

    def _parse_state(self, state_data, control_num=None):
        """Parse state bytes into ControlState object (LOW-LEVEL)

        Args:
            state_data: bytes from REPORTSTATE/GETSTATE
            control_num: Optional control number (needed for incremental mode tracking)

        Returns:
            Board-specific ControlState subclass instance
        """
        raise NotImplementedError("Subclass must implement _parse_state")

    # High-level client-facing interface

    def set_control_state(self, control_num, control_state):
        """Set control state (HIGH-LEVEL, client-facing)

        Args:
            control_num: Control number
            control_state: Board-specific ControlState object
        """
        state_data = self._pack_state(control_state)

        # Check cache - only send if state actually changed
        if control_num in self._cached_states:
            if self._cached_states[control_num] == state_data:
                return  # State unchanged, skip HID command

        # Log TX if debug_tx is enabled
        from ..manager import get_manager
        manager = get_manager()
        if manager and manager.debug_tx and self.config:
            msg = self.config.format_state_change(control_num, control_state)
            device_name = self.config.name
            print(f"[enigma] [{device_name}] {msg} (TX)")

        # Cache and send
        self._cached_states[control_num] = state_data
        self.device.set_state(control_num, state_data)

        # Update current_states so reads reflect the new state immediately
        self.device.current_states[control_num] = state_data

    def on_hardware_state_report(self, control_num, state_data):
        """Handle hardware-reported state change

        Called by manager when hardware reports a state change.
        Updates cache and handles any board-specific logic (e.g., radio groups).

        Args:
            control_num: Control number
            state_data: Raw state bytes from hardware
        """
        self._cached_states[control_num] = state_data
        self._hardware_changed.add(control_num)

    def clear_hardware_changed(self):
        """Clear hardware change tracking. Called by manager at start of each update cycle."""
        self._hardware_changed.clear()

    def is_hardware_changed(self, control_num):
        """Check if a control was changed by hardware this cycle."""
        return control_num in self._hardware_changed

    def set_control_by_value(self, control_num, value):
        """Set control state by value (string, int, or ControlState)

        Handles conversion of value strings to appropriate ControlState objects.
        Subclasses must override to provide board-specific behavior.

        Args:
            control_num: Control number
            value: String value (e.g., 'auto'), int state number, or ControlState object

        Returns:
            True if successful, False otherwise
        """
        # If already a ControlState, use directly
        if isinstance(value, ControlState):
            self.set_control_state(control_num, value)
            return True

        # Default: not implemented
        return False

    def get_control_state(self, control_num, callback=None):
        """Get control state (HIGH-LEVEL, client-facing)

        Args:
            control_num: Control number
            callback: Optional callback(control_state, error) called with ControlState object
        """
        def internal_callback(state_data, message=None):
            if message:
                if callback:
                    callback(None, message)
            else:
                control_state = self._parse_state(state_data)
                if callback:
                    callback(control_state, None)

        self.device.get_state(control_num, callback=internal_callback)

    def get_control_count(self):
        """Get number of controls on this board"""
        raise NotImplementedError("Subclass must implement get_control_count")

    def get_control_name(self, control_num):
        """Get descriptive name for a control"""
        if self.config:
            control = self.config.get_control(control_num)
            if control:
                return control.name

        if not self.validate_control_number(control_num):
            return f"Invalid Control {control_num}"
        return f"Control {control_num}"

    def validate_control_number(self, control_num):
        """Check if control number is valid"""
        return 1 <= control_num <= self.get_control_count()

    def set_indicator_scheme(self, scheme_name="default", control_name=""):
        """Set indicator scheme for controls

        Default implementation does nothing - only boards with scheme support override this.

        Args:
            scheme_name: Name of scheme to activate (default: "default")
            control_name: Control name to update, or "" for all controls (default: "")

        Returns:
            Number of controls actually updated
        """
        #print(f"WARNING: Board type {self.type_str} does not support indicator schemes")
        return 0

    def _compute_config_default_mask(self):
        """Build enable mask from control config 'enabled' flags.

        Returns uint16 where bit (N-1) = 1 if control N is enabled.
        Controls without an explicit 'enabled' flag default to enabled.
        """
        if not self.config:
            return 0xFFFF
        mask = 0xFFFF
        for num, ctrl in self.config.controls.items():
            if not getattr(ctrl, 'enabled', True):
                if 1 <= num <= 16:
                    mask &= ~(1 << (num - 1))
        return mask

    def reset(self, full_reset=False):
        """Reset handler state (called when board receives RESET command)

        Args:
            full_reset: If True, clears all cached values (nuclear reset for game restart).
                       If False, preserves non-default values for sync_state_to_device().

        Subclasses should override to reset control values, schemes, etc.
        Always call super().reset() to ensure base behavior runs.
        """
        self.reset_schemes(full_reset=full_reset)
        # Reset enable mask to config defaults (or all-enabled if no config)
        self._enable_mask = getattr(self, '_config_default_mask', 0xFFFF)
        self._enable_stack = []
        self._scheme_stack = []

    def sync_state_to_device(self):
        """Sync cached state values to device on (re)connect.

        Called after device configuration is complete. Sends SETSTATE for any
        controls where our cached value differs from the default. This restores
        programmatically-set values after device reconnection.

        Subclasses should call super().sync_state_to_device() to sync the enable mask.
        """
        # Send enable mask to hardware if not all-enabled
        if self._enable_mask != 0xFFFF:
            self.send_enable_mask(self._enable_mask)

    def send_enable_mask(self, mask: int):
        """Send enable/disable bitmask to device

        Args:
            mask: uint16 bitmask, bit N-1 = control N (1=enabled, 0=disabled).
                  0xFFFF = all enabled, 0x0000 = all disabled.

        Note: Silently does nothing for devices that don't support ENABLE command.
        """
        if self.device and hasattr(self.device, 'set_enable_mask'):
            self.device.set_enable_mask(mask)

    def get_enable_mask(self) -> int:
        """Get current enable mask (defaults to all enabled)"""
        if not hasattr(self, '_enable_mask'):
            self._enable_mask = 0xFFFF
        return self._enable_mask

    def set_enable_mask(self, mask: int):
        """Set enable mask and send to device if changed

        Args:
            mask: uint16 bitmask, bit N-1 = control N (1=enabled, 0=disabled)
        """
        if not hasattr(self, '_enable_mask'):
            self._enable_mask = 0xFFFF

        if mask != self._enable_mask:
            self._enable_mask = mask
            self.send_enable_mask(mask)

    def _push_if_requested(self, pushState):
        """Save current enable mask to stack if pushState is True"""
        if pushState:
            if not hasattr(self, '_enable_stack'):
                self._enable_stack = []
            self._enable_stack.append(self.get_enable_mask())

    def enable_all(self, pushState=False):
        """Enable all controls"""
        self._push_if_requested(pushState)
        self.set_enable_mask(0xFFFF)

    def disable_all(self, pushState=False):
        """Disable all controls"""
        self._push_if_requested(pushState)
        self.set_enable_mask(0x0000)

    def enable_controls(self, control_nums: list, pushState=False):
        """Enable specific controls by control number

        Args:
            control_nums: List of control numbers to enable
            pushState: If True, save current mask before modifying
        """
        self._push_if_requested(pushState)
        mask = self.get_enable_mask()
        for num in control_nums:
            if 1 <= num <= 16:
                mask |= (1 << (num - 1))
        self.set_enable_mask(mask)

    def disable_controls(self, control_nums: list, pushState=False):
        """Disable specific controls by control number

        Args:
            control_nums: List of control numbers to disable
            pushState: If True, save current mask before modifying
        """
        self._push_if_requested(pushState)
        mask = self.get_enable_mask()
        for num in control_nums:
            if 1 <= num <= 16:
                mask &= ~(1 << (num - 1))
        self.set_enable_mask(mask)

    def enable_controls_by_name(self, control_names: list, pushState=False):
        """Enable controls by name

        Args:
            control_names: List of control names to enable
            pushState: If True, save current mask before modifying
        """
        if not self.config:
            return
        control_nums = []
        for name in control_names:
            for num, ctrl in self.config.controls.items():
                if ctrl.name == name:
                    control_nums.append(num)
        if control_nums:
            self.enable_controls(control_nums, pushState=pushState)

    def disable_controls_by_name(self, control_names: list, pushState=False):
        """Disable controls by name

        Args:
            control_names: List of control names to disable
            pushState: If True, save current mask before modifying
        """
        if not self.config:
            return
        control_nums = []
        for name in control_names:
            for num, ctrl in self.config.controls.items():
                if ctrl.name == name:
                    control_nums.append(num)
        if control_nums:
            self.disable_controls(control_nums, pushState=pushState)

    def set_controls_enabled(self, control_names: list, enabled: bool, pushState=False):
        """Enable or disable a named list of controls, with optional state push.

        Parallel to set_indicator_scheme - takes a list of names rather than a bitmask.

        Args:
            control_names: List of control names to update
            enabled: True to enable, False to disable
            pushState: If True, push current enable mask before modifying
        """
        import logging
        if not self.config:
            logging.getLogger(__name__).warning(
                "set_controls_enabled: no config on board handler")
            return
        control_nums = []
        for name in control_names:
            for num, ctrl in self.config.controls.items():
                if ctrl.name == name:
                    control_nums.append(num)
        if not control_nums:
            logging.getLogger(__name__).warning(
                f"set_controls_enabled: no controls found for names {control_names}")
            return
        logging.getLogger(__name__).debug(
            f"set_controls_enabled: {'enabling' if enabled else 'disabling'} "
            f"controls {control_names} (nums {control_nums}), pushState={pushState}")
        if enabled:
            self.enable_controls(control_nums, pushState=pushState)
        else:
            self.disable_controls(control_nums, pushState=pushState)

    def get_all_control_schemes(self) -> dict:
        """Get current scheme name for all controls. Returns {name: scheme_name}.
        Subclasses with scheme support override this."""
        return {}

    def push_scheme(self, control_names=None):
        """Save current scheme state to stack.

        Args:
            control_names: List of control names to save, or None for all controls.
        """
        if not hasattr(self, '_scheme_stack'):
            self._scheme_stack = []
        all_schemes = self.get_all_control_schemes()
        if control_names is None:
            saved = dict(all_schemes)
        else:
            saved = {name: all_schemes.get(name, 'default') for name in control_names}
        self._scheme_stack.append(saved)

    def pop_scheme(self):
        """Restore scheme state from stack. Warns if stack is empty."""
        if not hasattr(self, '_scheme_stack') or not self._scheme_stack:
            import logging
            logging.getLogger(__name__).warning("pop_scheme() called on empty stack")
            return
        saved = self._scheme_stack.pop()
        for name, scheme in saved.items():
            self.set_indicator_scheme(scheme, name)

    def clear_scheme_stack(self):
        """Clear the scheme stack without restoring any state."""
        if hasattr(self, '_scheme_stack'):
            self._scheme_stack.clear()

    def clear_enable_stack(self):
        """Clear the enable mask stack without restoring any state"""
        if hasattr(self, '_enable_stack'):
            self._enable_stack.clear()

    def pop_enable_mask(self):
        """Restore enable mask from stack

        Warns if stack is empty.
        """
        if not hasattr(self, '_enable_stack') or not self._enable_stack:
            import logging
            logging.getLogger(__name__).warning("pop_enable_mask() called on empty stack")
            return
        self.set_enable_mask(self._enable_stack.pop())

    def is_control_enabled(self, control_num: int) -> bool:
        """Check if a control is enabled

        Args:
            control_num: Control number to check

        Returns:
            True if enabled, False if disabled
        """
        if not 1 <= control_num <= 16:
            return False
        mask = self.get_enable_mask()
        return bool(mask & (1 << (control_num - 1)))

    def reset_schemes(self, full_reset=False):
        """Reset all controls to default scheme (called on RESET)

        Args:
            full_reset: If True, actually reset schemes to default.
                       If False, preserve for sync_state_to_device().

        Default implementation does nothing - only boards with scheme support override this.
        """
        pass
