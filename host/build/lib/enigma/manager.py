# SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
# SPDX-License-Identifier: MIT

"""
enigma.manager - HID device enumeration and management

Handles, for Enigma and Thrustmaster devices:
- Device enumeration and connection
- Configuration loading and application
- State change monitoring
- High-level command interface (reset_all, set_brightness_all, etc.)
"""

import hid
import time
import threading
import json
from pathlib import Path
from typing import Dict, Optional, Callable, Any, Union, List

from .hid_protocol import EnigmaDevice, ConfigReport
from .config import ConfigManager
from . import boards
from .boards import get_board_handler
from .colors import print_error, print_warning

# Module-level manager singleton
_manager_instance = None

def get_manager():
    """Get the global manager instance"""
    if _manager_instance is None:
        raise RuntimeError("Manager not initialized. Create EnigmaManager first.")
    return _manager_instance

def register_control_class(control_class):
    """Register a generated control class for changed flag management

    Called automatically when control classes are instantiated.
    Safe to call before manager is created - will register when manager starts.
    """
    global _manager_instance
    if _manager_instance is not None:
        if control_class not in _manager_instance.control_classes:
            _manager_instance.control_classes.append(control_class)
    # If manager doesn't exist yet, that's fine - controls will be available
    # when manager is created since they're module-level singletons

# VID/PID constants
ENIGMA_VID = 0x303A
ENIGMA_PID = 0x1001

# Thrustmaster (imported dynamically if needed)
try:
    from .boards.thrustmaster import THRUSTMASTER_VID, THRUSTMASTER_PID
    THRUSTMASTER_SUPPORT = True
except ImportError:
    THRUSTMASTER_SUPPORT = False
    THRUSTMASTER_VID = None
    THRUSTMASTER_PID = None

class ThrustmasterDevice:
    """Simple wrapper for Thrustmaster devices (fake Enigma device)"""

    def __init__(self, hid_device, address=None):
        self.hid = hid_device
        self.address = address  # 0 or 1 (side switch)
        self.board_type = "T16K"
        self.variant = 255  # Special variant for non-Enigma
        self.handler = None
        self.config_report = None

        # State tracking (minimal for Thrustmaster)
        self.current_states = {}
        self.active_scheme = "default"

    def get_board_id(self):
        """Get board ID string"""
        if self.address is not None:
            return f"{self.board_type}-{self.address:02d}"
        return None

    def check_timeouts(self):
        """Thrustmaster doesn't need timeout checking"""
        pass

    def read_and_process(self):
        """Read and process a HID report"""
        data = self.hid.read(64, timeout_ms=0)
        if data and len(data) >= 9:
            report = bytes(data[:9])
            if self.handler:
                self.handler.process_report(report)

    def on_state_change(self, control_num, state_data):
        """Called by handler when state changes"""
        self.current_states[control_num] = state_data

        # Propagate to manager callback if set
        if hasattr(self, '_state_callback') and self._state_callback:
            self._state_callback(self, control_num, state_data)

    def get_control_state(self, control_num):
        """Get current state for a control by number"""
        return self.current_states.get(control_num)


