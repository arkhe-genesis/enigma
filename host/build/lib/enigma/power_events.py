# SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
# SPDX-License-Identifier: MIT

"""
Power-event listeners for the EnigmaManager.

When the host machine sleeps and wakes, USB-HID handles tend to go orphan:
the OS keeps the IOKit/HID registry path stable, hidapi reports the device
as still enumerable, reads silently return "no data," writes appear to
succeed. The application thinks everything is fine while in fact no bytes
reach the device. The only deterministic fix is to drop and reopen all
HID handles on wake.

This module provides a small interface and a default macOS implementation:

    listener = make_default_listener(on_wake_callback)
    if listener is not None:
        listener.start()
    ...
    listener.stop()

`on_wake_callback` is invoked from a background thread on every wake
event. It should be cheap and thread-safe - typically setting a flag that
the main poll loop reads at the top of its next iteration.

Non-macOS platforms currently get a None listener (no-op). If you need
sleep/wake handling on Windows or Linux, write a class that implements
the same start/stop/on_wake contract and pass it to EnigmaManager via
the `power_event_listener=` constructor argument.
"""

from __future__ import annotations

import sys
import threading
from typing import Callable, Optional


class _NullListener:
    """Listener that does nothing. Returned on platforms without a built-in
    implementation, so callers can unconditionally call .start()/.stop()."""
    def start(self) -> None: pass
    def stop(self) -> None: pass


