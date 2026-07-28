# SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
# SPDX-License-Identifier: MIT

"""
QD04 board variant handler - 4 quadrature encoder knobs with LED rings
"""

import struct
from enum import IntEnum
from .base import BoardVariantHandler, BoardConfig, ControlConfig, ControlState
from . import register_board_variant
from enigma.colors import print_error, print_warning

# Mode flag bits (packed into single byte for SETCONFIG)
MODE_FLAG_BACKGROUND_RANGED = 0x01  # Bit 0: 0=gradient, 1=ranged
MODE_FLAG_ACTIVE_TICK = 0x02        # Bit 1: 0=bar, 1=tick (single LED)
MODE_FLAG_AB_REVERSED = 0x04        # Bit 2: 0=normal, 1=A/B wiring reversed
MODE_FLAG_INCREMENTAL = 0x08        # Bit 3: 0=absolute, 1=incremental reporting

# Background display modes (bit 0 of mode flags)
class BackgroundMode(IntEnum):
    GRADIENT = 0
    RANGED = 1

# Active display modes (bit 1 of mode flags)
class ActiveMode(IntEnum):
    BAR = 0
    TICK = 1

# Count modes (bit 3 of mode flags)
class CountMode(IntEnum):
    ABSOLUTE = 0
    INCREMENTAL = 1

# Legacy alias for backward compatibility in code (not JSON)
DialMode = BackgroundMode

# Active region blend modes
class BlendMode(IntEnum):
    BRIGHTEN = 0
    REPLACE = 1
    ADDITIVE = 2
    MULTIPLY = 3
    SCREEN = 4
    ALPHA = 5

# Animation modes
class AnimMode(IntEnum):
    SOLID = 0
    BLINK = 1
    FADE = 2

# Button modes
class ButtonMode(IntEnum):
    MOMENTARY = 0
    TOGGLE = 1

class QD04ControlState(ControlState):
    """State object for QD04 control
    
    Attributes:
        position: LED position (0 to num_leds-1)
        button: Button state (0=released, 1=pressed)
        value: Real-world value (mapped from position using min/max)
        scheme: Current indicator scheme name (default: "default")
    """
    
    def __init__(self, position=0, button=0, value=None, scheme="default"):
        super().__init__(scheme=scheme)
        self.position = position
        self.button = button
        self.value = value  # Will be set by handler based on config
    
    def __str__(self):
        """String representation for debugging/CLI"""
        button_str = "pressed" if self.button else "released"
        
        if self.value is not None:
            value_part = f"value={self.value:.2f}, "
        else:
            value_part = ""
        
        result = f"{value_part}position={self.position}, button={button_str}"
        
        if self.scheme != "default":
            result += f" (scheme: {self.scheme})"
        
        return result
    
    def __eq__(self, other):
        if not isinstance(other, QD04ControlState):
            return False
        return (self.position == other.position and 
                self.button == other.button and 
                self.scheme == other.scheme)

class QD04DialConfig:
    """Configuration for dial display"""

    def __init__(self, background_mode=BackgroundMode.GRADIENT, active_mode=ActiveMode.BAR,
                 zones=None, start_color=None, end_color=None,
                 active_render=BlendMode.BRIGHTEN, overlay_color='#FFFFFF',
                 anim_mode=AnimMode.SOLID, anim_period=1000, anim_duty=0):
        self.background_mode = background_mode
        self.active_mode = active_mode
        self.zones = zones or []  # For ranged mode: [{"threshold": N, "color": "#RRGGBB"}, ...]
        self.start_color = start_color or '#0000FF'  # For gradient mode
        self.end_color = end_color or '#FF0000'      # For gradient mode
        self.active_render = active_render
        self.overlay_color = overlay_color
        self.anim_mode = anim_mode
        self.anim_period = anim_period
        self.anim_duty = anim_duty
    
    @staticmethod
    def hex_to_argb(hex_color):
        """Convert '#RRGGBB' or '#AARRGGBB' to (a, r, g, b)"""
        hex_color = hex_color.lstrip('#')
        
        if len(hex_color) == 6:
            # RGB only - default alpha to FF
            return (255,
                   int(hex_color[0:2], 16),
                   int(hex_color[2:4], 16),
                   int(hex_color[4:6], 16))
        elif len(hex_color) == 8:
            # ARGB
            return (int(hex_color[0:2], 16),
                   int(hex_color[2:4], 16),
                   int(hex_color[4:6], 16),
                   int(hex_color[6:8], 16))
        else:
            raise ValueError(f"Invalid hex color: {hex_color}")
    
    @staticmethod
    def hex_to_rgb(hex_color):
        """Convert '#RRGGBB' to (r, g, b) tuple"""
        hex_color = hex_color.lstrip('#')
        if len(hex_color) >= 6:
            return (int(hex_color[0:2], 16),
                   int(hex_color[2:4], 16),
                   int(hex_color[4:6], 16))
        raise ValueError(f"Invalid hex color: {hex_color}")
    
    def to_bytes(self, num_leds, reverse=False, count_mode=CountMode.ABSOLUTE):
        """Pack dial config into bytes for SETCONFIG

        Args:
            num_leds: Number of LEDs (also used for granularity in incremental mode)
            reverse: True if A/B wiring is reversed
            count_mode: ABSOLUTE or INCREMENTAL

        Structure depends on background_mode (gradient vs ranged)
        """
        # Build mode flags bitset
        mode_flags = 0
        if self.background_mode == BackgroundMode.RANGED:
            mode_flags |= MODE_FLAG_BACKGROUND_RANGED
        if self.active_mode == ActiveMode.TICK:
            mode_flags |= MODE_FLAG_ACTIVE_TICK
        if reverse:
            mode_flags |= MODE_FLAG_AB_REVERSED
        if count_mode == CountMode.INCREMENTAL:
            mode_flags |= MODE_FLAG_INCREMENTAL

        # Parse overlay color (ARGB)
        overlay_argb = self.hex_to_argb(self.overlay_color)

        # Base config: mode_flags(1) + active_render(1) + overlay(4) + anim_mode(1) + period(2) + duty(2)
        payload = struct.pack('<BB4BBHH',
                             mode_flags,
                             self.active_render,
                             overlay_argb[0], overlay_argb[1], overlay_argb[2], overlay_argb[3],
                             self.anim_mode,
                             self.anim_period,
                             self.anim_duty)

        # Mode-specific data (based on background_mode)
        if self.background_mode == BackgroundMode.GRADIENT:
            # Gradient: start_color(3) + end_color(3)
            start_rgb = self.hex_to_rgb(self.start_color)
            end_rgb = self.hex_to_rgb(self.end_color)
            payload += struct.pack('<3B3B', *start_rgb, *end_rgb)

        elif self.background_mode == BackgroundMode.RANGED:
            # Ranged: num_zones(1) + zones[](threshold(1) + color(3))
            num_zones = min(len(self.zones), 12)  # Limit to 12 zones

            payload += struct.pack('<B', num_zones)

            for zone in self.zones[:num_zones]:
                threshold = zone['threshold']
                color_rgb = self.hex_to_rgb(zone['color'])
                payload += struct.pack('<B3B', threshold, *color_rgb)

        return payload

