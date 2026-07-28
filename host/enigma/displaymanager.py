# SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
# SPDX-License-Identifier: MIT

"""
enigma.displaymanager - WebSocket publishing to remote displays

Uses python-socketio for persistent connections with auto-reconnect.
Runs in a dedicated background thread with its own event loop.
"""

import asyncio
import json
import threading
import queue
from pathlib import Path
from typing import Dict, List, Optional, Any
import traceback

from enigma.colors import print_error


def get_socketio():
    """Lazy import socketio"""
    try:
        import socketio
        return socketio
    except ImportError:
        print_error("[enigma] ERROR: python-socketio not installed. Install with: pip install python-socketio[asyncio_client]")
        return None


class DisplayPublisher:
    """Publishes attribute changes to a single remote display via WebSocket"""

    def __init__(self, name: str, url: str, heartbeat_url: Optional[str], published_attrs: List[str]):
        self.name = name
        # Convert HTTP URL to WebSocket base URL
        self.url = url.replace('/update', '').rstrip('/')
        self.published_attrs = published_attrs
        self._last_sent = {}
        self._is_connected = False
        self._sio = None
        self._first_publish = True
        self._connecting = False
        self._connection_error_printed = False
        self._emit_error_printed = False
        self._last_connect_attempt = 0
        self._handlers: Dict[str, List] = {}  # event_name -> [callback, ...]

    def add_handler(self, event_name: str, callback) -> None:
        """Register a callback for an incoming event emitted by this display.
        Must be called before the background thread starts (before start()).
        The callback is invoked on the background thread - keep it thread-safe."""
        self._handlers.setdefault(event_name, []).append(callback)

    async def start(self):
        """Initialize WebSocket connection"""
        socketio = get_socketio()
        if not socketio:
            return

        kwargs = dict(
            reconnection=False,  # We handle retry ourselves in check_and_publish
            logger=False,
            engineio_logger=False,
        )
        self._sio = socketio.AsyncClient(**kwargs)

        @self._sio.event
        async def connect():
            self._is_connected = True
            self._first_publish = True  # Resend everything on reconnect
            self._connection_error_printed = False  # Reset so future errors are reported
            self._emit_error_printed = False
            print(f"[enigma] [Display {self.name}] Connected to {self.url}")

        @self._sio.event
        async def disconnect():
            self._is_connected = False
            print_error(f"[enigma] [Display {self.name}] Disconnected from {self.url}")

        # Catch-all handler for display->Python events.
        # Reads _handlers at call time so add_handler() works at any point.
        _self = self

        @self._sio.on('*')
        async def _on_any_event(event, data):
            for h in _self._handlers.get(event, []):
                try:
                    h(data)
                except Exception as exc:
                    print_error(f"[enigma] [Display {_self.name}] Handler error for '{event}': {exc}")

        # Start connection in background
        asyncio.create_task(self._connect())

    async def _connect(self):
        """Connect to server with timeout"""
        if self._connecting or self._is_connected:
            return
        self._connecting = True
        try:
            await asyncio.wait_for(
                self._sio.connect(self.url, transports=['websocket']),
                timeout=5.0
            )
        except asyncio.TimeoutError:
            if not self._connection_error_printed:
                print_error(f"[enigma] [Display {self.name}] Connection timed out (retrying silently)")
                self._connection_error_printed = True
        except Exception as e:
            if not self._connection_error_printed:
                print_error(f"[enigma] [Display {self.name}] Connection failed: {e} (retrying silently)")
                self._connection_error_printed = True
        finally:
            self._connecting = False

    async def check_and_publish(self):
        """Check for attribute changes and publish via WebSocket"""
        if not self._sio:
            return

        # Retry connection if not connected, with 2s cooldown between attempts
        if not self._sio.connected and not self._connecting:
            now = asyncio.get_event_loop().time()
            if now - self._last_connect_attempt >= 2.0:
                self._last_connect_attempt = now
                asyncio.create_task(self._connect())
            return

        # Don't try to emit if not actually connected yet
        if not self._sio.connected:
            return

        try:
            from generated import devices
        except ImportError:
            return

        changes = {}
        for attr_path in self.published_attrs:
            try:
                device_name, attr_name = attr_path.split('.')
                device = getattr(devices, device_name)
                current = getattr(device, attr_name)

                # Convert to JSON-serializable
                if not isinstance(current, (int, float, bool, str, type(None))):
                    current = str(current)

                # Check if changed
                if self._first_publish or attr_path not in self._last_sent or self._last_sent[attr_path] != current:
                    changes[attr_path] = current

            except Exception as e:
                import traceback
                print_error(f"[enigma] [Display {self.name}] Error reading {attr_path}: {e}")
                traceback.print_exc()

        # Send if we have changes
        if changes:
            self._last_sent.update(changes)
            self._first_publish = False
            try:
                await self._sio.emit('host_update', changes)
                self._emit_error_printed = False  # Reset on success
            except Exception as e:
                if not self._emit_error_printed:
                    print_error(f"[enigma] [Display {self.name}] Emit failed: {e} (retrying silently)")
                    self._emit_error_printed = True

    async def emit_reload(self):
        """Tell the client to reload the page"""
        if self._sio and self._sio.connected:
            try:
                await self._sio.emit('reload')
                print(f"[enigma] [Display {self.name}] Sent reload command")
            except Exception as e:
                print_error(f"[enigma] [Display {self.name}] Failed to send reload: {e}")

    async def stop(self):
        """Disconnect"""
        if self._sio and self._sio.connected:
            await self._sio.disconnect()


