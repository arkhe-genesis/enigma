# SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
# SPDX-License-Identifier: MIT

"""
SW14 board variant handler - 14 illuminated toggle/momentary switches
"""

import struct
from .base import BoardVariantHandler, BoardConfig, ControlConfig, ControlState
from . import register_board_variant
from enigma.colors import print_error, print_warning

# Switch types (SW14-specific)
TYPE_MOM_OFF_MOM = 0
TYPE_PUSHBUTTON = 1
TYPE_TOGGLE = 2
TYPE_RADIO = 3

# Animation modes (SW14-specific)
MODE_SOLID = 0
MODE_BLINK = 1
MODE_FADE = 2

class SW14ControlState(ControlState):
    """State object for SW14 control
    
    Attributes:
        value: State value (0=off, 1=down/on, 2=up)
        scheme: Current indicator scheme name (default: "default")
    """
    
    def __init__(self, value=0, scheme="default"):
        super().__init__(scheme=scheme)
        self.value = value
    
    def __str__(self):
        """String representation for debugging/CLI"""
        state_names = {0: 'off', 1: 'down/on', 2: 'up'}
        value_str = state_names.get(self.value, f'state_{self.value}')
        
        if self.scheme != "default":
            return f"{value_str} (scheme: {self.scheme})"
        return value_str
    
    def __eq__(self, other):
        if not isinstance(other, SW14ControlState):
            return False
        return self.value == other.value and self.scheme == other.scheme

class SW14StateConfig:
    """Configuration for a single state"""
    
    def __init__(self, state_num, report=0, value=None, colors=None, 
                 mode='solid', period_ms=1000, duty_cycle_ms=0, hold_ms=0):
        self.state_num = state_num
        self.report = report
        self.value = value
        self.colors = colors or ['#ff0000', '#000000']  # [color1, color2]
        self.mode = mode
        
        # Handle defaults for period and duty cycle
        if period_ms == 0:
            period_ms = 500
        self.period_ms = period_ms
        
        if duty_cycle_ms == 0:
            duty_cycle_ms = period_ms // 2
        self.duty_cycle_ms = duty_cycle_ms
        
        self.hold_ms = hold_ms
    
    @staticmethod
    def parse_colors(color_str):
        """Parse color string like '#FF0000' or '#FF0000,#00FF00'
        Returns list of [color1, color2] as hex strings
        """
        if not color_str:
            return ['#ff0000', '#000000']
        
        colors = [c.strip() for c in color_str.split(',')]
        
        if len(colors) == 1:
            # Single color - second is black
            return [colors[0], '#000000']
        else:
            return colors[:2]  # Take first two
    
    @staticmethod
    def hex_to_rgb(hex_color):
        """Convert '#RRGGBB' to (r, g, b) tuple"""
        hex_color = hex_color.lstrip('#')
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    
    def to_bytes(self):
        """Pack state config into 14 bytes (for SETCONFIG)"""
        # Parse colors
        rgb1 = self.hex_to_rgb(self.colors[0])
        rgb2 = self.hex_to_rgb(self.colors[1])
        
        # Map mode string to number
        mode_map = {'solid': MODE_SOLID, 'blink': MODE_BLINK, 'fade': MODE_FADE}
        mode_num = mode_map.get(self.mode.lower(), MODE_SOLID)
        
        # Pack: report(1) + rgb1(3) + rgb2(3) + mode(1) + period(2) + duty(2) + holdms(2)
        return struct.pack('<BBBBBBBBHHH',
                          self.report,
                          rgb1[0], rgb1[1], rgb1[2],
                          rgb2[0], rgb2[1], rgb2[2],
                          mode_num,
                          self.period_ms,
                          self.duty_cycle_ms,
                          self.hold_ms)
    
    def to_indicator_bytes(self):
        """Pack indicator data into 13 bytes (for SETINDICATOR - no report byte)"""
        # Parse colors
        rgb1 = self.hex_to_rgb(self.colors[0])
        rgb2 = self.hex_to_rgb(self.colors[1])
        
        # Map mode string to number
        mode_map = {'solid': MODE_SOLID, 'blink': MODE_BLINK, 'fade': MODE_FADE}
        mode_num = mode_map.get(self.mode.lower(), MODE_SOLID)
        
        # Pack: rgb1(3) + rgb2(3) + mode(1) + period(2) + duty(2) + holdms(2)
        return struct.pack('<BBBBBBBHHH',
                          rgb1[0], rgb1[1], rgb1[2],
                          rgb2[0], rgb2[1], rgb2[2],
                          mode_num,
                          self.period_ms,
                          self.duty_cycle_ms,
                          self.hold_ms)