class IOKitPowerEventListener:
    """macOS sleep/wake listener via IOKit's IORegisterForSystemPower.

    Runs a CFRunLoop on a background daemon thread. On wake (and on
    will-sleep, which we forward as a wake too - the next poll will close
    handles either way) the constructor-provided callback fires.

    All ctypes loading happens at instantiation, so importing this module
    on a non-Darwin platform doesn't pay any IOKit cost.
    """

    # Documented in IOMessage.h. We pin them here so we don't depend on
    # any header parsing - these constants are part of the macOS ABI.
    _kIOMessageCanSystemSleep      = 0x280
    _kIOMessageSystemWillSleep     = 0x280  # alias - same code
    _kIOMessageSystemHasPoweredOn  = 0x300
    # Both messages above carry the high 16 bits 0xE000. The mask we
    # actually compare against:
    _kIOMessageCanSystemSleepFull       = 0xE0000270
    _kIOMessageSystemWillSleepFull      = 0xE0000280
    _kIOMessageSystemHasPoweredOnFull   = 0xE0000300

    def __init__(self, on_wake: Callable[[], None]) -> None:
        if sys.platform != 'darwin':
            raise RuntimeError("IOKitPowerEventListener requires macOS")

        import ctypes
        import ctypes.util

        iokit_path = ctypes.util.find_library('IOKit')
        cf_path    = ctypes.util.find_library('CoreFoundation')
        if not iokit_path or not cf_path:
            raise RuntimeError("Could not locate IOKit / CoreFoundation frameworks")

        self._ctypes = ctypes
        self._iokit = ctypes.CDLL(iokit_path)
        self._cf    = ctypes.CDLL(cf_path)
        self._on_wake = on_wake

        # Opaque types - represented as void* (c_void_p) on both arch.
        self._io_object_t              = ctypes.c_uint
        self._io_connect_t             = ctypes.c_uint
        self._IONotificationPortRef    = ctypes.c_void_p
        self._CFRunLoopRef             = ctypes.c_void_p
        self._CFRunLoopSourceRef       = ctypes.c_void_p
        self._CFStringRef              = ctypes.c_void_p

        # void (*IOServiceInterestCallback)(void *refcon, io_service_t service,
        #                                   uint32_t messageType, void *messageArgument)
        self._CallbackType = ctypes.CFUNCTYPE(
            None,
            ctypes.c_void_p,         # refcon
            self._io_object_t,       # service
            ctypes.c_uint32,         # messageType
            ctypes.c_void_p,         # messageArgument
        )

        # Function prototypes
        self._iokit.IORegisterForSystemPower.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(self._IONotificationPortRef),
            self._CallbackType,
            ctypes.POINTER(self._io_object_t),
        ]
        self._iokit.IORegisterForSystemPower.restype = self._io_connect_t

        self._iokit.IONotificationPortGetRunLoopSource.argtypes = [self._IONotificationPortRef]
        self._iokit.IONotificationPortGetRunLoopSource.restype  = self._CFRunLoopSourceRef

        self._iokit.IOAllowPowerChange.argtypes = [self._io_connect_t, ctypes.c_long]
        self._iokit.IOAllowPowerChange.restype  = ctypes.c_int

        self._cf.CFRunLoopGetCurrent.argtypes = []
        self._cf.CFRunLoopGetCurrent.restype  = self._CFRunLoopRef

        self._cf.CFRunLoopAddSource.argtypes = [
            self._CFRunLoopRef, self._CFRunLoopSourceRef, self._CFStringRef]
        self._cf.CFRunLoopAddSource.restype = None

        self._cf.CFRunLoopRun.argtypes = []
        self._cf.CFRunLoopRun.restype  = None

        self._cf.CFRunLoopStop.argtypes = [self._CFRunLoopRef]
        self._cf.CFRunLoopStop.restype  = None

        # kCFRunLoopCommonModes is an exported CFStringRef constant.
        self._kCFRunLoopCommonModes = ctypes.c_void_p.in_dll(
            self._cf, "kCFRunLoopCommonModes")

        # Runtime state (populated in _run on the worker thread)
        self._thread: Optional[threading.Thread] = None
        self._runloop_ref: Optional[int] = None
        self._root_port: int = 0
        # Keep a strong ref to the CFUNCTYPE wrapper - if it's GC'd while
        # the runloop is still alive, IOKit will call into freed memory.
        self._cb_holder = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name='enigma-power-monitor', daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._runloop_ref:
            self._cf.CFRunLoopStop(self._runloop_ref)

    def _run(self) -> None:
        ctypes = self._ctypes
        try:
            port_ref  = self._IONotificationPortRef()
            notifier  = self._io_object_t()

            def _callback(refcon, service, message_type, message_argument):
                # Both will-sleep and powered-on need the application to
                # treat its HID state as suspect. We acknowledge sleep
                # so the OS actually goes down, and forward both edges
                # to the user callback - invalidate_all is idempotent.
                try:
                    if message_type == self._kIOMessageCanSystemSleepFull:
                        self._iokit.IOAllowPowerChange(
                            self._root_port, message_argument or 0)
                    elif message_type == self._kIOMessageSystemWillSleepFull:
                        self._iokit.IOAllowPowerChange(
                            self._root_port, message_argument or 0)
                        self._on_wake()
                    elif message_type == self._kIOMessageSystemHasPoweredOnFull:
                        self._on_wake()
                except Exception:
                    import traceback
                    traceback.print_exc()

            cb_cf = self._CallbackType(_callback)
            self._cb_holder = cb_cf   # keep alive

            self._root_port = self._iokit.IORegisterForSystemPower(
                None, ctypes.byref(port_ref), cb_cf, ctypes.byref(notifier))
            if not self._root_port:
                print("[enigma] IORegisterForSystemPower failed; "
                      "sleep/wake HID reset disabled", file=sys.stderr)
                return

            source = self._iokit.IONotificationPortGetRunLoopSource(port_ref)
            self._runloop_ref = self._cf.CFRunLoopGetCurrent()
            self._cf.CFRunLoopAddSource(
                self._runloop_ref, source, self._kCFRunLoopCommonModes)

            # Blocks until CFRunLoopStop is called from another thread.
            self._cf.CFRunLoopRun()
        except Exception:
            import traceback
            traceback.print_exc()


def make_default_listener(on_wake: Callable[[], None]):
    """Return a power-event listener appropriate to the host platform, or
    None if no built-in is available. Caller may pass None straight back
    to start()/stop()-style code after a `if listener is not None` check,
    or use the no-op _NullListener if it's annoying to special-case None.

    Override this entirely by passing your own listener to
    EnigmaManager(power_event_listener=...) - anything with start() and
    stop() methods is fine; the listener is responsible for calling
    on_wake from whatever thread it likes.
    """
    if sys.platform == 'darwin':
        try:
            return IOKitPowerEventListener(on_wake)
        except (OSError, RuntimeError) as e:
            print(f"[enigma] Power-event listener unavailable: {e}", file=sys.stderr)
            return None
    return None