class EnigmaManager:
    """Manages multiple Enigma and Thrustmaster HID devices"""

    def __init__(self, config_manager: ConfigManager, debug_wire: bool = None, debug_rx: bool = None, debug_tx: bool = None, power_event_listener=None):
        # Register as singleton
        global _manager_instance
        _manager_instance = self

        # Get CLI config (populated by enigma.configure_from_args)
        from . import get_cli_config
        cli_config = get_cli_config()

        # Use explicit params if provided, otherwise fall back to CLI config
        self.config_manager = config_manager
        self.debug_wire = debug_wire if debug_wire is not None else cli_config.get('debug_wire', False)
        self.debug_rx = debug_rx if debug_rx is not None else cli_config.get('debug_rx', False)
        self.debug_tx = debug_tx if debug_tx is not None else cli_config.get('debug_tx', False)
        self.devices: Dict[bytes, Union[EnigmaDevice, ThrustmasterDevice]] = {}  # path -> Device
        self.devices_by_id: Dict[str, Union[EnigmaDevice, ThrustmasterDevice]] = {}  # board_id -> Device
        self.running = False
        self.poll_thread: Optional[threading.Thread] = None

        # Event queue for synchronous processing
        self.event_queue: List[tuple] = []
        self.event_lock = threading.Lock()

        # Queue for devices pending configuration (to avoid blocking read loop)
        self._pending_configs: List[tuple] = []  # [(device, board_id), ...]

        # Registry for generated control classes
        self.control_classes: List[Any] = []

        # Shared timebase for animation synchronization across all boards
        self._timebase_ms = int(time.time() * 1000) % 0xFFFFFFFF

        # Initialize display manager if configs exist
        self.display_manager = None
        try:
            from .displaymanager import DisplayManager
            # DisplayManager will check for display_mappings.json and handle gracefully if not found
            self.display_manager = DisplayManager(config_manager.config_dir)
        except Exception as e:
            print_warning(f"WARNING: Could not initialize DisplayManager: {e}")


        # Callbacks
        self.on_device_connected: Optional[Callable[[str, Any], None]] = None
        self.on_device_disconnected: Optional[Callable[[str], None]] = None
        self.on_state_change: Optional[Callable[[Any, int, bytes], None]] = None
        self.on_log_message: Optional[Callable[[Any, int, str], None]] = None

        # Power-event flag - set from arbitrary threads (sleep/wake
        # callback), read at the top of the poll loop. On wake, the OS
        # leaves HID handles silently orphaned: hidapi keeps reporting
        # the device as enumerable, reads return no data, writes appear
        # to succeed, but nothing reaches the panel. The only fix is to
        # drop and reopen every handle. We defer the actual disconnect
        # to the poll thread so the listener thread never touches
        # self.devices directly.
        self._invalidate_pending = False

        # Sleep/wake listener. Caller can pass their own to handle other
        # platforms; otherwise the macOS IOKit implementation auto-wires.
        # Listener calls invalidate_all() on wake (and on will-sleep, so
        # we close handles before the USB stack actually goes down).
        if power_event_listener is None:
            from .power_events import make_default_listener
            power_event_listener = make_default_listener(self.invalidate_all)
        self._power_listener = power_event_listener

    def start(self):
        """Start device monitoring"""
        # Auto-discover and register control instances from controls module
        try:
            from generated import controls
            for attr_name in dir(controls):
                # Skip private attributes starting with underscore (those are the classes)
                if attr_name.startswith('_'):
                    continue

                attr = getattr(controls, attr_name)
                # Look for instances that have clear_changed_flags method (our generated devices)
                if hasattr(attr, 'clear_changed_flags') and callable(getattr(attr, 'clear_changed_flags')):
                    if attr not in self.control_classes:
                        self.control_classes.append(attr)
        except ImportError:
            pass  # controls.py not generated yet

        # Initialize G Pro Keyboard if Keyboard.json config exists
        # GPRO boards don't use USB HID, they connect via daemon socket
        for board_id, config_name in self.config_manager.board_mappings.items():
            if board_id.startswith('GPRO-'):
                config_file = self.config_manager.get_config_file(board_id)
                if not config_file:
                    continue

                print(f"[enigma] Initializing {config_name} (GPRO keyboard)...")
                try:
                    from .boards.gpro import GProHandler
                    import json

                    # Create handler (device=None for GPRO)
                    handler = GProHandler(device=None)

                    # Load config
                    with open(config_file, 'r') as f:
                        config_data = json.load(f)
                    handler.parse_config(config_data)

                    # Connect to daemon
                    if handler.daemon.connect():
                        # Create device wrapper (like ThrustmasterDevice)
                        class GProDevice:
                            def __init__(self, handler, board_id):
                                self.handler = handler
                                self.board_type = "GPRO"
                                self.variant = 0
                                self._board_id = board_id

                            def get_board_id(self):
                                return self._board_id

                        device = GProDevice(handler, board_id)
                        self.devices_by_id[board_id] = device
                    else:
                        print_error(f"[enigma]   Failed to connect to gpro_daemon - make sure it's running")
                except Exception as e:
                    print_error(f"[enigma]   Failed to initialize: {e}")
                    import traceback
                    traceback.print_exc()

        self.running = True
        self._initial_reset_done = False  # Track if we've done the initial reset_all
        self.poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self.poll_thread.start()

        # Start the sleep/wake listener (no-op on platforms without one).
        if self._power_listener is not None:
            self._power_listener.start()

        print("[enigma] EnigmaManager started")

    def invalidate_all(self):
        """Force every device to close and re-enumerate on the next poll
        iteration. Thread-safe - sets a flag the poll loop drains.

        Intended for power-event listeners on sleep/wake, where USB-HID
        handles silently orphan: the OS keeps the device's IOKit path
        stable, hidapi keeps enumerating it, but reads/writes go to a
        gone-away handle. Without an external "your handles are stale"
        signal there's no error path to follow - the only fix is to
        invalidate everything and reopen against the fresh IOKit
        registry entries on the next enumerate."""
        self._invalidate_pending = True

    def stop(self):
        """Stop device monitoring"""
        self.running = False
        if self._power_listener is not None:
            try:
                self._power_listener.stop()
            except Exception as e:
                print_warning(f"Power listener stop failed: {e}")
        if self.poll_thread:
            self.poll_thread.join()

        # Stop display manager
        if self.display_manager:
            try:
                self.display_manager.stop()
            except Exception as e:
                print_warning(f"WARNING: Could not stop DisplayManager: {e}")

        # Close all devices
        for device in self.devices.values():
            device.hid.close()
        self.devices.clear()
        self.devices_by_id.clear()
        print("[enigma] EnigmaManager stopped")

    def _poll_loop(self):
        """Background thread for device enumeration and reading"""
        initial_delay = 0.3  # Wait for devices to enumerate before initial reset
        start_time = time.time()

        while self.running:
            # Drain a pending power-event invalidation in this thread
            # (self.devices is otherwise touched only from the poll loop,
            # so the listener thread sets the flag and we do the work).
            if self._invalidate_pending:
                self._invalidate_pending = False
                stale_paths = list(self.devices.keys())
                if stale_paths:
                    print(f"[enigma] Power event: invalidating {len(stale_paths)} HID handle(s)")
                    for path in stale_paths:
                        self._disconnect_device(path)
                # Next _enumerate_devices reopens against fresh IOKit entries.

            self._enumerate_devices()
            self._read_devices()
            self._check_timeouts()
            self._process_pending_configs()

            # Note: We skip initial reset_all() here because each device is already
            # reset during _configure_device(). The reset_all() is for game restarts.
            if not self._initial_reset_done and (time.time() - start_time) > initial_delay:
                self._initial_reset_done = True

            time.sleep(0.01)  # 10ms poll rate

    def _enumerate_devices(self):
        """Check for new/removed devices (both Enigma and Thrustmaster)"""
        current_devices = {}

        # Find all Enigma devices
        for dev_info in hid.enumerate(ENIGMA_VID, ENIGMA_PID):
            path = dev_info['path']
            current_devices[path] = ('enigma', dev_info)

        # Find all Thrustmaster devices (if supported)
        if THRUSTMASTER_SUPPORT:
            for dev_info in hid.enumerate(THRUSTMASTER_VID, THRUSTMASTER_PID):
                path = dev_info['path']
                current_devices[path] = ('thrustmaster', dev_info)

        # Check for new devices
        for path, (device_type, dev_info) in current_devices.items():
            if path not in self.devices:
                self._connect_device(path, device_type, dev_info)

        # Check for removed devices
        removed = set(self.devices.keys()) - set(current_devices.keys())
        for path in removed:
            self._disconnect_device(path)

    def _connect_device(self, path: bytes, device_type: str, dev_info: dict):
        """Connect to a new device (Enigma or Thrustmaster)"""
        try:
            hid_dev = hid.device()
            hid_dev.open_path(path)
            hid_dev.set_nonblocking(True)

            if device_type == 'enigma':
                # Create EnigmaDevice
                device = EnigmaDevice(hid_dev, debug_wire=self.debug_wire)
                self.devices[path] = device

                # Set up callbacks
                device.on_state_report = lambda ctrl, data: self._handle_state_report(device, ctrl, data)
                device.on_log_message = lambda level, msg: self._handle_log_message(device, level, msg)

                # Query device config
                def on_config(config_report, message=None, _dev_info=dev_info, _self=self):
                    if message is not None:
                        # Before config is received, we don't know the board ID yet
                        # Show which devices DID connect to help identify the failing one
                        connected_ids = list(_self.devices_by_id.keys())
                        if connected_ids:
                            print_error(f"[enigma] Config query failed for an Enigma device: {message}")
                            print_error(f"[enigma]   (Already connected: {', '.join(connected_ids)})")
                        else:
                            print_error(f"[enigma] Config query failed for an Enigma device: {message}")
                        return

                    board_id = device.get_board_id()
                    print(f"[enigma] Device identified: {board_id} (Proto v{config_report.protocol_version}, HW v{config_report.hw_version}, SW v{config_report.sw_version})")

                    # Queue for configuration (don't block the read loop)
                    self._pending_configs.append((device, board_id))

                device.get_config(callback=on_config)

            elif device_type == 'thrustmaster':
                # Create ThrustmasterDevice
                device = ThrustmasterDevice(hid_dev, address=None)  # Address TBD
                self.devices[path] = device

                # Set up state callback
                device._state_callback = lambda dev, ctrl, data: self._handle_state_report(dev, ctrl, data)

                # Device will auto-identify on first report in _read_devices()

        except Exception as e:
            print_error(f"[enigma] Failed to connect device: {e}")
            import traceback
            traceback.print_exc()

    def _disconnect_device(self, path: bytes):
        """Disconnect a device"""
        device = self.devices.pop(path, None)
        if device:
            board_id = device.get_board_id()

            # Remove from ID lookup
            if board_id and board_id in self.devices_by_id:
                del self.devices_by_id[board_id]

            # Flush any queued events from this device
            with self.event_lock:
                self.event_queue = [e for e in self.event_queue if e[1] is not device]

            # Close handle - may already be invalid if device was yanked
            try:
                device.hid.close()
            except Exception:
                pass  # Device already gone

            print(f"[enigma] Disconnected: {board_id}")

            if self.on_device_disconnected:
                self.on_device_disconnected(board_id)

    def _create_handler(self, device: Union[EnigmaDevice, ThrustmasterDevice], board_id: str):
        """Create board-specific handler for device"""
        if isinstance(device, EnigmaDevice):
            variant = device.config_report.variant
            board_type = device.config_report.board_type
        else:
            variant = device.variant
            board_type = device.board_type

        handler_class = get_board_handler(variant, board_type)
        if not handler_class:
            print_warning(f"WARNING: No handler found for variant={variant}, type={board_type}")
            from boards import list_board_variants
            print(f"[enigma] Registered variants: {list_board_variants()}")
            return

        device.handler = handler_class(device)

    def _configure_device(self, device: Union[EnigmaDevice, ThrustmasterDevice], board_id: str):
        """Load and apply configuration to device"""
        if not hasattr(device, 'handler') or not device.handler:
            print(f"[enigma] No handler for {board_id}, skipping configuration")
            return

        # Look up config name from mappings
        # Get config file for this board
        config_file = self.config_manager.get_config_file(board_id)
        if not config_file:
            return

        # Load and parse config through handler
        with open(config_file, 'r') as f:
            config_data = json.load(f)

        print(f"[enigma] Configuring {board_id} with '{config_data.get('name')}'...")

        # Parse config through handler
        device.handler.config = device.handler.parse_config(config_data)
        device.handler._config_default_mask = device.handler._compute_config_default_mask()

        if isinstance(device, ThrustmasterDevice):
            # Thrustmaster: read-only, no config upload needed
            # Initialize enable mask from config defaults (software-side filtering)
            device.handler._enable_mask = device.handler._config_default_mask
            device.handler._enable_stack = []
        else:
            # Enigma: Check if config needs to be sent by comparing CRC
            import zlib
            config_bytes = b''

            # Include ALL controls (with blanks for missing ones) to match what's sent
            for control_num in range(1, device.handler.get_control_count() + 1):
                if control_num in device.handler.config.controls:
                    control_config = device.handler.config.controls[control_num]
                else:
                    control_config = device.handler.create_blank_config(control_num)
                payload = control_config.to_setconfig_payload()
                config_bytes += payload

            computed_crc = zlib.crc32(config_bytes) & 0xFFFFFFFF
            device_crc = device.config_report.crc32 if device.config_report else 0

            if computed_crc != device_crc:
                print(f"[enigma]   Device CRC: {device_crc:08X}, Computed CRC: {computed_crc:08X}")
                print(f"[enigma]   CRC mismatch - sending configuration...")
                device.handler.send_all_configs(delay_ms=1, send_blanks=True)

                # Send RESET with shared timebase for animation sync
                device.reset(self._timebase_ms)

                print(f"[enigma]   Configuration complete for {board_id}")
            else:
                # Still send RESET to sync timebase
                device.reset(self._timebase_ms)

            # Reset handler state (default values, schemes, etc.)
            # Writes are now queued in background, so this won't block
            device.handler.reset(send_to_hardware=True)

            # Sync any non-default cached values back to device
            if hasattr(device.handler, 'sync_state_to_device'):
                device.handler.sync_state_to_device()

    def _read_devices(self):
        """Read from all devices"""
        for path, device in list(self.devices.items()):
            try:
                if isinstance(device, ThrustmasterDevice):
                    # Thrustmaster: identify on first report, then process
                    if device.address is None:
                        data = device.hid.read(64, timeout_ms=0)
                        if data and len(data) >= 9:
                            report = bytes(data[:9])
                            side_switch = (report[2] & 0x20) >> 5
                            device.address = side_switch

                            board_id = device.get_board_id()
                            print(f"[enigma] Thrustmaster identified: {board_id}")

                            # Create handler and configure
                            self._create_handler(device, board_id)
                            self._configure_device(device, board_id)

                            # Add to ID lookup
                            self.devices_by_id[board_id] = device

                            # Process the identifying report now that handler exists
                            # (otherwise the event that triggered enumeration is lost)
                            device.handler.process_report(report)

                            # Notify callback
                            if self.on_device_connected:
                                self.on_device_connected(board_id, device)
                    else:
                        # Normal processing
                        device.read_and_process()
                else:
                    # EnigmaDevice: read and handle responses
                    data = device.hid.read(64, timeout_ms=0)
                    if data:
                        device.handle_response(bytes(data))
            except Exception as e:
                # Read failure likely means device was yanked - disconnect immediately
                # to avoid processing garbage data on subsequent reads
                self._disconnect_device(path)

    def _check_timeouts(self):
        """Check command timeouts"""
        for device in self.devices.values():
            device.check_timeouts()

    def _process_pending_configs(self):
        """Process any devices waiting for configuration"""
        while self._pending_configs:
            device, board_id = self._pending_configs.pop(0)

            # Create handler
            self._create_handler(device, board_id)

            # Configure device
            if hasattr(device, 'handler') and device.handler:
                self._configure_device(device, board_id)

            # Add to ID lookup
            self.devices_by_id[board_id] = device

            # Notify callback
            if self.on_device_connected:
                self.on_device_connected(board_id, device)

    def _handle_state_report(self, device: Union[EnigmaDevice, ThrustmasterDevice],
                            control_num: int, state_data: bytes):
        """Handle state change from device"""
        if not hasattr(device, 'handler') or not device.handler or not device.handler.config:
            return

        # Let handler process the state report (updates cache, handles radio groups, etc.)
        device.handler.on_hardware_state_report(control_num, state_data)

        # Parse state for logging
        control_state = device.handler._parse_state(state_data, control_num)

        # Log control state changes if debug_rx is enabled
        if self.debug_rx:
            msg = device.handler.config.format_state_change(control_num, control_state)
            device_name = device.handler.config.name if device.handler and device.handler.config else device.get_board_id()
            print(f"[enigma] [{device_name}] {msg}")

        # Queue event for synchronous processing
        with self.event_lock:
            self.event_queue.append(('state_change', device, control_num, state_data))

    def update(self):
        """Process queued events (call this from your main loop)

        This processes all state changes that occurred since the last update.
        Call this regularly (e.g., every frame) to handle device events.

        Returns:
            Number of events processed
        """
        # Clear the "changed this cycle" flags at the start
        for control_instance in self.control_classes:
            if hasattr(control_instance, 'clear_changed_flags'):
                control_instance.clear_changed_flags()

        # Swap keyboard double-buffered flags at cycle start
        for board_id, device in self.devices_by_id.items():
            if board_id.startswith('GPRO-') and device.handler:
                if hasattr(device.handler, 'keyboard_cycle_start'):
                    device.handler.keyboard_cycle_start()

        events_to_process = []

        # Get all queued events
        with self.event_lock:
            events_to_process = self.event_queue[:]
            self.event_queue.clear()

        # Process events outside the lock
        for event in events_to_process:
            event_type = event[0]

            if event_type == 'state_change':
                _, device, control_num, state_data = event
                if self.on_state_change:
                    self.on_state_change(device, control_num, state_data)

        # Let panel managers update their logic
        try:
            from .panelmanager import PanelManager
            PanelManager.update_all()
        except ImportError:
            pass  # panelmanager not available

        # Run device simulation logic and commit published values
        try:
            from .device import (Device, PublishedValue,
                                 set_current_updating_device, clear_current_updating_device,
                                 clear_write_tracking)
            for device in Device.all():
                set_current_updating_device(device.__class__.__name__)
                device.update()
                clear_current_updating_device()
            # Clear write tracking and commit pending values
            clear_write_tracking()
            PublishedValue.commit_all()
        except ImportError:
            pass  # device specs not generated yet

        # Clear hardware change tracking after device updates have run
        for board_id, device in self.devices_by_id.items():
            if hasattr(device, 'handler') and device.handler:
                device.handler.clear_hardware_changed()

        # Publish device attribute changes to remote displays
        if self.display_manager:
            self.display_manager.update()

        return len(events_to_process)

    def _handle_log_message(self, device: EnigmaDevice, level: int, message: str):
        """Handle log message from device"""
        if not hasattr(device, 'handler') or not device.handler:
            return

        level_names = ['ERROR', 'WARN', 'INFO', 'DEBUG']
        level_name = level_names[level] if level < len(level_names) else 'UNKNOWN'
        # Get friendly name from config
        device_name = device.handler.config.name if device.handler and device.handler.config else device.get_board_id()

        print(f"[enigma] [{device_name}] [{level_name}] {message}")