class SW14ControlConfig(ControlConfig):
    """Configuration for an SW14 control"""
    
    def __init__(self, control_num, name, desc, switch_type, default_state, group, enabled=True):
        super().__init__(control_num, name, desc, enabled=enabled)
        self.switch_type = switch_type
        self.default_state = default_state
        self.group = group
        self.states = {}  # state_num -> SW14StateConfig (the "default" scheme)
        self.schemes = {}  # scheme_name -> {state_num -> SW14StateConfig}
        self.current_scheme = "default"  # Track active scheme
    
    def to_setconfig_payload(self):
        """Pack into SETCONFIG payload (46 bytes for SW14)"""
        payload = struct.pack('<BBBB', self.control_num, self.switch_type, 
                            self.default_state, self.group)
        
        # Pack all 3 states (even if not all defined)
        for state_num in range(3):
            if state_num in self.states:
                payload += self.states[state_num].to_bytes()
            else:
                # Default: don't report, red/black, solid
                default = SW14StateConfig(state_num)
                payload += default.to_bytes()
        
        # Verify payload is exactly 46 bytes
        if len(payload) != 46:
            raise ValueError(f"SW14 SETCONFIG payload must be 46 bytes, got {len(payload)}")
        
        return payload
    
    def get_state_value(self, state_dict):
        """Get value string for a state"""
        state_num = state_dict.get("state") if isinstance(state_dict, dict) else state_dict
        if state_num in self.states:
            return self.states[state_num].value
        return None
    
    def get_indicator_for_scheme(self, scheme_name):
        """Get indicator states (dict) for a given scheme
        
        Returns:
            Dict of {state_num -> SW14StateConfig}, or None if scheme doesn't exist
        """
        if scheme_name == "default":
            return self.states
        
        if scheme_name not in self.schemes:
            return None
        
        return self.schemes[scheme_name]

class SW14BoardConfig(BoardConfig):
    """SW14-specific board configuration"""
    
    def format_state_change(self, control_num, control_state):
        """Format a state change for logging
        Returns string like "PortEngine.AMFA = arm" using configured value strings
        """
        control = self.get_control(control_num)
        if not control:
            return f"{self.name}.Control{control_num} = {control_state}"
        
        # If control has a value string for this state, use it
        if hasattr(control, 'states') and control_state.value in control.states:
            state_config = control.states[control_state.value]
            if state_config.value:
                return f"{self.name}.{control.name} = {state_config.value}"
        
        # Fall back to default string representation
        return f"{self.name}.{control.name} = {control_state}"