class QD04AccelerationConfig:
    """Configuration for incremental encoder acceleration"""

    def __init__(self, max_multiplier=1.0, ramp_speed=30.0, dead_zone=5.0):
        self.max_multiplier = max_multiplier  # Max speedup at fast rotation
        self.ramp_speed = ramp_speed          # Reports/sec to reach max_multiplier
        self.dead_zone = dead_zone            # Reports/sec below which = no acceleration

    def calculate_multiplier(self, reports_per_second):
        """Calculate acceleration multiplier based on current speed

        Uses exponential easing for smooth feel.
        """
        if reports_per_second <= self.dead_zone:
            return 1.0

        if reports_per_second >= self.ramp_speed:
            return self.max_multiplier

        # Exponential interpolation between dead_zone and ramp_speed
        # normalized: 0 at dead_zone, 1 at ramp_speed
        normalized = (reports_per_second - self.dead_zone) / (self.ramp_speed - self.dead_zone)

        # Exponential easing: slow start, accelerates as you go faster
        # Using ease-in curve: t^2 feels natural for this
        eased = normalized * normalized

        # Interpolate between 1.0 and max_multiplier
        return 1.0 + (self.max_multiplier - 1.0) * eased


class QD04ControlConfig(ControlConfig):
    """Configuration for a QD04 control (encoder knob)"""

    def __init__(self, control_num, name=None, desc=None,
                 num_leds=20, button_mode=ButtonMode.MOMENTARY, button_reports=1,
                 min_value=0.0, max_value=100.0, units='',
                 reverse=False, count_mode=CountMode.ABSOLUTE, wrap=False,
                 acceleration=None,
                 default_value=None, default_button=0,
                 dial=None, schemes=None, enabled=True):
        super().__init__(control_num, name, desc, enabled=enabled)
        self.num_leds = num_leds
        self.button_mode = button_mode
        self.button_reports = button_reports
        self.min_value = min_value
        self.max_value = max_value
        self.units = units
        self.reverse = reverse                # A/B wiring reversed
        self.count_mode = count_mode          # ABSOLUTE or INCREMENTAL
        self.wrap = wrap                      # Wrap around at min/max boundaries
        self.acceleration = acceleration      # QD04AccelerationConfig or None
        # Default value (if None, computed as midpoint of min/max)
        if default_value is None:
            self.default_value = (min_value + max_value) / 2.0
        else:
            self.default_value = default_value
        self.default_button = default_button  # Default button state (0=released, 1=pressed)
        self.dial = dial or QD04DialConfig()
        self.schemes = schemes or {}  # scheme_name -> QD04DialConfig
        self.current_scheme = "default"
    
    def to_setconfig_payload(self):
        """Pack into SETCONFIG payload for QD04"""
        # For incremental mode, send a dummy small value to firmware (no LEDs to drive)
        # but keep self.num_leds for Python-side resolution calculation
        fw_num_leds = 10 if self.count_mode == CountMode.INCREMENTAL else self.num_leds

        # Base config: control_num(1) + num_leds(1) + button_mode(1) + button_reports(1)
        payload = struct.pack('<BBBB',
                             self.control_num,
                             fw_num_leds,
                             self.button_mode,
                             self.button_reports)

        # Add dial config (includes mode flags bitset)
        payload += self.dial.to_bytes(fw_num_leds, self.reverse, self.count_mode)

        return payload
    
    def get_state_value(self, state_dict):
        """Get value string for a state (for QD04, map position to real value)"""
        if isinstance(state_dict, dict):
            position = state_dict.get('position', 0)
            button = state_dict.get('button', 0)
        else:
            position = state_dict
            button = 0
        
        # Map position to real value
        value = self.position_to_value(position)
        
        button_str = "pressed" if button else "released"
        
        if self.units:
            return f"{value:.2f} {self.units}, button={button_str}"
        else:
            return f"{value:.2f}, button={button_str}"
    
    def position_to_value(self, position):
        """Convert LED position (0 to num_leds-1) to real value"""
        if self.num_leds > 1:
            normalized = position / (self.num_leds - 1)
        else:
            normalized = 0.0

        return self.min_value + (normalized * (self.max_value - self.min_value))

    def value_to_position(self, value):
        """Convert real value to LED position (0 to num_leds-1)"""
        if self.max_value == self.min_value:
            return 0

        normalized = (value - self.min_value) / (self.max_value - self.min_value)
        normalized = max(0.0, min(1.0, normalized))  # Clamp to 0-1

        return int(round(normalized * (self.num_leds - 1)))

