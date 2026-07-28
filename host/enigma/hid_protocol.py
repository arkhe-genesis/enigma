# SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
# SPDX-License-Identifier: MIT

"""
enigma_hid.py - Core HID protocol implementation for Enigma devices

This module handles ONLY the HID protocol layer:
- Command/response framing (cmd + seq + payload)
- Command tracking and timeouts
- Response dispatching

Board-specific payload formats are handled by board handlers.
"""

import struct
import time
import threading
import queue
from enum import IntEnum
from dataclasses import dataclass
from typing import Optional, Callable, Dict, Tuple, Any

from enigma.colors import print_error

# HID Command opcodes (Host -> Device)
class HIDCommand(IntEnum):
    RESET = 0x01
    GETCONFIG = 0x02
    SETCONFIG = 0x03
    SETSTATE = 0x04
    GETSTATE = 0x05
    SETINDICATOR = 0x06
    SETBRIGHTNESS = 0x07
    STATUS = 0x08
    SETLOGLEVEL = 0x0D
    SETBLANKING = 0x0E
    PULSE = 0x0F
    ENABLE = 0x10

# Device -> Host responses
class HIDResponse(IntEnum):
    REPORTSTATE = 0x09
    ACK = 0x0A
    CONFIGREPORT = 0x0B
    LOGMSG = 0x0C

# Blanking modes
class BlankingMode(IntEnum):
    OFF = 0
    ON = 1
    DISRUPTION = 2

# Log levels
class LogLevel(IntEnum):
    ERROR = 0
    WARNING = 1
    INFO = 2
    DEBUG = 3

@dataclass
class ConfigReport:
    """Response from GETCONFIG command (universal across all board types)"""
    sequence: int
    board_type: str
    protocol_version: int
    hw_version: int
    sw_version: int
    variant: int
    address: int
    crc32: int
    
    @classmethod
    def from_bytes(cls, data: bytes) -> 'ConfigReport':
        """Parse CONFIGREPORT response
        
        Format: seq(4) + board_type(4) + proto(1) + hw(1) + sw(1) + 
                variant(1) + addr(1) + crc(4) = 17 bytes
        """
        if len(data) < 17:
            raise ValueError(f"ConfigReport data too short: {len(data)} bytes")
    
        seq = struct.unpack('<I', data[0:4])[0]
        board_type = data[4:8].decode('ascii', errors='ignore').rstrip('\x00')
        proto = data[8]
        hw = data[9]
        sw = data[10]
        variant = data[11]
        addr = data[12]
        crc = struct.unpack('<I', data[13:17])[0]
    
        return cls(
            sequence=seq,
            board_type=board_type,
            protocol_version=proto,
            hw_version=hw,
            sw_version=sw,
            variant=variant,
            address=addr,
            crc32=crc
        )

