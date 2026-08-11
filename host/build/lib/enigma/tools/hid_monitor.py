#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
# SPDX-License-Identifier: MIT

"""
hid_monitor.py - Raw HID monitor for Enigma and Thrustmaster devices.

Listens for devices to connect/disconnect and prints all raw control
reports as they arrive. No board configs or game state are loaded.

Usage:
    python enigma/tools/hid_monitor.py [--voltage]
"""

import sys
import time
import signal
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from enigma import EnigmaManager, ConfigManager

VOLTAGE_MODE = False


def _device_label(device, board_id):
    """Format identifier for output: 'SW14-13 (WeaponsControl)' when the
    handler's config is loaded, otherwise just the bare board id."""
    if hasattr(device, 'handler') and device.handler and device.handler.config:
        name = getattr(device.handler.config, 'name', None)
        if name and name != 'Unknown':
            return f"{board_id} ({name})"
    return board_id


def on_connected(board_id, device):
    board_type = getattr(device, 'board_type', 'unknown')
    print(f"[+] Connected:    {_device_label(device, board_id)}  (type={board_type})")
    if hasattr(device, 'handler') and device.handler:
        device.handler.set_enable_mask(0xFFFF)
        print(f"    Sent enable-all to {_device_label(device, board_id)}")


def on_disconnected(board_id):
    print(f"[-] Disconnected: {board_id}")


def on_state_change(device, control_num, state_data):
    board_id = device.get_board_id() if hasattr(device, 'get_board_id') else str(device)
    label = _device_label(device, board_id)

    cfg = None
    if hasattr(device, 'handler') and device.handler and device.handler.config:
        cfg = device.handler.config.controls.get(control_num)
    ctrl_name = getattr(cfg, 'name', None) if cfg is not None else None
    ctrl_str = f"ctrl={control_num:3d}" + (f" ({ctrl_name})" if ctrl_name else "")

    if VOLTAGE_MODE and isinstance(state_data, (bytes, bytearray)) and len(state_data) >= 2:
        if cfg is not None and hasattr(cfg, 'sensor_min_v') and hasattr(cfg, 'sensor_max_v'):
            raw = int.from_bytes(state_data[:2], 'little')
            norm = raw / 1023.0
            voltage = cfg.sensor_min_v + norm * (cfg.sensor_max_v - cfg.sensor_min_v)
            print(f"    {label}  {ctrl_str}  {state_data[:2].hex()}  ({raw:4d}, ~{voltage:.2f}V)")
            return

    hex_data = state_data.hex() if isinstance(state_data, (bytes, bytearray)) else repr(state_data)
    print(f"    {label}  {ctrl_str}  {hex_data}")


def main():
    # Route Ctrl-\ through KeyboardInterrupt instead of SIGQUIT's default core
    # dump, which triggers macOS's crash dialog (see hd.py).
    signal.signal(signal.SIGQUIT, signal.default_int_handler)

    parser = argparse.ArgumentParser(description="Raw HID monitor for Enigma and Thrustmaster devices")
    parser.add_argument('--voltage', action='store_true',
                        help='For analog (AN08) channels, decode the post-pipeline value back to '
                             'sensor voltage using the channel\'s configured sensor_min_v/sensor_max_v')
    args = parser.parse_args()

    global VOLTAGE_MODE
    VOLTAGE_MODE = args.voltage

    config_manager = ConfigManager(Path('configs'))
    manager = EnigmaManager(config_manager)

    manager.on_device_connected = on_connected
    manager.on_device_disconnected = on_disconnected
    manager.on_state_change = on_state_change

    manager.start()
    print("HID monitor running - plug/unplug devices, press Ctrl+C to stop\n")

    def shutdown(sig, frame):
        print("\nStopping...")
        manager.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)

    while True:
        manager.update()
        time.sleep(0.01)


if __name__ == '__main__':
    main()