class DisplayManager:
    """Manages WebSocket publishing using a dedicated background thread"""
    
    _instance: Optional['DisplayManager'] = None
    
    def __init__(self, config_dir: Path):
        self.config_dir = Path(config_dir)
        self.displays: Dict[str, DisplayPublisher] = {}
        self._command_queue = queue.Queue()
        self._thread = None
        self._running = False
        
        # Load configurations
        self._load_configs()
        
        # Start background thread
        if self.displays:
            self._start_thread()
        
        DisplayManager._instance = self
    
    def _start_thread(self):
        """Start background thread with event loop"""
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
    
    def _run_loop(self):
        """Background thread main loop"""
        # Create event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            loop.run_until_complete(self._async_main())
        finally:
            loop.close()
    
    async def _async_main(self):
        """Main async coroutine running in background thread"""
        socketio = get_socketio()
        if not socketio:
            return

        # Initialize all displays (each manages its own WebSocket connection)
        for display in self.displays.values():
            await display.start()

        print(f"[enigma] [DisplayManager] Background thread started with {len(self.displays)} displays")

        # Main loop - poll for changes at fixed rate
        while self._running:
            # Check for stop/reset/reload commands
            try:
                cmd = self._command_queue.get_nowait()
                if cmd == 'stop':
                    break
                elif cmd == 'reset':
                    for display in self.displays.values():
                        display._last_sent.clear()
                        display._first_publish = True
                elif cmd == 'reload':
                    await asyncio.gather(*[display.emit_reload() for display in self.displays.values()])
            except queue.Empty:
                pass

            # Check and publish all displays
            await asyncio.gather(*[display.check_and_publish() for display in self.displays.values()])

            # Target ~20Hz update rate
            await asyncio.sleep(0.05)

        # Cleanup
        for display in self.displays.values():
            await display.stop()
    
    def update(self):
        """Queue an update request (called from main thread)"""
        if self._running:
            self._command_queue.put('update')

    def reset(self):
        """Reset display state - clears last sent values to force full refresh"""
        for display in self.displays.values():
            display._last_sent.clear()
        # Queue an update to send fresh values
        self.update()

    def reload_clients(self):
        """Tell all connected display clients to reload their page"""
        if self._running:
            self._command_queue.put('reload')

    def stop(self):
        """Stop the background thread"""
        if self._running:
            self._running = False
            self._command_queue.put('stop')
            if self._thread:
                self._thread.join(timeout=2.0)
    
    def _load_configs(self):
        """Load display configurations"""
        mappings_file = self.config_dir / "display_mappings.json"
        
        if not mappings_file.exists():
            return
        
        try:
            with open(mappings_file, 'r') as f:
                mappings = json.load(f)
        except Exception as e:
            print_error(f"[enigma] ERROR loading display mappings: {e}")
            return
        
        print(f"[enigma] Loading {len(mappings)} display configurations")
        
        for display_name, config_file in mappings.items():
            config_path = self.config_dir / config_file
            display = self._load_display_config(display_name, config_path)
            if display:
                self.displays[display_name] = display
                print(f"[enigma]   Registered display: {display_name} -> {display.url}")
    
    def _load_display_config(self, display_name: str, config_path: Path) -> Optional[DisplayPublisher]:
        """Load a single display configuration"""
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
            
            url = config.get('URL')
            heartbeat_url = config.get('HeartBeatURL')
            publish = config.get('Publish', [])
            
            if not url or not publish:
                print_error(f"[enigma] ERROR: {config_path}: Missing URL or Publish")
                return None
            
            # Validate attributes
            valid_attrs = [attr for attr in publish if self._validate_attribute(attr, config_path)]
            
            if not valid_attrs:
                return None
            
            return DisplayPublisher(display_name, url, heartbeat_url, valid_attrs)
            
        except Exception as e:
            print_error(f"[enigma] ERROR loading {config_path}: {e}")
            return None
    
    def _validate_attribute(self, attr_path: str, config_path: Path) -> bool:
        """Validate attribute exists"""
        parts = attr_path.split('.')
        if len(parts) != 2:
            print_error(f"[enigma] ERROR: {config_path}: '{attr_path}' must be 'Device.Attribute'")
            return False

        try:
            from generated import devices
            device_name, attr_name = parts

            if not hasattr(devices, device_name):
                print_error(f"[enigma] ERROR: {config_path}: Device '{device_name}' not found")
                print(f"[enigma]   Available devices: {[a for a in dir(devices) if not a.startswith('_')]}")
                return False

            device = getattr(devices, device_name)
            if not hasattr(device, attr_name):
                print_error(f"[enigma] ERROR: {config_path}: Attribute '{attr_name}' not found on {device_name}")
                print(f"[enigma]   Available: {[a for a in dir(device) if not a.startswith('_')]}")
                return False

            return True
        except ImportError:
            return True
        
    def register_handler(self, display_name: str, event_name: str, callback) -> None:
        """Register a callback for incoming events emitted by a named display.
        Must be called before the background thread starts processing events.
        callback(data) is invoked on the background thread - must be thread-safe."""
        display = self.displays.get(display_name)
        if display is None:
            print_error(f"[enigma] [DisplayManager] register_handler: display '{display_name}' not found")
            return
        display.add_handler(event_name, callback)

    @classmethod
    def get_instance(cls):
        return cls._instance