class QD04BoardConfig(BoardConfig):
    """QD04-specific board configuration"""
    
    def get_control_by_name(self, name: str):
        """Get control config by name (for controls with same name, returns first)"""
        for control_num, control in self.controls.items():
            if control.name == name:
                return control
        return None

def parse_dial_config(dial_data, control_num):
    """Parse dial configuration from JSON

    Returns QD04DialConfig instance
    """
    VALID_DIAL_KEYS = {'comment', 'background_mode', 'active_mode', 'start_color', 'end_color', 'zones',
                      'active_render', 'overlay_color', 'animation', 'schemes'}
    VALID_ANIM_KEYS = {'comment', 'mode', 'period_ms', 'duty_cycle_ms'}

    # Validate dial keys
    unknown_keys = set(dial_data.keys()) - VALID_DIAL_KEYS
    if unknown_keys:
        print_warning(f"WARNING: Control {control_num} dial: Unknown keys: {unknown_keys}")

    # Parse background_mode
    bg_mode_str = dial_data.get('background_mode', 'gradient').lower()
    bg_mode_map = {'gradient': BackgroundMode.GRADIENT, 'ranged': BackgroundMode.RANGED}
    if bg_mode_str not in bg_mode_map:
        print_error(f"[enigma] ERROR: Control {control_num} dial: Invalid background_mode '{bg_mode_str}'. "
              f"Valid modes: {list(bg_mode_map.keys())}. Defaulting to 'gradient'")
        bg_mode_str = 'gradient'
    background_mode = bg_mode_map[bg_mode_str]

    # Parse active_mode
    active_mode_str = dial_data.get('active_mode', 'bar').lower()
    active_mode_map = {'bar': ActiveMode.BAR, 'tick': ActiveMode.TICK}
    if active_mode_str not in active_mode_map:
        print_error(f"[enigma] ERROR: Control {control_num} dial: Invalid active_mode '{active_mode_str}'. "
              f"Valid modes: {list(active_mode_map.keys())}. Defaulting to 'bar'")
        active_mode_str = 'bar'
    active_mode = active_mode_map[active_mode_str]

    # Parse colors (mode-specific)
    start_color = dial_data.get('start_color', '#0000FF')
    end_color = dial_data.get('end_color', '#FF0000')
    zones = dial_data.get('zones', [])

    # Validate zones for ranged mode
    if background_mode == BackgroundMode.RANGED:
        if not zones:
            print_warning(f"WARNING: Control {control_num} dial: Ranged mode requires zones")
        for i, zone in enumerate(zones):
            if 'threshold' not in zone or 'color' not in zone:
                print_error(f"[enigma] ERROR: Control {control_num} dial zone {i}: "
                      f"Must have 'threshold' and 'color'")
    
    # Parse active render mode
    render_str = dial_data.get('active_render', 'brighten').lower()
    render_map = {
        'brighten': BlendMode.BRIGHTEN,
        'replace': BlendMode.REPLACE,
        'additive': BlendMode.ADDITIVE,
        'multiply': BlendMode.MULTIPLY,
        'screen': BlendMode.SCREEN,
        'alpha': BlendMode.ALPHA
    }
    if render_str not in render_map:
        print_error(f"[enigma] ERROR: Control {control_num} dial: Invalid active_render '{render_str}'. "
              f"Valid modes: {list(render_map.keys())}. Defaulting to 'brighten'")
        render_str = 'brighten'
    active_render = render_map[render_str]
    
    # Parse overlay color
    overlay_color = dial_data.get('overlay_color', '#FFFFFF')
    
    # Parse animation
    anim_data = dial_data.get('animation', {})
    
    # Validate animation keys
    unknown_anim_keys = set(anim_data.keys()) - VALID_ANIM_KEYS
    if unknown_anim_keys:
        print_warning(f"WARNING: Control {control_num} dial animation: Unknown keys: {unknown_anim_keys}")
    
    anim_mode_str = anim_data.get('mode', 'solid').lower()
    anim_mode_map = {'solid': AnimMode.SOLID, 'blink': AnimMode.BLINK, 'fade': AnimMode.FADE}
    if anim_mode_str not in anim_mode_map:
        print_error(f"[enigma] ERROR: Control {control_num} dial animation: Invalid mode '{anim_mode_str}'. "
              f"Valid modes: {list(anim_mode_map.keys())}. Defaulting to 'solid'")
        anim_mode_str = 'solid'
    anim_mode = anim_mode_map[anim_mode_str]
    
    anim_period = anim_data.get('period_ms', 1000)
    anim_duty = anim_data.get('duty_cycle_ms', 0)
    
    if anim_duty == 0:
        anim_duty = anim_period // 2
    
    if anim_duty > anim_period:
        print_warning(f"WARNING: Control {control_num} dial animation: "
              f"duty_cycle_ms ({anim_duty}) > period_ms ({anim_period})")
    
    return QD04DialConfig(
        background_mode=background_mode,
        active_mode=active_mode,
        zones=zones,
        start_color=start_color,
        end_color=end_color,
        active_render=active_render,
        overlay_color=overlay_color,
        anim_mode=anim_mode,
        anim_period=anim_period,
        anim_duty=anim_duty
    )