class EnigmaDevice:
    """Represents one connected Enigma HID device
    
    This class handles the HID protocol layer only. Board-specific
    logic (parsing state, formatting configs, etc.) is delegated to
    board handlers.
    """
    
    def __init__(self, hid_device, debug_wire: bool = False):
        self.hid = hid_device
        self.debug_wire = debug_wire
        self.pending_commands: Dict[int, Tuple[float, int, Optional[Callable]]] = {}
        self.next_seq = 1
        self.timeout = 10.0
        self.lock = threading.Lock()
        self.config_report: Optional[ConfigReport] = None

        # State tracking (stored as raw bytes, parsed by handler)
        self.current_states: Dict[int, bytes] = {}  # control_num -> raw state bytes
        self.active_scheme: str = "default"

        # Log message buffering
        self.log_buffer: str = ""

        # Callbacks
        self.on_state_report: Optional[Callable[[int, bytes], None]] = None
        self.on_log_message: Optional[Callable[[int, str], None]] = None

        # Background write queue (to avoid blocking on slow HID writes)
        self._write_queue: queue.Queue = queue.Queue()
        self._write_thread = threading.Thread(target=self._write_loop, daemon=True)
        self._write_thread.start()
        
    def send_command(self, cmd: HIDCommand, payload: bytes, 
                    callback: Optional[Callable] = None) -> int:
        """Send a command and track it for timeout
        
        Args:
            cmd: Command opcode
            payload: Command-specific payload (board handler provides this)
            callback: Optional callback for response
            
        Returns:
            Sequence number of sent command
        """
        with self.lock:
            seq = self.next_seq
            self.next_seq += 1
            if self.next_seq > 0xFFFFFFFF:
                self.next_seq = 1

        # Build packet: cmd (1) + seq (4) + payload
        packet = struct.pack('<BI', cmd, seq) + payload

        # Pad to 64 bytes
        packet += b'\x00' * (64 - len(packet))

        # Debug: Show TX data
        if self.debug_wire:
            print(f"[enigma] TX: {packet.hex()}")

        # Queue for background write (avoids blocking on slow HID writes)
        self._write_queue.put(packet)

        # Track for timeout
        with self.lock:
            self.pending_commands[seq] = (time.time(), cmd, callback)

        return seq

    def _write_loop(self):
        """Background thread that processes queued HID writes"""
        while True:
            try:
                packet = self._write_queue.get()
                if packet is None:  # Shutdown signal
                    break
                self.hid.write(packet)
            except Exception as e:
                print_error(f"[enigma] HID write error: {e}")
    
    def handle_response(self, data: bytes):
        """Process incoming HID report

        Strips off cmd + seq and dispatches payload to appropriate handler.
        """
        # Debug: Show RX data
        if self.debug_wire:
            print(f"[enigma] RX: {data.hex()}")

        if len(data) < 5:
            return
        
        cmd = data[0]
        seq = struct.unpack('<I', data[1:5])[0]
        payload = data[5:]
        
        if cmd == HIDResponse.ACK:
            self._handle_ack(seq, payload)
        elif cmd == HIDResponse.CONFIGREPORT:
            self._handle_config_report(seq, payload)
        elif cmd == HIDResponse.REPORTSTATE:
            self._handle_state_report(seq, payload)
        elif cmd == HIDResponse.LOGMSG:
            self._handle_log_message(payload)
    
    def _handle_ack(self, seq: int, payload: bytes):
        """Handle ACK response"""
        status = payload[0]
        message = payload[1:].rstrip(b'\x00').decode('ascii', errors='ignore')
        
        # Get callback while holding lock, then release before calling
        callback = None
        with self.lock:
            if seq in self.pending_commands:
                _, cmd, callback = self.pending_commands.pop(seq)
        
        # Call callback outside lock to avoid deadlock
        if callback:
            callback(status, message)
    
    def _handle_config_report(self, seq: int, payload: bytes):
        """Handle CONFIGREPORT response"""
        self.config_report = ConfigReport.from_bytes(
            data=struct.pack('<I', seq) + payload
        )
        
        # Get callback while holding lock, then release before calling
        callback = None
        with self.lock:
            if seq in self.pending_commands:
                _, cmd, callback = self.pending_commands.pop(seq)
        
        # Call callback outside lock to avoid deadlock
        if callback:
            callback(self.config_report)
    
    def _handle_state_report(self, seq: int, payload: bytes):
        """Handle REPORTSTATE message
        
        Payload format: control_num(1) + state_data(N bytes)
        State data is board-specific and parsed by handler.
        """
        control_num = payload[0]
        state_data = payload[1:]
        
        # Store raw state data
        self.current_states[control_num] = state_data
        
        # Notify callback with raw state data
        if self.on_state_report:
            self.on_state_report(control_num, state_data)
        