#        print(f"[{device.get_board_id()}] [{level_name}] {message}")

        # Notify callback
        if self.on_log_message:
            self.on_log_message(device, level, message)

    # High-level interface methods

    def get_device(self, board_id: str) -> Optional[Union[EnigmaDevice, ThrustmasterDevice]]:
        """Get device by board ID (e.g. 'SW14-00', 'T16K-01')"""
        return self.devices_by_id.get(board_id)

    def get_all_devices(self) -> Dict[str, Union[EnigmaDevice, ThrustmasterDevice]]:
        """Get all connected devices as {board_id: device}"""
        return self.devices_by_id.copy()

    def get_controls(self, device_name: str, control_name: str) -> List[tuple]:
        """Get controls matching device and control names

        Returns list of (device, control_num) tuples since multiple controls
        can share the same name (radio buttons, etc.)

        Args:
            device_name: Device board name (e.g. 'PortEngine')
            control_name: Control name (e.g. 'Coolant')
        """
        results = []

        for board_id, device in self.devices_by_id.items():
            if not device.handler or not device.handler.config:
                continue

            # Check if device name matches
            if device.handler.config.name != device_name:
                continue

            # Find all controls with matching name
            for control_num, control in device.handler.config.controls.items():
                if control.name == control_name:
                    results.append((device, control_num))

        return results

    def get_control_value(self, device_name: str, control_name: str):
        """Get the current value of a control (simplified interface)

        Returns the semantic value string from the config if defined, otherwise
        returns the ControlState object.

        For ANY control where the config defines a "value" string for the active state,
        returns that string. Otherwise returns the ControlState object.

        This method ALWAYS returns a valid object, never None, so you can safely
        access without checking.

        Args:
            device_name: Device board name (e.g. 'PowerCore')
            control_name: Control name (e.g. 'System')

        Returns:
            - Control with value string: string (e.g. 'lifesupport', 'auto', 'arm')
            - Control without value string: ControlState object
            - Not found: empty string "" or ControlState with value=None

        Examples:
            >>> power = manager.get_control_value("PowerCore", "System")
            >>> if power == 'lifesupport':  # Radio group returns string
            >>>     ...

            >>> auto = manager.get_control_value("PowerCore", "Auto")
            >>> if auto == 'auto':  # Single control with value strings
            >>>     ...

            >>> ignition = manager.get_control_value("StarboardEngine", "Ignition")
            >>> if ignition.value == 1:  # Control without value strings returns ControlState
            >>>     ...
        """
        from .boards.base import ControlState

        controls = self.get_controls(device_name, control_name)

        if not controls:
            # Return None when control not found
            return None

        # Check if this is a radio group (multiple controls with same name)
        is_radio_group = len(controls) > 1

        # Check cached states for each control
        for device, control_num in controls:
            cached_state = device.get_control_state(control_num)
            if not cached_state:
                continue

            control_state = device.handler._parse_state(cached_state, control_num)
            control_config = device.handler.config.controls.get(control_num)

            if is_radio_group:
                # Radio group - find the active one (any non-zero state)
                if hasattr(control_state, 'value') and control_state.value != 0:
                    # Get the value string from the active state
                    state_num = control_state.value
                    if control_config and hasattr(control_config, 'states') and state_num in control_config.states:
                        value_str = control_config.states[state_num].value
                        if value_str:
                            return value_str  # Return string
                        else:
                            return control_state.value  # No value string, return state number as int
            else:
                # Single control - check if config has a value string for this state
                if control_config and hasattr(control_config, 'states'):
                    state_num = getattr(control_state, 'value', None)
                    if state_num is not None and state_num in control_config.states:
                        value_str = control_config.states[state_num].value
                        if value_str:
                            return value_str  # Return string

                # Check if this is a QD04 control (has position_to_value method)
                if control_config and hasattr(control_config, 'position_to_value') and hasattr(control_state, 'position'):
                    # QD04 control - convert position to real numeric value
                    return control_config.position_to_value(control_state.position)

                # No value string and not QD04 - return the numeric value
                return getattr(control_state, 'value', 0)

        # No active control found - return default from config if available
        if is_radio_group:
            return ""  # Radio group with no active button returns empty string
        else:
            # Try to get default_value from the control config
            for device, control_num in controls:
                if device.handler and device.handler.config:
                    control_config = device.handler.config.controls.get(control_num)
                    if control_config and hasattr(control_config, 'default_value'):
                        return control_config.default_value
            return None  # No default available

    def set_control_value(self, device_name: str, control_name: str, value):
        """Set the value of a control (simplified interface)

        For controls with value strings: Pass the string (e.g., 'auto', 'arm', 'lifesupport')
        For controls without value strings: Pass a state number (int) or ControlState object

        For radio groups (multiple controls sharing same name): Sets the matching control
        to active state and all others to state 0 (off).

        Args:
            device_name: Device board name (e.g. 'PowerCore')
            control_name: Control name (e.g. 'Auto')
            value: String value, int state number, or ControlState object

        Returns:
            True if successful, False otherwise

        Examples:
            >>> # Set using value string
            >>> manager.set_control_value("PowerCore", "Auto", "auto")

            >>> # Set using state number
            >>> manager.set_control_value("StarboardEngine", "Ignition", 1)
        """
        controls = self.get_controls(device_name, control_name)

        if not controls:
            return False

        # For radio groups (multiple controls with same name), find and set the
        # matching control. Firmware handles turning off other buttons in the group.
        if len(controls) > 1 and isinstance(value, str):
            for device, control_num in controls:
                if not device.handler:
                    continue
                try:
                    if device.handler.set_control_by_value(control_num, value):
                        return True
                except Exception as e:
                    print_error(f"[enigma] Error setting control {control_name}: {e}")
            return False

        # Single control - just set it directly
        for device, control_num in controls:
            if device.handler:
                try:
                    if device.handler.set_control_by_value(control_num, value):
                        return True
                except Exception as e:
                    print_error(f"[enigma] Error setting control {control_name} to {value}: {e}")
                    continue

        return False

    def reset_all(self, timebase_ms: Optional[int] = None):
        """Send RESET to all Enigma devices and reset simulation state

        This is a "nuclear reset" - all cached values are cleared and everything
        returns to defaults. Use this for game start/restart.

        Args:
            timebase_ms: Timebase in milliseconds (defaults to current time)
        """
        if timebase_ms is None:
            timebase_ms = int(time.time() * 1000) % 0xFFFFFFFF

        # Update shared timebase for any future device connections
        self._timebase_ms = timebase_ms

        # Send RESET to all Enigma HID devices first (rapid succession for sync)
        for device in self.devices.values():
            if isinstance(device, EnigmaDevice) and hasattr(device, 'handler') and device.handler:
                device.reset(timebase_ms)

        # Give firmware time to process RESET before sending SETSTATE commands
        time.sleep(0.05)

        # Then reset handler state with full_reset=True (clears all cached values)
        for device in self.devices.values():
            if isinstance(device, EnigmaDevice) and hasattr(device, 'handler') and device.handler:
                device.handler.reset(full_reset=True)
                # Send config-default enable mask if any controls are disabled
                if getattr(device.handler, '_config_default_mask', 0xFFFF) != 0xFFFF:
                    device.handler.send_enable_mask(device.handler._enable_mask)

        # Reset GPRO devices with full_reset=True (no sync - we want defaults)
        for board_id, device in self.devices_by_id.items():
            if board_id.startswith('GPRO-') and hasattr(device, 'handler') and device.handler:
                device.handler.reset(full_reset=True)

        # Reset Thrustmaster enable masks to config defaults
        for device in self.devices.values():
            if isinstance(device, ThrustmasterDevice) and hasattr(device, 'handler') and device.handler:
                device.handler.reset(full_reset=True)

        # Reset change tracking on control wrappers (so changed() works correctly after reset)
        for control_instance in self.control_classes:
            if hasattr(control_instance, 'reset_change_tracking'):
                control_instance.reset_change_tracking()

        # Reset simulation devices and published values
        try:
            from .device import Device, PublishedValue
            # Reset all published values to defaults
            PublishedValue.reset_all()
            # Call on_reset() for each device
            for device in Device.all():
                device.on_reset()
        except ImportError:
            pass  # device specs not generated yet

        # Reset all panel managers (MetaPanel re-applies saved settings, etc.)
        from enigma.panelmanager import PanelManager
        PanelManager.reset_all()

        if self.display_manager:
            self.display_manager.reload_clients()  # Tell clients to reload first
            self.display_manager.reset()  # Clear sent cache so reconnecting clients get fresh values

    def disable_all_controls(self, pushState=False):
        """Disable all controls on all devices (push state first if requested)"""
        for device in self.devices.values():
            if hasattr(device, 'handler') and device.handler and hasattr(device.handler, 'disable_all'):
                device.handler.disable_all(pushState=pushState)

    def enable_all_controls(self):
        """Restore enable masks to config defaults on all devices.

        Controls with enabled:false in their config will remain disabled.
        """
        for device in self.devices.values():
            if hasattr(device, 'handler') and device.handler:
                default_mask = getattr(device.handler, '_config_default_mask', 0xFFFF)
                device.handler.set_enable_mask(default_mask)

    def pop_all_enable_masks(self):
        """Pop enable mask stack on all devices, restoring previous state"""
        for device in self.devices.values():
            if hasattr(device, 'handler') and device.handler and hasattr(device.handler, 'pop_enable_mask'):
                device.handler.pop_enable_mask()

    def clear_all_enable_stacks(self):
        """Clear enable mask stacks on all devices without restoring state"""
        for device in self.devices.values():
            if hasattr(device, 'handler') and device.handler and hasattr(device.handler, 'clear_enable_stack'):
                device.handler.clear_enable_stack()

    def set_brightness_all(self, brightness: int):
        """Send SETBRIGHTNESS to all Enigma devices

        Args:
            brightness: 0-255
        """
        for device in self.devices.values():
            if isinstance(device, EnigmaDevice):
                device.set_brightness(brightness)

    def set_scheme_all(self, scheme_name: str):
        """Set indicator scheme on all devices that support it

        Args:
            scheme_name: Name of scheme to activate

        Returns:
            Total number of controls updated across all devices
        """
        total_count = 0

        for device in self.devices.values():
            if device.handler and hasattr(device.handler, 'set_indicator_scheme'):
                count = device.handler.set_indicator_scheme(scheme_name, "")
                total_count += count

        return total_count

    def pulse_all(self):
        """Send PULSE to all Enigma devices (white flash)"""
        for device in self.devices.values():
            if isinstance(device, EnigmaDevice):
                device.pulse()

    def set_blanking_all(self, mode: int, duration_tenths: int = 0):
        """Send SETBLANKING to all Enigma devices

        Args:
            mode: 0=off, 1=on, 2=disruption
            duration_tenths: For disruption mode, duration before full blank (0-255)
        """
        from .hid_protocol import BlankingMode

        for device in self.devices.values():
            if isinstance(device, EnigmaDevice):
                device.set_blanking(BlankingMode(mode), duration_tenths)