class QD04Handler(BoardVariantHandler):
    """Handler for QD04 (4 quadrature encoder knobs)"""

    VARIANT_ID = 4
    TYPE_STR = "QD04"
    NUM_CONTROLS = 4
    SPEED_WINDOW_SIZE = 10       # Number of timestamps to track for speed calculation
    IDLE_TIMEOUT_MS = 500        # Ms of no activity before resetting to fine mode
    MIN_DETENT_GAP_MS = 50       # Min gap between reports to count as separate physical detents

    def __init__(self, device):
        super().__init__(device)
        self.variant_id = self.VARIANT_ID
        self.type_str = self.TYPE_STR
        # Track positions for incremental mode (control_num -> value)
        self._tracked_positions = {}
        # Track report timestamps for speed calculation (control_num -> list of timestamps)
        self._report_timestamps = {}

    def _calculate_speed(self, control_num):
        """Calculate physical detents-per-second based on recent report timestamps

        Collapses reports that arrive within MIN_DETENT_GAP_MS of each other,
        treating them as a single physical detent (handles encoders that send
        multiple reports per physical click).
        """
        import time

        timestamps = self._report_timestamps.get(control_num, [])
        if len(timestamps) < 2:
            return 0.0

        # Check if we've been idle too long - reset to fine mode
        now = time.time()
        if (now - timestamps[-1]) > (self.IDLE_TIMEOUT_MS / 1000.0):
            return 0.0

        # Collapse timestamps into physical detents
        # Reports within MIN_DETENT_GAP_MS of each other are the same detent
        min_gap = self.MIN_DETENT_GAP_MS / 1000.0
        detent_times = [timestamps[0]]
        for ts in timestamps[1:]:
            if (ts - detent_times[-1]) >= min_gap:
                detent_times.append(ts)

        if len(detent_times) < 2:
            return 0.0

        # Calculate average time between physical detents
        total_time = detent_times[-1] - detent_times[0]
        if total_time <= 0:
            return 0.0

        num_intervals = len(detent_times) - 1
        avg_interval = total_time / num_intervals

        # Convert to reports per second
        if avg_interval > 0:
            return 1.0 / avg_interval
        return 0.0

    def _record_report_timestamp(self, control_num):
        """Record a report timestamp for speed tracking"""
        import time

        now = time.time()

        if control_num not in self._report_timestamps:
            self._report_timestamps[control_num] = []

        timestamps = self._report_timestamps[control_num]

        # Check for idle timeout - if so, clear old timestamps
        if timestamps and (now - timestamps[-1]) > (self.IDLE_TIMEOUT_MS / 1000.0):
            timestamps.clear()

        timestamps.append(now)

        # Keep only the most recent timestamps
        if len(timestamps) > self.SPEED_WINDOW_SIZE:
            self._report_timestamps[control_num] = timestamps[-self.SPEED_WINDOW_SIZE:]
    
    def create_blank_config(self, control_num):
        """Create blank QD04 config - unconfigured indicator

        Creates a 10-50% gray gradient with red overlay in screen mode, blinking
        """
        dial = QD04DialConfig(
            background_mode=BackgroundMode.GRADIENT,
            active_mode=ActiveMode.BAR,
            start_color='#202020',  # 10% white
            end_color='#808080',    # 50% white
            active_render=BlendMode.SCREEN,
            overlay_color='#FF800000',  # Alpha=FF, Red
            anim_mode=AnimMode.BLINK,
            anim_period=500,
            anim_duty=0
        )

        return QD04ControlConfig(
            control_num,
            name=f"Unused{control_num}",
            desc="Unconfigured channel",
            num_leds=20,
            button_mode=ButtonMode.MOMENTARY,
            button_reports=1,
            min_value=0.0,
            max_value=100.0,
            units='',
            reverse=False,
            count_mode=CountMode.ABSOLUTE,
            wrap=False,
            acceleration=None,
            default_value=None,  # Will default to midpoint (50.0)
            default_button=0,
            dial=dial
        )
    
    def parse_config(self, config_data):
        """Parse QD04 config JSON"""
        board_config = QD04BoardConfig(config_data)

        controls = config_data.get('controls', [])

        VALID_CONTROL_KEYS = {'comment', 'control_num', 'name', 'desc', 'num_leds', 'button_mode',
                             'button_reports', 'min_value', 'max_value', 'units',
                             'reverse', 'count_mode', 'wrap', 'acceleration',
                             'default_value', 'default_button',
                             'dial', 'schemes', 'enabled'}

        for ctrl_data in controls:
            try:
                # Validate control keys
                unknown_keys = set(ctrl_data.keys()) - VALID_CONTROL_KEYS
                if unknown_keys:
                    print_warning(f"WARNING: Control config: Unknown keys: {unknown_keys}")

                control_num = ctrl_data.get('control_num')
                if not control_num or control_num < 1 or control_num > self.NUM_CONTROLS:
                    print_error(f"[enigma] ERROR: Invalid control_num: {control_num}")
                    continue

                name = ctrl_data.get('name', f'Knob{control_num}')
                desc = ctrl_data.get('desc', '')
                enabled = ctrl_data.get('enabled', True)
                min_value = ctrl_data.get('min_value', 0.0)
                max_value = ctrl_data.get('max_value', 100.0)
                units = ctrl_data.get('units', '')

                # Parse count_mode first (affects num_leds validation)
                count_mode_str = ctrl_data.get('count_mode', 'absolute').lower()
                count_mode_map = {'absolute': CountMode.ABSOLUTE, 'incremental': CountMode.INCREMENTAL}
                if count_mode_str not in count_mode_map:
                    print_error(f"[enigma] ERROR: Control {control_num}: Invalid count_mode '{count_mode_str}'. "
                          f"Valid modes: {list(count_mode_map.keys())}. Defaulting to 'absolute'")
                    count_mode_str = 'absolute'
                count_mode = count_mode_map[count_mode_str]

                # Parse num_leds with validation based on count_mode
                if count_mode == CountMode.INCREMENTAL:
                    # Incremental mode: num_leds sets resolution (steps to traverse full range)
                    # No upper limit - firmware gets a dummy value, Python uses the real value
                    if 'num_leds' in ctrl_data:
                        num_leds = ctrl_data.get('num_leds')
                        if num_leds < 1:
                            print_error(f"[enigma] ERROR: Control {control_num}: num_leds must be >= 1, "
                                  f"got {num_leds}. Defaulting to 255")
                            num_leds = 255
                    else:
                        num_leds = 255  # Default resolution for incremental
                else:
                    # Absolute mode: num_leds is required
                    if 'num_leds' not in ctrl_data:
                        print_error(f"[enigma] ERROR: Control {control_num}: num_leds is required for absolute count_mode. "
                              f"Defaulting to 20")
                        num_leds = 20
                    else:
                        num_leds = ctrl_data.get('num_leds')
                        if num_leds < 1 or num_leds > 255:
                            print_error(f"[enigma] ERROR: Control {control_num}: num_leds must be 1-255, "
                                  f"got {num_leds}. Defaulting to 20")
                            num_leds = 20

                # Parse reverse flag
                reverse = ctrl_data.get('reverse', False)
                if not isinstance(reverse, bool):
                    print_warning(f"WARNING: Control {control_num}: 'reverse' should be true/false, "
                          f"got {reverse}. Defaulting to false")
                    reverse = False

                # Parse wrap flag
                wrap = ctrl_data.get('wrap', False)
                if not isinstance(wrap, bool):
                    print_warning(f"WARNING: Control {control_num}: 'wrap' should be true/false, "
                          f"got {wrap}. Defaulting to false")
                    wrap = False

                # Parse acceleration config (only meaningful for incremental mode)
                acceleration = None
                accel_data = ctrl_data.get('acceleration', None)
                if accel_data:
                    if count_mode != CountMode.INCREMENTAL:
                        print_warning(f"WARNING: Control {control_num}: 'acceleration' is only used in incremental count_mode")
                    else:
                        VALID_ACCEL_KEYS = {'comment', 'max_multiplier', 'ramp_speed', 'dead_zone'}
                        unknown_accel_keys = set(accel_data.keys()) - VALID_ACCEL_KEYS
                        if unknown_accel_keys:
                            print_warning(f"WARNING: Control {control_num} acceleration: Unknown keys: {unknown_accel_keys}")

                        max_multiplier = accel_data.get('max_multiplier', 1.0)
                        ramp_speed = accel_data.get('ramp_speed', 30.0)
                        dead_zone = accel_data.get('dead_zone', 5.0)

                        # Validate values
                        if max_multiplier < 1.0:
                            print_warning(f"WARNING: Control {control_num}: max_multiplier must be >= 1.0, "
                                  f"got {max_multiplier}. Defaulting to 1.0")
                            max_multiplier = 1.0
                        if ramp_speed <= 0:
                            print_warning(f"WARNING: Control {control_num}: ramp_speed must be > 0, "
                                  f"got {ramp_speed}. Defaulting to 30.0")
                            ramp_speed = 30.0
                        if dead_zone < 0:
                            print_warning(f"WARNING: Control {control_num}: dead_zone must be >= 0, "
                                  f"got {dead_zone}. Defaulting to 0")
                            dead_zone = 0
                        if dead_zone >= ramp_speed:
                            print_warning(f"WARNING: Control {control_num}: dead_zone ({dead_zone}) must be < ramp_speed ({ramp_speed}). "
                                  f"Adjusting dead_zone to {ramp_speed * 0.5}")
                            dead_zone = ramp_speed * 0.5

                        acceleration = QD04AccelerationConfig(
                            max_multiplier=max_multiplier,
                            ramp_speed=ramp_speed,
                            dead_zone=dead_zone
                        )

                # Parse button mode
                button_mode_str = ctrl_data.get('button_mode', 'momentary').lower()
                button_mode_map = {'momentary': ButtonMode.MOMENTARY, 'toggle': ButtonMode.TOGGLE}
                if button_mode_str not in button_mode_map:
                    print_warning(f"WARNING: Control {control_num}: Invalid button_mode '{button_mode_str}'. "
                          f"Valid modes: {list(button_mode_map.keys())}. Defaulting to 'momentary'")
                    button_mode_str = 'momentary'
                button_mode = button_mode_map[button_mode_str]

                button_reports = ctrl_data.get('button_reports', 1)

                # Parse default_value (if not specified, will default to midpoint in config)
                default_value = ctrl_data.get('default_value', None)
                if default_value is not None:
                    # Validate it's within range
                    if default_value < min_value or default_value > max_value:
                        print_warning(f"WARNING: Control {control_num}: default_value {default_value} "
                              f"is outside range [{min_value}, {max_value}]. "
                              f"Will be clamped.")
                        default_value = max(min_value, min(max_value, default_value))

                # Parse default_button (0=released, 1=pressed)
                default_button = ctrl_data.get('default_button', 0)
                if default_button not in (0, 1):
                    print_warning(f"WARNING: Control {control_num}: default_button must be 0 or 1, "
                          f"got {default_button}. Defaulting to 0")
                    default_button = 0

                # Parse dial config
                dial_data = ctrl_data.get('dial', {})
                dial = parse_dial_config(dial_data, control_num)

                # Parse schemes
                schemes = {}
                schemes_data = ctrl_data.get('schemes', {})
                for scheme_name, scheme_dial_data in schemes_data.items():
                    schemes[scheme_name] = parse_dial_config(scheme_dial_data, control_num)

                control = QD04ControlConfig(
                    control_num, name, desc,
                    num_leds, button_mode, button_reports,
                    min_value, max_value, units,
                    reverse, count_mode, wrap,
                    acceleration,
                    default_value, default_button,
                    dial, schemes, enabled=enabled
                )

                board_config.controls[control_num] = control

            except Exception as e:
                print_error(f"[enigma] Error parsing control {ctrl_data.get('control_num')}: {e}")
                import traceback
                traceback.print_exc()