#        # Send ACK back (write directly, don't use send_command)
#        # Format: cmd(1) + seq(4) + status(1) + message(59)
#        ack_packet = struct.pack('<BIB', HIDResponse.ACK, seq, 0) + b'\x00' * 59
#        self.hid.write(ack_packet)
    
    def _handle_log_message(self, payload: bytes):
        """Handle LOGMSG response"""
        level = payload[0]
        msg_chunk = payload[1:].rstrip(b'\x00').decode('ascii', errors='ignore')
 
        # Buffer log messages until we get a newline
        self.log_buffer += msg_chunk
        
        if '\n' in self.log_buffer:
            lines = self.log_buffer.split('\n')
            for line in lines[:-1]:
                if self.on_log_message:
                    self.on_log_message(level, line)
            self.log_buffer = lines[-1]
    
    def check_timeouts(self):
        """Check for timed out commands"""
        now = time.time()
        timed_out = []
        
        with self.lock:
            for seq, (timestamp, cmd, callback) in self.pending_commands.items():
                if now - timestamp > self.timeout:
                    timed_out.append(seq)
        
        for seq in timed_out:
            with self.lock:
                timestamp, cmd, callback = self.pending_commands.pop(seq)
            if callback:
                callback(255, "Timeout")
    
    # High-level command methods
    # These take raw payloads from board handlers
    
    def reset(self, timebase_ms: int, callback: Optional[Callable] = None) -> int:
        """Send RESET command
        
        Args:
            timebase_ms: Current timebase in milliseconds
        """
        payload = struct.pack('<I', timebase_ms)
        return self.send_command(HIDCommand.RESET, payload, callback)
    
    def get_config(self, callback: Optional[Callable] = None) -> int:
        """Send GETCONFIG command"""
        return self.send_command(HIDCommand.GETCONFIG, b'', callback)
    
    def set_config(self, payload: bytes, callback: Optional[Callable] = None) -> int:
        """Send SETCONFIG command with board-specific payload
        
        Args:
            payload: Board-specific config data (from handler)
        """
        return self.send_command(HIDCommand.SETCONFIG, payload, callback)
    
    def set_state(self, control_num: int, state_data: bytes, 
                 callback: Optional[Callable] = None) -> int:
        """Send SETSTATE command
        
        Args:
            control_num: Control number
            state_data: Board-specific state data (from handler)
        """
        payload = struct.pack('<B', control_num) + state_data
        return self.send_command(HIDCommand.SETSTATE, payload, callback)
    
    def get_state(self, control_num: int, callback: Optional[Callable] = None) -> int:
        """Send GETSTATE command"""
        payload = struct.pack('<B', control_num)
        return self.send_command(HIDCommand.GETSTATE, payload, callback)
    
    def set_indicator(self, control_num: int, indicator_data: bytes,
                     callback: Optional[Callable] = None) -> int:
        """Send SETINDICATOR command with board-specific payload
        
        Args:
            control_num: Control number
            indicator_data: Board-specific indicator data (from handler)
        """
        payload = struct.pack('<B', control_num) + indicator_data
        return self.send_command(HIDCommand.SETINDICATOR, payload, callback)
    
    def set_brightness(self, brightness: int, callback: Optional[Callable] = None) -> int:
        """Send SETBRIGHTNESS command
        
        Args:
            brightness: 0-255
        """
        payload = struct.pack('<B', brightness)
        return self.send_command(HIDCommand.SETBRIGHTNESS, payload, callback)
    
    def set_log_level(self, level: LogLevel, callback: Optional[Callable] = None) -> int:
        """Send SETLOGLEVEL command"""
        payload = struct.pack('<B', level)
        return self.send_command(HIDCommand.SETLOGLEVEL, payload, callback)
    
    def set_blanking(self, mode: BlankingMode, duration_tenths: int = 0, 
                    callback: Optional[Callable] = None) -> int:
        """Send SETBLANKING command
        
        Args:
            mode: Blanking mode (OFF, ON, DISRUPTION)
            duration_tenths: For DISRUPTION mode, duration before full blank (0-255)
        """
        if mode == BlankingMode.DISRUPTION:
            payload = struct.pack('<BB', mode, duration_tenths)
        else:
            payload = struct.pack('<B', mode)
        return self.send_command(HIDCommand.SETBLANKING, payload, callback)
    
    def pulse(self, callback: Optional[Callable] = None) -> int:
        """DISABLED - PULSE command flashes all LEDs white, which draws enough current
        to blow the LDO on SW14/QD04 boards. Do not re-enable without hardware fix.
        SW14 and QD04 inherit this no-op; GPro overrides it with its own safe implementation."""
        return 0

    def set_enable_mask(self, mask: int) -> int:
        """Send ENABLE command - set which controls report state changes

        Args:
            mask: uint16 bitmask, bit N-1 = control N (1=enabled, 0=disabled)
        """
        payload = struct.pack('<H', mask)
        return self.send_command(HIDCommand.ENABLE, payload)
    
    def status(self, callback: Optional[Callable] = None) -> int:
        """Send STATUS ping"""
        return self.send_command(HIDCommand.STATUS, b'', callback)
    
    # Accessors
    
    def get_board_id(self) -> Optional[str]:
        """Get board ID string (e.g. 'SW14-00')"""
        if self.config_report:
            return f"{self.config_report.board_type}-{self.config_report.address:02d}"
        return None
    
    def get_control_state(self, control_num: int) -> Optional[bytes]:
        """Get the current state of a control as raw bytes
        
        Use board handler to parse into human-readable format.
        """
        return self.current_states.get(control_num)
    
    def set_control_state(self, control_num: int, state_data: bytes):
        """Update the stored state of a control (called by handler)"""
        self.current_states[control_num] = state_data