def parse_scheme_states(scheme_name, scheme_data, control_num, switch_type):
    """Parse states within a scheme
    
    Returns dict of {state_num -> SW14StateConfig}
    """
    VALID_STATE_KEYS = {'comment', 'report', 'value', 'colors', 'mode', 'period_ms',
                       'duty_cycle_ms', 'hold_ms'}
    VALID_MODES = {'solid', 'blink', 'fade'}
    
    states = {}
    
    # Parse each state in the scheme
    for state_num in range(3):
        state_key = f'state_{state_num}'
        if state_key not in scheme_data:
            continue
            
        state_data = scheme_data[state_key]
        
        # Validate state keys
        unknown_keys = set(state_data.keys()) - VALID_STATE_KEYS
        if unknown_keys:
            print_warning(f"WARNING: Control {control_num} scheme '{scheme_name}' {state_key}: "
                  f"Unknown keys: {unknown_keys}")
        
        report = state_data.get('report', 0)
        if report not in [0, 1]:
            print_warning(f"WARNING: Control {control_num} scheme '{scheme_name}' {state_key}: "
                  f"report should be 0 or 1, got {report}")
        
        value = state_data.get('value')
        colors_str = state_data.get('colors', '#ff0000,#000000')
        
        try:
            colors = SW14StateConfig.parse_colors(colors_str)
        except Exception as e:
            print_error(f"[enigma] ERROR: Control {control_num} scheme '{scheme_name}' {state_key}: "
                  f"Invalid colors '{colors_str}': {e}")
            colors = ['#ff0000', '#000000']
        
        # Validate mode
        mode = state_data.get('mode', 'solid').lower()
        if mode not in VALID_MODES:
            print_error(f"[enigma] ERROR: Control {control_num} scheme '{scheme_name}' {state_key}: "
                  f"Invalid mode '{mode}'. Valid modes: {VALID_MODES}. Defaulting to 'solid'")
            mode = 'solid'
        
        period = state_data.get('period_ms', 1000)
        if not isinstance(period, int) or period <= 0:
            print_warning(f"WARNING: Control {control_num} scheme '{scheme_name}' {state_key}: "
                  f"period_ms should be positive integer, got {period}")
            period = 1000
        
        duty = state_data.get('duty_cycle_ms', 0)
        if duty == 0:
            duty = period // 2
        
        if duty > period:
            print_warning(f"WARNING: Control {control_num} scheme '{scheme_name}' {state_key}: "
                  f"duty_cycle_ms ({duty}) > period_ms ({period})")
        
        hold_ms = state_data.get('hold_ms', 0)
        
        sw14_state = SW14StateConfig(
            state_num=state_num,
            report=report,
            value=value,
            colors=colors,
            mode=mode,
            period_ms=period,
            duty_cycle_ms=duty,
            hold_ms=hold_ms
        )
        
        states[state_num] = sw14_state
    
    # For button/toggle/radio: if 1 state missing and other exists, copy it
    if switch_type in [TYPE_PUSHBUTTON, TYPE_TOGGLE, TYPE_RADIO]:
        if 1 not in states and 2 in states:
            states[1] = states[2]
        elif 2 not in states and 1 in states:
            states[2] = states[1]
    
    return states

class SW14Handler(BoardVariantHandler):
    """Handler for SW14 (14 illuminated switches)"""
    
    VARIANT_ID = 1  # Hardware reports variant 1 for SW14
    TYPE_STR = "SW14"
    NUM_CONTROLS = 14
    
    def __init__(self, device):
        super().__init__(device)
        self.variant_id = self.VARIANT_ID
        self.type_str = self.TYPE_STR
    
    def create_blank_config(self, control_num):
        """Create blank SW14 config - all LEDs off, no reporting"""
        control = SW14ControlConfig(
            control_num=control_num,
            name=f"Unused{control_num}",
            desc="Unconfigured",
            switch_type=TYPE_PUSHBUTTON,
            default_state=0,
            group=0
        )
        
        # Add default blank states
        for state_num in range(3):
            control.states[state_num] = SW14StateConfig(state_num)
        
        return control
    
    def parse_config(self, config_data):
        """Parse SW14 config JSON"""
        board_config = SW14BoardConfig(config_data)
        
        controls = config_data.get('controls', [])
        
        for ctrl_data in controls:
            try:
                control_num = ctrl_data.get('control_num')
                if not control_num or control_num < 1 or control_num > self.NUM_CONTROLS:
                    print(f"[enigma] Invalid control_num: {control_num}")
                    continue
                
                name = ctrl_data.get('name', f'Control{control_num}')
                desc = ctrl_data.get('desc', '')
                default_state = ctrl_data.get('default_state', 0)
                group = ctrl_data.get('group', 0)
                enabled = ctrl_data.get('enabled', True)

                # Parse switch type
                type_str = ctrl_data.get('type', 'button').lower()
                type_map = {
                    'momoffmom': TYPE_MOM_OFF_MOM,
                    'button': TYPE_PUSHBUTTON,
                    'toggle': TYPE_TOGGLE,
                    'pushbutton': TYPE_PUSHBUTTON,
                    'radio': TYPE_RADIO
                }
                switch_type = type_map.get(type_str, TYPE_PUSHBUTTON)

                control = SW14ControlConfig(
                    control_num, name, desc, switch_type, default_state, group,
                    enabled=enabled
                )
                
                # Parse default states (state_0, state_1, state_2)
                for state_num in range(3):
                    state_key = f'state_{state_num}'
                    if state_key in ctrl_data:
                        state_data = ctrl_data[state_key]
                        
                        report = state_data.get('report', 0)
                        value = state_data.get('value')
                        colors_str = state_data.get('colors', '#ff0000,#000000')
                        colors = SW14StateConfig.parse_colors(colors_str)
                        mode = state_data.get('mode', 'solid').lower()
                        period = state_data.get('period_ms', 1000)
                        duty = state_data.get('duty_cycle_ms', 0)
                        if duty == 0:
                            duty = period // 2
                        hold_ms = state_data.get('hold_ms', 0)
                        
                        sw14_state = SW14StateConfig(
                            state_num=state_num,
                            report=report,
                            value=value,
                            colors=colors,
                            mode=mode,
                            period_ms=period,
                            duty_cycle_ms=duty,
                            hold_ms=hold_ms
                        )
                        
                        control.states[state_num] = sw14_state
                
                # For button/toggle/radio: if 1 state missing and other exists, copy it
                if switch_type in [TYPE_PUSHBUTTON, TYPE_TOGGLE, TYPE_RADIO]:
                    if 1 not in control.states and 2 in control.states:
                        control.states[1] = control.states[2]
                    elif 2 not in control.states and 1 in control.states:
                        control.states[2] = control.states[1]
                
                # Parse schemes
                schemes_data = ctrl_data.get('schemes', {})
                for scheme_name, scheme_states_data in schemes_data.items():
                    scheme_states = parse_scheme_states(
                        scheme_name, scheme_states_data, control_num, switch_type
                    )
                    control.schemes[scheme_name] = scheme_states
                
                board_config.controls[control_num] = control
                
            except Exception as e:
                print_error(f"[enigma] Error parsing control {ctrl_data.get('control_num')}: {e}")
                import traceback
                traceback.print_exc()
        