#        print(f"Loaded config '{board_config.name}' with {len(board_config.controls)} controls")
        return board_config
    
    # Low-level pack/parse (internal use)
    
    def _pack_state(self, control_state):
        """Pack QD04ControlState into bytes"""
        if not isinstance(control_state, QD04ControlState):
            raise TypeError(f"Expected QD04ControlState, got {type(control_state).__name__}")
        
        if control_state.position < 0:
            raise ValueError(f"QD04 position must be >= 0, got {control_state.position}")
        
        if control_state.button not in (0, 1):
            raise ValueError(f"QD04 button must be 0 or 1, got {control_state.button}")
        
        return struct.pack('<BB', control_state.position, control_state.button)
    
    def _parse_state(self, state_data, control_num=None):
        """Parse bytes into QD04ControlState

        For absolute mode: byte 0 is position (0 to num_leds)
        For incremental mode: byte 0 is signed delta (-128 to +127)
        """
        if len(state_data) < 2:
            return QD04ControlState(position=0, button=0)

        raw_value = state_data[0]
        button = state_data[1]

        # Get current scheme from device
        scheme = self.device.active_scheme if hasattr(self.device, 'active_scheme') else "default"

        # Check if this control is in incremental mode
        control_config = None
        if control_num and self.config:
            control_config = self.config.controls.get(control_num)

        if control_config and control_config.count_mode == CountMode.INCREMENTAL:
            # INCREMENTAL MODE: raw_value is signed delta
            # Convert uint8 to signed int8
            delta = raw_value if raw_value < 128 else raw_value - 256


            # Only process if there's actual movement
            if delta != 0:
                # Record timestamp for speed tracking
                self._record_report_timestamp(control_num)

            # Get current tracked value (default to min_value for centered start, or 0)
            current_value = self._tracked_positions.get(control_num, control_config.min_value)

            # Calculate base value increment based on num_leds (resolution)
            value_range = control_config.max_value - control_config.min_value
            base_increment = value_range / control_config.num_leds  # num_leds defaults to 255 for incremental

            # Apply acceleration if configured
            if delta != 0 and control_config.acceleration:
                speed = self._calculate_speed(control_num)
                multiplier = control_config.acceleration.calculate_multiplier(speed)
                increment = base_increment * multiplier
            else:
                increment = base_increment

            # Apply delta
            new_value = current_value + (delta * increment)

            # Apply wrap or clamp
            if control_config.wrap:
                # Wrap around (handle multiple wraps for fast movement)
                while new_value > control_config.max_value:
                    new_value -= value_range
                while new_value < control_config.min_value:
                    new_value += value_range
            else:
                # Clamp to range
                new_value = max(control_config.min_value, min(control_config.max_value, new_value))

            # Store updated value
            self._tracked_positions[control_num] = new_value

            # Consume the delta by zeroing it in cached state
            # This prevents re-applying the delta on subsequent reads
            if delta != 0 and hasattr(self, 'device') and self.device:
                self.device.current_states[control_num] = bytes([0, button])

            # Convert value back to position for the state object (for consistency)
            # Position represents where in the range we are (0 to num_leds)
            if value_range > 0:
                normalized = (new_value - control_config.min_value) / value_range
                position = int(normalized * control_config.num_leds)
            else:
                position = 0

            return QD04ControlState(position=position, button=button, value=new_value, scheme=scheme)

        else:
            # ABSOLUTE MODE: raw_value is position (0 to num_leds)
            position = raw_value

            # Apply wrap or clamp if config available
            if control_config:
                if control_config.wrap:
                    # Wrap position
                    while position > control_config.num_leds:
                        position -= control_config.num_leds
                    while position < 0:
                        position += control_config.num_leds
                else:
                    # Clamp position (shouldn't be needed, firmware already clamps)
                    position = max(0, min(control_config.num_leds, position))

                # Calculate value from position
                value = control_config.position_to_value(position)

                # Track position for consistency
                self._tracked_positions[control_num] = value
            else:
                value = None

            return QD04ControlState(position=position, button=button, value=value, scheme=scheme)
    
    def get_control_count(self):
        return self.NUM_CONTROLS
    
    def set_control_by_value(self, control_num, value):
        """Set QD04 control by value

        Args:
            control_num: Control number
            value: QD04ControlState object, int (position), float (mapped from min/max),
                   or dict with 'position' and 'button'

        Returns:
            True if successful, False otherwise
        """
        # Get control config for mapping
        control = self.config.controls.get(control_num)
        if not control:
            return False

        # Incremental controls have no absolute hardware position - the firmware
        # only reports +/- delta ticks; the accumulated value lives entirely in
        # _tracked_positions. So a "set value" is library-side state only: write
        # the accumulator and zero the cached delta byte so the next _parse_state
        # doesn't re-apply stale motion on top. No firmware roundtrip - the
        # position-as-ubyte packing in _pack_state can't represent the mapped
        # position for high-num_leds incrementals anyway.
        if control.count_mode == CountMode.INCREMENTAL and isinstance(value, (int, float)):
            v = float(value)
            value_range = control.max_value - control.min_value
            if value_range > 0:
                if control.wrap:
                    while v > control.max_value:
                        v -= value_range
                    while v < control.min_value:
                        v += value_range
                else:
                    v = max(control.min_value, min(control.max_value, v))
            self._tracked_positions[control_num] = v
            if self.device is not None:
                cur = self.device.current_states.get(control_num)
                button = cur[1] if cur and len(cur) >= 2 else 0
                self.device.current_states[control_num] = bytes([0, button])
            return True

        # If already a ControlState, use directly
        if isinstance(value, QD04ControlState):
            self.set_control_state(control_num, value)
            return True

        # If float, map from min/max range to LED position
        if isinstance(value, float):
            # Map value from [min_value, max_value] to [0, num_leds-1]
            value_range = control.max_value - control.min_value
            if value_range == 0:
                position = 0
            else:
                normalized = (value - control.min_value) / value_range
                position = round(normalized * (control.num_leds - 1))
                # Clamp to valid range
                if position < 0 or position >= control.num_leds:
                    clamped_pos = max(0, min(control.num_leds - 1, position))
                    # Calculate what value this position represents
                    clamped_value = control.min_value + (clamped_pos / (control.num_leds - 1)) * value_range
                    print_warning(f"WARNING: Control {control_num} ({control.name}): Value {value} "
                          f"out of range [{control.min_value}, {control.max_value}], "
                          f"clamped to {clamped_value:.1f}")
                    position = clamped_pos
            
            # Preserve current button state
            current_state = self._cached_states.get(control_num)
            current_button = 0
            if current_state:
                parsed = self._parse_state(current_state, control_num)
                current_button = parsed.button
            self.set_control_state(control_num, QD04ControlState(position=position, button=current_button))
            return True

        # If int, treat as position, preserve button state
        if isinstance(value, int):
            if 0 <= value < control.num_leds:
                current_state = self._cached_states.get(control_num)
                current_button = 0
                if current_state:
                    parsed = self._parse_state(current_state, control_num)
                    current_button = parsed.button
                self.set_control_state(control_num, QD04ControlState(position=value, button=current_button))
                return True
            return False
        
        # If dict, extract position and button
        if isinstance(value, dict):
            position = value.get('position', 0)
            button = value.get('button', 0)
            if 0 <= position < control.num_leds and button in (0, 1):
                self.set_control_state(control_num, QD04ControlState(position=position, button=button))
                return True
        
        return False
    
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
            target_controls = list(self.config.controls.values())
        else:
            target_controls = [c for c in self.config.controls.values() 
                             if c.name == control_name]
        
        if not target_controls:
            print(f"[enigma] No controls found matching name '{control_name}'")
            return 0
        
        # Update each control
        for control in target_controls:
            # Check if this control has the requested scheme
            if scheme_name != "default" and scheme_name not in control.schemes:
                continue
            
            # Check if already at this scheme
            if control.current_scheme == scheme_name:
                continue
            
            # Get the dial config for this scheme
            if scheme_name == "default":
                dial_config = control.dial
            else:
                dial_config = control.schemes.get(scheme_name)
                if not dial_config:
                    continue
            
            # Pack indicator data
            indicator_data = dial_config.to_bytes(control.num_leds)
            
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
    
    def reset(self, full_reset=False, send_to_hardware=True):
        """Reset handler state - sets controls to default values and schemes

        Args:
            full_reset: If True, clears all cached values (nuclear reset).
                       If False, preserves non-default values for sync.
            send_to_hardware: If True, send SETSTATE commands. If False, just update tracking.
        """
        self._reset_to_defaults(full_reset=full_reset, send_to_hardware=send_to_hardware)
        super().reset(full_reset=full_reset)

    def _reset_to_defaults(self, full_reset=False, send_to_hardware=True):
        """Reset all controls to their default values

        Args:
            full_reset: If True, clears all cached values (nuclear reset).
                       If False, preserves non-default values for sync.
            send_to_hardware: If True, send SETSTATE commands. If False, just update tracking.
        """
        if not self.config:
            return

        for control in self.config.controls.values():
            control_num = control.control_num
            default_value = control.default_value
            default_button = control.default_button

            if not full_reset:
                # Check if we have a tracked position that differs from default
                tracked = self._tracked_positions.get(control_num)
                if tracked is not None and tracked != default_value:
                    # Preserve non-default value - sync_state_to_device() will restore it
                    continue

            # Calculate LED position from default_value
            if control.count_mode == CountMode.INCREMENTAL:
                # Incremental mode: position doesn't matter to firmware, send 0
                position = 0
            else:
                # Absolute mode: convert value to LED position
                position = control.value_to_position(default_value)

            # Pack state bytes
            state_data = struct.pack('<BB', position, default_button)

            if send_to_hardware:
                # Clear cache so SETSTATE actually sends
                if control_num in self._cached_states:
                    del self._cached_states[control_num]

                # Send to hardware
                try:
                    self.device.set_state(control_num, state_data)
                except Exception as e:
                    print_error(f"[enigma] [QD04] Failed to set default state for control {control_num}: {e}")

            # Update Python-side tracking and cache
            self._tracked_positions[control_num] = default_value
            self.device.current_states[control_num] = state_data
            self._cached_states[control_num] = state_data

    def sync_state_to_device(self):
        """Sync cached state and scheme values to device on (re)connect.

        Sends SETSTATE for any controls where our tracked position differs from
        the default, and restores non-default schemes. This restores programmatically-set
        values after device reconnection (e.g., after sleep/wake or device reboot).
        """
        if not self.config:
            return

        synced_states = 0
        synced_schemes = 0

        for control in self.config.controls.values():
            control_num = control.control_num
            default_value = control.default_value
            default_button = control.default_button

            # Sync state if different from default
            tracked = self._tracked_positions.get(control_num)
            if tracked is not None and tracked != default_value:
                # Calculate LED position from tracked value
                if control.count_mode == CountMode.INCREMENTAL:
                    position = 0
                else:
                    position = control.value_to_position(tracked)

                state_data = struct.pack('<BB', position, default_button)

                # Clear cache so SETSTATE actually sends
                if control_num in self._cached_states:
                    del self._cached_states[control_num]

                try:
                    self.device.set_state(control_num, state_data)
                    self._cached_states[control_num] = state_data
                    self.device.current_states[control_num] = state_data
                    synced_states += 1
                except Exception as e:
                    print_error(f"[enigma] ERROR: Failed to sync control {control_num}: {e}")

            # Sync scheme if not default
            if hasattr(control, 'current_scheme') and control.current_scheme != "default":
                scheme_name = control.current_scheme
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
register_board_variant(QD04Handler.VARIANT_ID, QD04Handler.TYPE_STR, QD04Handler)
