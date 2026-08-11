# SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
# SPDX-License-Identifier: MIT

"""
Logitech G Pro Keyboard RGB Control
Communicates with gpro_daemon via Unix socket
"""

import socket
import json
import time
import threading
import random
from typing import List, Tuple, Dict, Optional

from .base import BoardVariantHandler, BoardConfig
from enigma.colors import print_error, print_warning

# Socket path for daemon connection
DAEMON_SOCKET_PATH = "/tmp/gpro_daemon.sock"

# USB HID scan codes for keys we care about
KEYS = {
    # Letters
    'A': 0x04, 'B': 0x05, 'C': 0x06, 'D': 0x07, 'E': 0x08, 'F': 0x09,
    'G': 0x0a, 'H': 0x0b, 'I': 0x0c, 'J': 0x0d, 'K': 0x0e, 'L': 0x0f,
    'M': 0x10, 'N': 0x11, 'O': 0x12, 'P': 0x13, 'Q': 0x14, 'R': 0x15,
    'S': 0x16, 'T': 0x17, 'U': 0x18, 'V': 0x19, 'W': 0x1a, 'X': 0x1b,
    'Y': 0x1c, 'Z': 0x1d,

    # Numbers
    '0': 0x27, '1': 0x1e, '2': 0x1f, '3': 0x20, '4': 0x21,
    '5': 0x22, '6': 0x23, '7': 0x24, '8': 0x25, '9': 0x26,

    # Special keys
    'SPACE': 0x2c,
    'BACKSPACE': 0x2a,
    'ENTER': 0x28,
    'ESC': 0x29,
    '-': 0x2d,  # Minus/underscore key
    '=': 0x2e,  # Equal/plus key

    # Punctuation keys
    '`': 0x35,  # Grave accent/backtick
    '[': 0x2f,  # Left bracket
    ']': 0x30,  # Right bracket
    '\\': 0x31, # Backslash
    ';': 0x33,  # Semicolon
    "'": 0x34,  # Apostrophe
    ',': 0x36,  # Comma
    '.': 0x37,  # Period
    '/': 0x38,  # Forward slash

    # Arrow keys
    'UP': 0x52,
    'DOWN': 0x51,
    'LEFT': 0x50,
    'RIGHT': 0x4f,

    # Modifier keys (for LED control)
    'LSHIFT': 0xe1,  # Left Shift
    'RSHIFT': 0xe5,  # Right Shift
}

# Shift key mappings (base char -> shifted char)
SHIFT_MAP = {
    '`': '~',
    '[': '{',
    ']': '}',
    '\\': '|',
    ';': ':',
    "'": '"',
    ',': '<',
    '.': '>',
    '/': '?',
    '-': '_',
    '=': '+',
    '1': '!',
    '2': '@',
    '3': '#',
    '4': '$',
    '5': '%',
    '6': '^',
    '7': '&',
    '8': '*',
    '9': '(',
    '0': ')',
}

# Hardcoded key groups
KEY_GROUPS = {
    'meta': ['ENTER', 'BACKSPACE', 'SPACE', 'ESC', 'UP', 'DOWN', 'LEFT', 'RIGHT', 'LSHIFT', 'RSHIFT'],
    'alpha': list('ABCDEFGHIJKLMNOPQRSTUVWXYZ'),
    'numeric': list('0123456789') + ['-', '='],
    'punctuation': ['`', '[', ']', '\\', ';', "'", ',', '.', '/'],
}

# Blanking modes
BLANKING_OFF = 0
BLANKING_ON = 1
BLANKING_DISRUPTION = 2

# Pulse fade duration
PULSE_FADE_MS = 500


class GProDaemonClient:
    """Client for gpro_daemon socket connection"""

    def __init__(self, socket_path=DAEMON_SOCKET_PATH):
        self.socket_path = socket_path
        self.sock = None
        self._lock = threading.Lock()

    def connect(self):
        """Connect to daemon socket"""
        try:
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.connect(self.socket_path)
            # Give keyboard a moment after connection before sending commands
            time.sleep(0.1)
            return True
        except Exception as e:
            print_error(f"[enigma] Failed to connect to gpro_daemon: {e}")
            print(f"[enigma] Run 'enigma/tools/gpro-daemon-start.sh' to start the daemon")
            return False

    def disconnect(self):
        """Disconnect from daemon"""
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
            self.sock = None

    def send_raw(self, data: bytes, size: int = 64):
        """Send raw HID packet to device (thread-safe, fire-and-forget)

        Args:
            data: Command bytes
            size: Packet size to send to HID device (20 or 64 bytes)
        """
        with self._lock:
            if not self.sock:
                if not self.connect():
                    return False

            try:
                # Protocol: [1 byte size][size bytes padded data]
                # Pad to the actual HID packet size (20 or 64)
                padded = data + bytes(size - len(data))
                packet = bytes([size]) + padded
                self.sock.send(packet)
                # Fire and forget - no response needed for LED commands
                return True
            except Exception as e:
                print_error(f"[enigma] Socket send error: {e}")
                self.disconnect()
                return False