#        print(f"Loaded config '{board_config.name}' with {len(board_config.controls)} controls")
        return board_config
    
    # Low-level pack/parse (internal use)
    
    def _pack_state(self, control_state):
        """Pack SW14ControlState into bytes"""
        if not isinstance(control_state, SW14ControlState):
            raise TypeError(f"Expected SW14ControlState, got {type(control_state).__name__}")
        
        if not (0 <= control_state.value <= 2):
            raise ValueError(f"SW14 state value must be 0-2, got {control_state.value}")
        
        return struct.pack('<B', control_state.value)
    
    def _parse_state(self, state_data, control_num=None):
        """Parse bytes into SW14ControlState"""
        if len(state_data) < 1:
            return SW14ControlState(value=0)
        
        value = state_data[0]
        
        # Don't include scheme in state - scheme is visual only, not functional state
        return SW14ControlState(value=value, scheme="default")
    
    def get_control_count(self):
        return self.NUM_CONTROLS
    
    def get_control_schemes(self, control_num):
        """Get list of available scheme names for a control
        
        Args:
            control_num: Control number
            
        Returns:
            List of scheme names (always includes 'default')
        """
        if not self.config:
            return ["default"]
        
        control = self.config.controls.get(control_num)
        if not control:
            return ["default"]
        
        # Always have default, plus any defined schemes
        schemes = ["default"]
        if hasattr(control, 'schemes'):
            schemes.extend(control.schemes.keys())
        
        return schemes
    
    def get_all_schemes(self):
        """Get all unique scheme names across all controls
        
        Returns:
            Set of scheme names
        """
        if not self.config:
            return {"default"}
        
        schemes = {"default"}
        for control in self.config.controls.values():
            if hasattr(control, 'schemes'):
                schemes.update(control.schemes.keys())
        
        return schemes
    
    def set_control_state(self, control_num, control_state):
        """Set control state with radio group handling

        SW14 override: after setting a control, clears other controls in the
        same radio group (same name) so reads reflect the correct active control.
        """
        # Call base implementation
        super().set_control_state(control_num, control_state)

        # Radio group handling: if this control went non-zero, clear others in group
        if not self.config:
            return

        control_config = self.config.controls.get(control_num)
        if control_config and control_state.value != 0:
            # Find all other controls with the same name (radio group)
            control_name = control_config.name
            for other_num, other_config in self.config.controls.items():
                if other_num != control_num and other_config.name == control_name:
                    # Clear this control's cache to state 0
                    zero_state = bytes([0])
                    self.device.current_states[other_num] = zero_state
                    self._cached_states[other_num] = zero_state

    def set_control_by_value(self, control_num, value):
        """Set SW14 control by value string, state number, or ControlState

        Args:
            control_num: Control number
            value: String value (e.g., 'auto', 'arm'), int state number (0-2), or SW14ControlState

        Returns:
            True if successful, False otherwise
        """
        # If already a ControlState, use directly
        if isinstance(value, SW14ControlState):
            self.set_control_state(control_num, value)
            return True
        
        # If int, create ControlState directly
        if isinstance(value, int):
            if 0 <= value <= 2:
                self.set_control_state(control_num, SW14ControlState(value=value))
                return True
            return False
        
        # If string, look up which state has this value
        if isinstance(value, str):
            control_config = self.config.controls.get(control_num) if self.config else None
            if control_config and hasattr(control_config, 'states'):
                for state_num, state_config in control_config.states.items():
                    if state_config.value == value:
                        self.set_control_state(control_num, SW14ControlState(value=state_num))
                        return True
        
        return False
    
    def get_all_control_schemes(self) -> dict:
        """Get current scheme name for all controls."""
        if not self.config:
            return {}
        return {ctrl.name: ctrl.current_scheme for ctrl in self.config.controls.values()}

    def set_indicator_scheme(self, scheme_name="default", control_name=""):
        """Set indicator scheme for controls
        
        Args:
            scheme_name: Name of scheme to activate (default: "default")
            control_name: Control name to update, or "" for all controls (default: "")
        
        Returns:
            Number of controls actually updated
        """
        
        if not self.config:
            print_error("[enigma] ERROR: No config loaded")
            return 0
        
        updated_count = 0
        
        # Determine which controls to update
        if control_name == "":
            # Update all controls
            target_controls = list(self.config.controls.values())
        else:
            # Update controls with matching name
            target_controls = [c for c in self.config.controls.values() 
                             if c.name == control_name]
        
        if not target_controls:
            print(f"[enigma] No controls found matching name '{control_name}'")
            return 0
       
        # Update each control
        for control in target_controls:
            # Check if this control has the requested scheme
            if scheme_name != "default" and scheme_name not in control.schemes:
                # Control doesn't have this scheme, skip it
                continue
            
            # Check if already at this scheme
            if control.current_scheme == scheme_name:
                # Already displaying this scheme, skip
                continue
            
            # Get the scheme's states
            scheme_states = control.get_indicator_for_scheme(scheme_name)
            if scheme_states is None:
                print_error(f"[enigma] ERROR: Control {control.control_num} ({control.name}): "
                      f"Scheme '{scheme_name}' not found")
                continue
            
            # Pack indicator data (39 bytes = 3 states x 13 bytes)
            indicator_data = b''
            for state_num in range(3):
                if state_num in scheme_states:
                    state_config = scheme_states[state_num]
                    indicator_data += state_config.to_indicator_bytes()  # Use 13-byte format
                else:
                    # Error state: 500ms red blink
                    error_state = SW14StateConfig(
                        state_num,
                        report=0,
                        colors=['#ff0000', '#000000'],
                        mode='blink',
                        period_ms=500,
                        duty_cycle_ms=250
                    )
                    indicator_data += error_state.to_indicator_bytes()  # Use 13-byte format
            
            # Send SETINDICATOR command
            try:
                self.device.set_indicator(control.control_num, indicator_data)
                control.current_scheme = scheme_name
                updated_count += 1
            except Exception as e:
                print_error(f"[enigma] ERROR: Failed to set scheme for control {control.control_num}: {e}")
        
        # Update device's active scheme if any controls were updated
        if updated_count > 0:
            self.device.active_scheme = scheme_name
        
        return updated_count
    
    def on_hardware_state_report(self, control_num, state_data):
        """Handle hardware-reported state change

        SW14 override: also handles radio group clearing
        """
        # Update cache
        self._cached_states[control_num] = state_data
        self._hardware_changed.add(control_num)

        # Radio group handling: if this control went non-zero, clear others in group
        if not self.config:
            return

        control_state = self._parse_state(state_data, control_num)
        control_config = self.config.controls.get(control_num)

        if control_config and control_state.value != 0:
            # Find all other controls with the same name (radio group)
            control_name = control_config.name
            for other_num, other_config in self.config.controls.items():
                if other_num != control_num and other_config.name == control_name:
                    # Clear this control to state 0
                    zero_state = bytes([0])
                    self.device.current_states[other_num] = zero_state
                    self._cached_states[other_num] = zero_state

    def reset(self, full_reset=False, send_to_hardware=True):
        """Reset handler state - sets controls to default state and schemes

        Args:
            full_reset: If True, clears all cached values (nuclear reset).
                       If False, preserves non-default values for sync.
            send_to_hardware: If True, send SETSTATE commands. If False, just update tracking.
        """
        self._reset_to_defaults(full_reset=full_reset, send_to_hardware=send_to_hardware)
        super().reset(full_reset=full_reset)

    def _reset_to_defaults(self, full_reset=False, send_to_hardware=True):
        """Reset all controls to their default state

        Args:
            full_reset: If True, clears all cached values (nuclear reset).
                       If False, preserves non-default values for sync.
            send_to_hardware: If True, send SETSTATE commands. If False, just update tracking.
        """
        if not self.config:
            return

        for control in self.config.controls.values():
            control_num = control.control_num
            default_state = control.default_state

            # Pack default state bytes
            default_state_data = struct.pack('<B', default_state)

            should_update = False
            if full_reset:
                # Nuclear reset - always set to default
                should_update = True
            else:
                # Preserve non-default values for sync_state_to_device to restore
                cached = self._cached_states.get(control_num)
                if cached is None or cached == default_state_data:
                    should_update = True

            if should_update:
                if send_to_hardware:
                    # Clear cache so SETSTATE actually sends
                    if control_num in self._cached_states:
                        del self._cached_states[control_num]

                    # Send to hardware
                    try:
                        self.device.set_state(control_num, default_state_data)
                    except Exception as e:
                        print_error(f"[enigma] [SW14] Failed to set default state for control {control_num}: {e}")

                # Update Python-side tracking and cache
                self.device.current_states[control_num] = default_state_data
                self._cached_states[control_num] = default_state_data

    def sync_state_to_device(self):
        """Sync cached state and scheme values to device on (re)connect.

        Sends SETSTATE for any controls where our cached value differs from
        the default, and SETINDICATOR for any controls with non-default schemes.
        This restores programmatically-set values after device reconnection
        (e.g., after sleep/wake or device reboot).
        """
        if not self.config:
            return

        synced_states = 0
        synced_schemes = 0

        for control in self.config.controls.values():
            control_num = control.control_num

            # Sync state if different from default
            default_state = control.default_state
            default_state_data = struct.pack('<B', default_state)
            cached = self._cached_states.get(control_num)
            if cached is not None and cached != default_state_data:
                self.device.set_state(control_num, cached)
                synced_states += 1

            # Sync scheme if not default
            if hasattr(control, 'current_scheme') and control.current_scheme != "default":
                # Re-apply the non-default scheme
                scheme_name = control.current_scheme
                # Temporarily set to "default" so set_indicator_scheme will process it
                control.current_scheme = "default"
                if self.set_indicator_scheme(scheme_name, control.name) > 0:
                    synced_schemes += 1

        if synced_states > 0 or synced_schemes > 0:
            print(f"[enigma]   Synced to device: {synced_states} state(s), {synced_schemes} scheme(s)")

        # Sync enable mask to hardware
        super().sync_state_to_device()

    def reset_schemes(self, full_reset=False):
        """Reset scheme tracking (called on RESET)

        Args:
            full_reset: If True, reset schemes to default (nuclear reset).
                       If False, preserve for sync_state_to_device().
        """
        if not self.config:
            return

        if full_reset:
            # Nuclear reset - clear all schemes to default
            for control in self.config.controls.values():
                control.current_scheme = "default"
        # Otherwise preserve current_scheme for sync_state_to_device()

# Register this variant
register_board_variant(SW14Handler.VARIANT_ID, SW14Handler.TYPE_STR, SW14Handler)