class GProHandler(BoardVariantHandler):
    """Handler for G Pro Keyboard (connects via daemon)"""

    VARIANT_ID = 0  # Not a real variant, just for compatibility
    TYPE_STR = "GPRO"

    def __init__(self, device=None):
        # Note: device will be None for GPRO since we don't use USB HID
        super().__init__(device)
        self.variant_id = self.VARIANT_ID
        self.type_str = self.TYPE_STR

        self.daemon = GProDaemonClient()

        # State
        self.brightness = 255  # 0-255
        self.blanking_mode = BLANKING_OFF
        self.disruption_start = None
        self.disruption_duration_ms = 0
        self.pulse_active = False
        self.pulse_start = None

        # Current colors (for restoration after pulse/blanking)
        self.current_colors = {}  # key_id -> (r, g, b)
        self.current_scheme = "default"

        # Schemes loaded from config
        self.schemes = {}
        self.default_scheme = {}

        # Disruption update thread
        self._disruption_thread = None
        self._disruption_stop = threading.Event()

        # Keyboard text input state
        self._text_buffer = ""
        self._cursor_position = 0
        self._input_active = False
        self._capture_arrows = True   # When False, arrow keys skip buffer-cursor logic - app reads them via last_key()
        self._submit_flag = False
        self._cancel_flag = False
        self._submit_flag_next = False
        self._cancel_flag_next = False
        self._last_key = None
        self._last_key_next = None

        # Keystroke receive thread
        self._keystroke_thread = None
        self._keystroke_stop = threading.Event()
        self._last_scancodes = set()  # Track held keys for chord detection
        self._input_filter = None  # Character filter (frozenset or None for all)

    def parse_config(self, config_data):
        """Parse keyboard config JSON and return BoardConfig"""
        # BoardConfig expects the full config_data dict
        board_config = BoardConfig(config_data)

        # Extract schemes
        self.default_scheme = {
            'background': config_data.get('background', '#000000'),
            'meta': config_data.get('meta'),
            'alpha': config_data.get('alpha'),
            'numeric': config_data.get('numeric'),
            'punctuation': config_data.get('punctuation'),
            'custom': config_data.get('custom'),
        }

        # Load named schemes
        if 'schemes' in config_data:
            self.schemes = config_data['schemes']

        # Store config
        self.config = board_config
        return board_config

    def load_config(self, config_file: str):
        """Load configuration from JSON file"""
        try:
            with open(config_file, 'r') as f:
                self.config = json.load(f)

            # Extract default scheme (top-level colors)
            self.default_scheme = {
                'background': self.config.get('background', '#000000'),
                'meta': self.config.get('meta'),
                'alpha': self.config.get('alpha'),
                'numeric': self.config.get('numeric'),
                'punctuation': self.config.get('punctuation'),
                'custom': self.config.get('custom'),
            }

            # Extract named schemes
            self.schemes = self.config.get('schemes', {})

            print(f"[enigma] Loaded G Pro config: {len(self.schemes)} schemes")
            return True
        except Exception as e:
            print_error(f"[enigma] Error loading config {config_file}: {e}")
            return False

    # =========================================================================
    # Low-level RGB Protocol (from gpro_test.py)
    # =========================================================================

    def _send_keys_packet(self, keys: List[Tuple[int, int, int, int]]):
        """Send up to 14 key colors (64-byte packet)"""
        data = bytes([0x12, 0xff, 0x0c, 0x3a, 0x00, 0x01, 0x00, 0x0e])
        for key_id, r, g, b in keys[:14]:
            data += bytes([key_id, r, g, b])
        self.daemon.send_raw(data, size=64)
        time.sleep(0.005)  # 5ms delay to avoid overwhelming keyboard

    def _commit(self):
        """Commit key data (20-byte packet)"""
        data = bytes([0x11, 0xff, 0x0c, 0x3a, 0x00, 0x01, 0x00, 0x0e])
        self.daemon.send_raw(data, size=20)
        time.sleep(0.010)  # 10ms delay before finalize

    def _finalize(self):
        """Apply changes (20-byte packet)"""
        data = bytes([0x11, 0xff, 0x0c, 0x5a])
        self.daemon.send_raw(data, size=20)

    # =========================================================================
    # Color Management
    # =========================================================================

    def _scale_brightness(self, r: int, g: int, b: int) -> Tuple[int, int, int]:
        """Apply global brightness scaling"""
        return (
            (r * self.brightness) // 255,
            (g * self.brightness) // 255,
            (b * self.brightness) // 255
        )

    def _hex_to_rgb(self, hex_color: str) -> Tuple[int, int, int]:
        """Convert '#RRGGBB' to (r, g, b)"""
        hex_color = hex_color.lstrip('#')
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

    def _parse_custom_keys(self, key_str: str) -> List[str]:
        """Parse custom key string into list of key names

        Supports:
        - Single chars: 'ABC123+-'
        - Escape sequences from JSON: ' ' (space), '\\b' (backspace), '\\n' or '\\r' (enter), '\\x1b' (ESC)
        - Brace notation: {SPACE}, {ENTER}, {BACKSPACE}, {ESC}, {UP}, {DOWN}, {LEFT}, {RIGHT}
        - {SHIFT} expands to both {LSHIFT} and {RSHIFT}
        """
        keys = []
        i = 0
        while i < len(key_str):
            # Check for brace notation
            if key_str[i] == '{':
                # Find closing brace
                close_idx = key_str.find('}', i)
                if close_idx != -1:
                    key_name = key_str[i+1:close_idx].upper()
                    # Special case: {SHIFT} expands to both shift keys
                    if key_name == 'SHIFT':
                        keys.append('LSHIFT')
                        keys.append('RSHIFT')
                    # Validate it's a known key
                    elif key_name in KEYS:
                        keys.append(key_name)
                    i = close_idx + 1
                    continue

            # Single character handling
            char = key_str[i]
            if char == ' ':
                keys.append('SPACE')
            elif char == '\b':  # Backspace escape from JSON
                keys.append('BACKSPACE')
            elif char in ('\n', '\r'):  # Enter escape from JSON
                keys.append('ENTER')
            elif char == '\x1b':  # ESC escape from JSON
                keys.append('ESC')
            elif char in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-=`[]\\;',./":
                keys.append(char)
            elif char in SHIFT_MAP.values():
                # Shifted character - find the base key
                for base, shifted in SHIFT_MAP.items():
                    if shifted == char:
                        keys.append(base)
                        break
            # Ignore other characters

            i += 1
        return keys

    # =========================================================================
    # Scheme Rendering
    # =========================================================================

    def set_scheme(self, scheme_name: str):
        """Apply a color scheme"""
        # Skip if already active (avoid USB spam)
        if scheme_name == self.current_scheme:
            return

        # Get scheme definition
        if scheme_name == "default":
            scheme = self.default_scheme
        elif scheme_name in self.schemes:
            scheme = self.schemes[scheme_name]
        else:
            print(f"[enigma] Unknown scheme: {scheme_name}")
            return

        key_colors = {}  # key_id -> (r, g, b)

        # 1. Background (all keys)
        bg_hex = scheme.get('background', '#000000')
        bg_rgb = self._hex_to_rgb(bg_hex)
        for key_id in KEYS.values():
            key_colors[key_id] = bg_rgb

        # 2. Named groups (meta, alpha, numeric, punctuation) - if present
        for group_name in ['meta', 'alpha', 'numeric', 'punctuation']:
            if scheme.get(group_name):
                color_hex = scheme[group_name]
                color_rgb = self._hex_to_rgb(color_hex)
                key_names = KEY_GROUPS.get(group_name, [])
                for key_name in key_names:
                    if key_name in KEYS:
                        key_colors[KEYS[key_name]] = color_rgb

        # 3. Custom (highest priority) - if present. Accepts either a single
        # {keys, color} object or a list of them; later entries override earlier
        # ones if they target the same key.
        custom_block = scheme.get('custom')
        if custom_block:
            custom_list = custom_block if isinstance(custom_block, list) else [custom_block]
            for custom in custom_list:
                color_hex = custom.get('color', '#FFFFFF')
                color_rgb = self._hex_to_rgb(color_hex)
                key_str = custom.get('keys', '')
                key_names = self._parse_custom_keys(key_str)
                for key_name in key_names:
                    if key_name in KEYS:
                        key_colors[KEYS[key_name]] = color_rgb

        # Store current colors (before brightness scaling)
        self.current_colors = key_colors.copy()
        self.current_scheme = scheme_name

        # Send to keyboard (with brightness and blanking applied)
        self._render_colors()

    def _render_colors(self):
        """Render current_colors to keyboard with brightness/blanking applied"""
        if self.blanking_mode == BLANKING_ON:
            # Full blank - all keys black
            keys_to_send = [(kid, 0, 0, 0) for kid in KEYS.values()]
        else:
            # Apply brightness scaling
            keys_to_send = []
            for key_id, (r, g, b) in self.current_colors.items():
                sr, sg, sb = self._scale_brightness(r, g, b)
                keys_to_send.append((key_id, sr, sg, sb))

        # Send in batches of 14
        for i in range(0, len(keys_to_send), 14):
            batch = keys_to_send[i:i+14]
            self._send_keys_packet(batch)

        self._commit()
        self._finalize()

    # =========================================================================
    # Standard Board Features
    # =========================================================================

    def reset(self, full_reset=False, send_to_hardware=True):
        """Reset brightness/blanking/pulse state and re-apply the current scheme.

        Args:
            full_reset: If True, reset scheme to "default" before re-applying.
                       If False, preserve and re-apply the current scheme.
            send_to_hardware: When True (default), force the current scheme to
                              be sent to the keyboard, busting set_scheme's
                              same-scheme early-exit so the LEDs reflect the
                              configured state (e.g. all-black default at boot).
        """
        self.brightness = 255
        self.blanking_mode = BLANKING_OFF
        self.pulse_active = False
        self.disruption_start = None
        self._stop_disruption_thread()

        if full_reset:
            self.current_scheme = "default"

        if send_to_hardware:
            scheme = self.current_scheme
            self.current_scheme = "__resync__"   # bust set_scheme's cache check
            self.set_scheme(scheme)

    def sync_state_to_device(self):
        """Sync cached scheme to device on (re)connect.

        Restores non-default scheme after device reconnection.
        """
        if self.current_scheme != "default":
            scheme_to_restore = self.current_scheme
            # Temporarily set to something else so set_scheme will re-apply
            self.current_scheme = "__resync__"
            self.set_scheme(scheme_to_restore)
            print(f"[enigma]   Synced scheme '{scheme_to_restore}' to G Pro keyboard")

    def set_brightness(self, level: int):
        """Set global brightness (0-255)"""
        self.brightness = max(0, min(255, level))
        # Re-render with new brightness
        if not self.pulse_active:  # Don't interrupt pulse
            self._render_colors()

    def set_blanking(self, mode: int, param: int = 0):
        """Set blanking mode

        Args:
            mode: BLANKING_OFF (0), BLANKING_ON (1), or BLANKING_DISRUPTION (2)
            param: For disruption mode, duration in tenths of seconds
        """
        self.blanking_mode = mode

        if mode == BLANKING_DISRUPTION:
            self.disruption_start = time.time()
            self.disruption_duration_ms = param * 100  # Tenths to ms
            self._start_disruption_thread()
        elif mode == BLANKING_OFF:
            self._stop_disruption_thread()
            self._render_colors()
        elif mode == BLANKING_ON:
            self._stop_disruption_thread()
            self._render_colors()

    def pulse(self):
        """Flash white and fade back over 500ms"""
        # Immediately flash all keys to FULL white (ignoring brightness, like firmware)
        keys_to_send = [(key_id, 255, 255, 255) for key_id in KEYS.values()]
        for i in range(0, len(keys_to_send), 14):
            batch = keys_to_send[i:i+14]
            self._send_keys_packet(batch)
        self._commit()
        self._finalize()

        # Now start fade back to original colors
        self.pulse_active = True
        self.pulse_start = time.time()
        threading.Thread(target=self._pulse_animation, daemon=True).start()

    def _pulse_animation(self):
        """Pulse animation thread"""
        # Store brightness-scaled target colors (where we're fading TO)
        target_colors = {}
        for key_id, (r, g, b) in self.current_colors.items():
            target_colors[key_id] = self._scale_brightness(r, g, b)

        while self.pulse_active:
            frame_start = time.time()
            elapsed_ms = (frame_start - self.pulse_start) * 1000

            if elapsed_ms >= PULSE_FADE_MS:
                # Fade complete - restore original colors
                self.pulse_active = False
                self._render_colors()
                break

            # Calculate fade progress (0.0 -> 1.0)
            fade_progress = elapsed_ms / PULSE_FADE_MS

            # Blend from FULL white (255,255,255) toward brightness-scaled target colors
            keys_to_send = []
            for key_id, (tr, tg, tb) in target_colors.items():
                # Start at full white, fade toward target
                # led = 255 - (255 - target) * fade_progress
                pr = 255 - int((255 - tr) * fade_progress)
                pg = 255 - int((255 - tg) * fade_progress)
                pb = 255 - int((255 - tb) * fade_progress)
                keys_to_send.append((key_id, pr, pg, pb))

            # Send to keyboard
            for i in range(0, len(keys_to_send), 14):
                batch = keys_to_send[i:i+14]
                self._send_keys_packet(batch)
            self._commit()
            self._finalize()

            time.sleep(0.016)  # ~60fps

    # =========================================================================
    # Disruption Mode
    # =========================================================================

    def _start_disruption_thread(self):
        """Start disruption update thread"""
        self._stop_disruption_thread()
        self._disruption_stop.clear()
        self._disruption_thread = threading.Thread(target=self._disruption_update, daemon=True)
        self._disruption_thread.start()

    def _stop_disruption_thread(self):
        """Stop disruption update thread"""
        if self._disruption_thread:
            self._disruption_stop.set()
            self._disruption_thread.join(timeout=0.5)
            self._disruption_thread = None

    def _disruption_update(self):
        """Disruption update thread - renders probabilistic blanking"""
        frame_count = 0

        while not self._disruption_stop.is_set():
            elapsed_ms = (time.time() - self.disruption_start) * 1000

            # Check if disruption period is over
            if elapsed_ms >= self.disruption_duration_ms:
                self.blanking_mode = BLANKING_ON
                self._render_colors()
                break

            # Calculate probability of blanking (0% -> 100%)
            progress = elapsed_ms / self.disruption_duration_ms
            blank_threshold = int(progress * 255)

            # Apply probabilistic blanking to each key
            keys_to_send = []
            for key_id, (r, g, b) in self.current_colors.items():
                # Generate pseudo-random value for this key at this frame
                # (matching LEDManager.cpp algorithm)
                hash_val = (key_id * 6997 + frame_count * 5003)
                hash_val = (hash_val ^ (hash_val >> 16)) * 0x85ebca6b
                hash_val = (hash_val ^ (hash_val >> 13)) * 0xc2b2ae35
                hash_val = hash_val ^ (hash_val >> 16)
                random_val = hash_val & 0xFF

                if random_val < blank_threshold:
                    # Blank this key
                    keys_to_send.append((key_id, 0, 0, 0))
                else:
                    # Normal color with brightness
                    sr, sg, sb = self._scale_brightness(r, g, b)
                    keys_to_send.append((key_id, sr, sg, sb))

            # Send to keyboard
            for i in range(0, len(keys_to_send), 14):
                batch = keys_to_send[i:i+14]
                self._send_keys_packet(batch)
            self._commit()
            self._finalize()

            frame_count += 1
            time.sleep(0.016)  # ~60fps

    # =========================================================================
    # Utility
    # =========================================================================

    def close(self):
        """Close connection to daemon"""
        self._stop_disruption_thread()
        self._stop_keystroke_thread()
        self.daemon.disconnect()

    def _start_keystroke_thread(self):
        """Start keystroke receive thread"""
        if self._keystroke_thread is None or not self._keystroke_thread.is_alive():
            self._keystroke_stop.clear()
            self._keystroke_thread = threading.Thread(target=self._keystroke_loop, daemon=True)
            self._keystroke_thread.start()

    def _stop_keystroke_thread(self):
        """Stop keystroke receive thread"""
        if self._keystroke_thread and self._keystroke_thread.is_alive():
            self._keystroke_stop.set()
            self._keystroke_thread.join(timeout=1.0)

    def _keystroke_loop(self):
        """Thread loop to receive keystrokes from daemon"""
        while not self._keystroke_stop.is_set():
            try:
                # Read data from socket with timeout
                self.daemon.sock.settimeout(0.1)
                data = self.daemon.sock.recv(65)

                if not data:
                    # Connection closed
                    print("[enigma] [Keyboard] Daemon connection closed")
                    break

                # Check for keyboard event marker (0xFF)
                if len(data) > 0 and data[0] == 0xFF:
                    # This is a keyboard event
                    hid_report = data[1:9]  # 8 bytes of HID report
                    self._process_hid_report(hid_report)

            except socket.timeout:
                continue
            except Exception as e:
                if not self._keystroke_stop.is_set():
                    print_error(f"[enigma] [Keyboard] Error receiving keystrokes: {e}")
                break

    def _process_hid_report(self, report: bytes):
        """Process USB HID keyboard report

        The daemon sends us reports when key state changes (including releases).
        Each report is a snapshot of ALL currently pressed keys. We track state
        to detect newly pressed keys (positive edge).
        """
        if len(report) < 8:
            return

        # Parse HID report
        # Byte 0: modifiers (bit 1 = L-Shift, bit 5 = R-Shift)
        # Byte 1: reserved
        # Bytes 2-7: up to 6 pressed key scancodes

        # Check if shift is held (left shift = 0x02, right shift = 0x20)
        shift_held = (report[0] & 0x22) != 0

        # Build set of currently pressed scancodes from this report
        current_scancodes = set()
        for i in range(2, 8):
            scancode = report[i]
            if scancode != 0:
                current_scancodes.add(scancode)

        # Find newly pressed keys (keys in current but not in previous)
        newly_pressed = current_scancodes - self._last_scancodes

        # Update our state to match current report
        # This tracks both presses and releases
        self._last_scancodes = current_scancodes

        # Process only newly pressed keys
        for scancode in newly_pressed:
            self._handle_key_press(scancode, shift_held)

    def _handle_key_press(self, scancode: int, shift_held: bool = False):
        """Handle a key press event"""
        # Convert scancode to key name
        key_name = None
        for name, code in KEYS.items():
            if code == scancode:
                key_name = name
                break

        if not key_name:
            return

        # Apply shift mapping if shift is held
        if shift_held and key_name in SHIFT_MAP:
            key_name = SHIFT_MAP[key_name]

        # Store last key pressed (for next cycle)
        self._last_key_next = key_name

        # Only process if input is active
        if not self._input_active:
            return

        # Handle special keys
        if key_name == 'ENTER':
            self._submit_flag_next = True
            self.keyboard_end_input()
            return
        elif key_name == 'ESC':
            self._cancel_flag_next = True
            self.keyboard_end_input()
            return
        elif key_name == 'BACKSPACE':
            if self._cursor_position > 0:
                self._text_buffer = (
                    self._text_buffer[:self._cursor_position-1] +
                    self._text_buffer[self._cursor_position:]
                )
                self._cursor_position -= 1
            return
        elif key_name in ('LEFT', 'RIGHT', 'UP', 'DOWN'):
            # When capture_arrows is False, arrows are reserved for the app - they're
            # already recorded in _last_key_next above for the app to consume; skip
            # the buffer-cursor logic so they don't compete with highlight navigation.
            if not self._capture_arrows:
                return
            if key_name == 'LEFT':
                if self._cursor_position > 0:
                    self._cursor_position -= 1
            elif key_name == 'RIGHT':
                if self._cursor_position < len(self._text_buffer):
                    self._cursor_position += 1
            elif key_name == 'UP':
                self._cursor_position = 0  # Jump to start
            elif key_name == 'DOWN':
                self._cursor_position = len(self._text_buffer)  # Jump to end
            return
        elif key_name == 'SPACE':
            # Check filter - space is ' '
            if self._input_filter is not None and ' ' not in self._input_filter:
                return
            # Insert space at cursor
            self._text_buffer = (
                self._text_buffer[:self._cursor_position] +
                ' ' +
                self._text_buffer[self._cursor_position:]
            )
            self._cursor_position += 1
            return

        # Handle printable character keys
        char = None
        if len(key_name) == 1:
            # Single character key (A-Z, 0-9, punctuation, shifted symbols)
            char = key_name

        if char:
            # Check filter
            if self._input_filter is not None and char not in self._input_filter:
                return
            # Insert at cursor position
            self._text_buffer = (
                self._text_buffer[:self._cursor_position] +
                char +
                self._text_buffer[self._cursor_position:]
            )
            self._cursor_position += 1

    # =========================================================================
    # Keyboard Text Input API
    # =========================================================================

    def get_text_buffer(self) -> str:
        """Get current text buffer"""
        return self._text_buffer

    def set_text_buffer(self, text: str):
        """Set text buffer"""
        self._text_buffer = text
        # Clamp cursor to valid range
        self._cursor_position = min(self._cursor_position, len(self._text_buffer))

    def keyboard_did_submit(self) -> bool:
        """Returns True if ENTER was pressed (one-shot, cleared next cycle)"""
        return self._submit_flag

    def keyboard_did_cancel(self) -> bool:
        """Returns True if ESC was pressed (one-shot, cleared next cycle)"""
        return self._cancel_flag

    def keyboard_start_input(self, allowed=None, capture_arrows=True):
        """Start keyboard input mode

        Args:
            allowed: Optional frozenset of allowed characters, or None for all
            capture_arrows: When True (default), LEFT/RIGHT/UP/DOWN move the buffer cursor.
                When False, arrows are left for the app to consume via keyboard_last_key()
                - useful when the app wants arrows for highlight/selection navigation
                while still using the buffer for text input.
        """
        print("[enigma]   [Keyboard] Input started")
        # Clear buffer for fresh start
        self._text_buffer = ""
        self._cursor_position = 0
        self._last_scancodes = set()  # Reset held key tracking
        self._last_key = None  # Clear last key state
        self._last_key_next = None
        self._input_filter = allowed  # Store character filter
        self._capture_arrows = capture_arrows

        # Flush any pending data from socket to avoid stale keypresses
        if self.daemon.sock:
            self.daemon.sock.setblocking(False)
            try:
                while True:
                    data = self.daemon.sock.recv(1024)
                    if not data:
                        break
            except BlockingIOError:
                pass  # No more data to flush
            except Exception:
                pass
            self.daemon.sock.setblocking(True)

        self._input_active = True
        self._start_keystroke_thread()

    def keyboard_end_input(self):
        """End keyboard input mode"""
        print("[enigma]   [Keyboard] Input ended")
        self._input_active = False

    def keyboard_cursor_position(self) -> int:
        """Get cursor position"""
        return self._cursor_position

    def keyboard_cursor_to_end(self) -> None:
        """Snap cursor to the end of the text buffer. Useful after a restart
        that preserved buffer text - set_text_buffer clamps cursor down to
        the new length, so callers that want the caret at the end after a
        restore need this explicit nudge."""
        self._cursor_position = len(self._text_buffer)

    def keyboard_last_key(self) -> str:
        """Get last key pressed this cycle (None if no key pressed)"""
        return self._last_key

    def keyboard_cycle_start(self):
        """Called at start of each update cycle - swap double-buffered flags"""
        # Swap flags from "next" to "current"
        self._submit_flag = self._submit_flag_next
        self._cancel_flag = self._cancel_flag_next
        self._last_key = self._last_key_next

        # Clear "next" flags for next cycle
        self._submit_flag_next = False
        self._cancel_flag_next = False
        self._last_key_next = None


# Alias for backward compatibility
GProKeyboard = GProHandler


# Example usage
if __name__ == "__main__":
    kbd = GProHandler()

    if not kbd.daemon.connect():
        print("[enigma] Failed to connect to gpro_daemon. Is it running?")
        print("[enigma] Run: sudo /path/to/gpro_daemon")
        exit(1)

    print("[enigma] Connected to G Pro keyboard")
    print("[enigma] Testing...")

    # Test: Set all keys to dim blue
    kbd.current_colors = {kid: (0, 0, 128) for kid in KEYS.values()}
    kbd._render_colors()
    time.sleep(1)

    # Test: Pulse
    print("[enigma] Pulse test")
    kbd.pulse()
    time.sleep(1)

    # Test: Blanking
    print("[enigma] Blanking ON")
    kbd.set_blanking(BLANKING_ON)
    time.sleep(1)

    print("[enigma] Blanking OFF")
    kbd.set_blanking(BLANKING_OFF)
    time.sleep(1)

    # Test: Disruption (2 seconds)
    print("[enigma] Disruption mode (2 seconds)")
    kbd.set_blanking(BLANKING_DISRUPTION, param=20)  # 20 tenths = 2 sec
    time.sleep(3)

    # Reset
    print("[enigma] Reset")
    kbd.reset()

    kbd.close()
    print("[enigma] Done")
