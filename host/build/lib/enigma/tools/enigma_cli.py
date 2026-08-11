#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
# SPDX-License-Identifier: MIT

"""
enigma_cli.py - Interactive command-line tool for Enigma device management

This is a thin CLI wrapper around EnigmaManager. All device management
logic lives in the manager - this just provides the interactive menu.
"""

import argparse
import signal
import time
import struct
import sys
from pathlib import Path

from enigma import EnigmaManager, ConfigManager, LogLevel, BlankingMode
from enigma.colors import print_error

#import boards  # Import to trigger registration

# Log file
log_file = None

def log_event(msg):
    """Log event to file"""
    timestamp = time.strftime('%H:%M:%S')
    line = f"[{timestamp}] {msg}\n"
    if log_file:
        log_file.write(line)
        log_file.flush()

def print_menu():
    """Print command menu"""
    print("\n" + "="*60)
    print("ENIGMA TEST COMMANDS")
    print("="*60)
    print("1. STATUS - Ping device")
    print("2. GETCONFIG - Get device configuration")
    print("3. RESET - Reset device with timebase")
    print("4. SETSTATE - Set control state")
    print("5. GETSTATE - Get control state")
    print("6. SETBRIGHTNESS - Set LED brightness")
    print("7. SETINDICATOR - Set indicator colors/animation")
    print("8. SETLOGLEVEL - Change log level")
    print("9. SETBLANKING - Turn blanking on/off")
    print("s. SetScheme - Set indicator scheme for control(s)")
    print("p. PULSE - Pulse all LEDs")
    print("l. List devices")
    print("q. Quit")
    print("="*60)
    print("\nNote: Monitor output.log in another terminal with: tail -f output.log")

def select_device(manager: EnigmaManager):
    """Prompt user to select a device"""
    devices = manager.get_all_devices()

    if not devices:
        print("No devices connected!")
        return None

    if len(devices) == 1:
        # Only one device, use it
        board_id = list(devices.keys())[0]
        return devices[board_id]

    # Multiple devices - let user choose
    print("\nAvailable devices:")
    device_list = list(devices.items())
    for i, (board_id, device) in enumerate(device_list, 1):
        config_name = device.handler.config.name if device.handler and device.handler.config else "Unknown"
        print(f"  {i}. {board_id} -> {config_name}")

    while True:
        try:
            choice = int(input("\nSelect device number: "))
            if 1 <= choice <= len(device_list):
                return device_list[choice - 1][1]
            else:
                print(f"Invalid choice. Enter 1-{len(device_list)}")
        except ValueError:
            print("Invalid input. Enter a number.")

def interactive_menu(manager: EnigmaManager, initial_log_level: int):
    """Interactive command menu"""

    # Set initial log level on all devices
    for device in manager.get_all_devices().values():
        if hasattr(device, 'set_log_level'):
            device.set_log_level(LogLevel(initial_log_level))

    while True:
        print_menu()

        choice = input("\nEnter command: ").strip().lower()

        if choice == 'q':
            print("Exiting...")
            return False

        if choice == 'l':
            # List devices
            devices = manager.get_all_devices()
            print("\nConnected devices:")
            if devices:
                for board_id, device in devices.items():
                    config_name = device.handler.config.name if device.handler and device.handler.config else "None"
                    print(f"  - {board_id} -> {config_name}")
            else:
                print("  No devices connected")
            continue

        # Commands that don't need a device
        if choice == 'p':
            # PULSE all devices
            print("Sending pulse to all devices...")
            manager.pulse_all()
            continue

        # All other commands need a device selected
        if not manager.get_all_devices():
            print("No devices connected!")
            continue

        device = select_device(manager)
        if not device:
            continue

        try:
            if choice == '1':  # STATUS
                print("Sending STATUS...")
                device.status()

            elif choice == '2':  # GETCONFIG
                print("Sending GETCONFIG...")

                def on_config(config_report, message=None):
                    if message:
                        print_error(f"Error: {message}")
                    else:
                        print(f"\nDevice Configuration:")
                        print(f"  Board: {config_report.board_type}")
                        print(f"  Protocol: v{config_report.protocol_version}")
                        print(f"  HW: v{config_report.hw_version}, SW: v{config_report.sw_version}")
                        print(f"  Variant: {config_report.variant}, Address: {config_report.address}")
                        print(f"  Config CRC: {config_report.crc32:08X}")

                device.get_config(callback=on_config)
                time.sleep(0.5)  # Wait for response

            elif choice == '3':  # RESET
                timebase_ms = int(time.time() * 1000) % 0xFFFFFFFF
                print(f"Sending RESET (timebase={timebase_ms})...")
                device.reset(timebase_ms)

                # Reset schemes
                if device.handler:
                    device.handler.reset_schemes()

            elif choice == '4':  # SETSTATE
                if not device.handler:
                    print("No handler for this board type")
                    continue

                control = int(input("Enter control number: "))

                # Board-specific state input - use ControlState objects
                if device.handler.type_str == "SW14":
                    from boards.sw14 import SW14ControlState

                    state_value = int(input("Enter state (0=off, 1=down/on, 2=up): "))
                    control_state = SW14ControlState(value=state_value)
                    device.handler.set_control_state(control, control_state)

                elif device.handler.type_str == "QD08":
                    from boards.qd08 import QD08ControlState

                    position = int(input("Enter position (0-23): "))
                    button = int(input("Button state (0/1): "))
                    control_state = QD08ControlState(position=position, button=button)
                    device.handler.set_control_state(control, control_state)

                else:
                    print(f"SETSTATE not implemented for {device.handler.type_str}")

            elif choice == '5':  # GETSTATE
                if not device.handler:
                    print("No handler for this board type")
                    continue

                control = int(input("Enter control number: "))

                def on_state(control_state, error):
                    if error:
                        print_error(f"Error: {error}")
                    else:
                        control_name = device.handler.get_control_name(control)
                        # ControlState has __str__ for nice printing
                        print(f"{control_name}: {control_state}")

                device.handler.get_control_state(control, callback=on_state)
                time.sleep(0.5)  # Wait for response

            elif choice == '6':  # SETBRIGHTNESS
                brightness = int(input("Enter brightness (0-255): "))
                device.set_brightness(brightness)

            elif choice == '7':  # SETINDICATOR
                if not device.handler:
                    print("No handler for this board type")
                    continue

                control = int(input("Enter control number: "))

                if device.handler.type_str == "SW14":
                    # SW14: 3 states with colors/animation
                    print("Enter colors for 3 states:")

                    # Import SW14 classes
                    from boards.sw14 import SW14StateConfig, MODE_SOLID, MODE_BLINK, MODE_FADE

                    indicator_data = b''
                    for i in range(3):
                        print(f"\nState {i}:")
                        colors_str = input("  Colors (e.g. '#FF0000,#00FF00'): ").strip()
                        colors = SW14StateConfig.parse_colors(colors_str)

                        mode_str = input("  Mode (solid/blink/fade): ").strip().lower()
                        mode_map = {'solid': MODE_SOLID, 'blink': MODE_BLINK, 'fade': MODE_FADE}
                        mode = mode_map.get(mode_str, MODE_SOLID)

                        period = int(input("  Period (ms): "))
                        duty = int(input("  Duty cycle (ms): "))

                        # Create state config
                        state_config = SW14StateConfig(i, report=0, value=None, colors=colors,
                                                      mode=mode_str, period_ms=period, duty_cycle_ms=duty)
                        indicator_data += state_config.to_bytes()

                    device.set_indicator(control, indicator_data)

                elif device.handler.type_str == "QD08":
                    # QD08: dial configuration
                    print("\nDial Configuration:")
                    mode = int(input("Mode (0=gradient, 1=ranged): "))

                    print("\nActive Region Rendering:")
                    print("0=brighten, 1=replace, 2=additive, 3=multiply, 4=screen, 5=alpha")
                    active_render = int(input("Active render mode: "))

                    print("\nOverlay Color (ARGB):")
                    overlay_a = int(input("  Alpha (0-255): "))
                    overlay_r = int(input("  Red (0-255): "))
                    overlay_g = int(input("  Green (0-255): "))
                    overlay_b = int(input("  Blue (0-255): "))

                    print("\nAnimation:")
                    anim_mode = int(input("Mode (0=solid, 1=blink, 2=fade): "))
                    anim_period = int(input("Period (ms): "))
                    anim_duty = int(input("Duty cycle (ms): "))

                    # Build payload (without control number - device.set_indicator adds it)
                    indicator_data = struct.pack('<BB4BBHH',
                                                mode,
                                                active_render,
                                                overlay_a, overlay_r, overlay_g, overlay_b,
                                                anim_mode,
                                                anim_period,
                                                anim_duty)

                    if mode == 0:  # Gradient
                        print("\nGradient Colors:")
                        r1 = int(input("  Start R (0-255): "))
                        g1 = int(input("  Start G (0-255): "))
                        b1 = int(input("  Start B (0-255): "))
                        r2 = int(input("  End R (0-255): "))
                        g2 = int(input("  End G (0-255): "))
                        b2 = int(input("  End B (0-255): "))

                        indicator_data += struct.pack('<3B3B', r1, g1, b1, r2, g2, b2)

                    elif mode == 1:  # Ranged
                        num_zones = int(input("\nNumber of zones (1-12): "))
                        indicator_data += struct.pack('<B', num_zones)

                        for z in range(num_zones):
                            print(f"\nZone {z+1}:")
                            threshold = int(input("  Threshold LED (1-based): "))
                            r = int(input("  R (0-255): "))
                            g = int(input("  G (0-255): "))
                            b = int(input("  B (0-255): "))
                            indicator_data += struct.pack('<B3B', threshold, r, g, b)

                    device.set_indicator(control, indicator_data)

                else:
                    print(f"SETINDICATOR not implemented for {device.handler.type_str}")

            elif choice == '8':  # SETLOGLEVEL
                print("0=ERROR, 1=WARNING, 2=INFO, 3=DEBUG")
                level = int(input("Enter log level: "))
                device.set_log_level(LogLevel(level))

            elif choice == '9':  # SETBLANKING
                print("Blanking modes:")
                print("  0 = Off (normal operation)")
                print("  1 = On (all LEDs off)")
                print("  2 = Disruption (escalating chaos)")
                mode = int(input("Enter blanking mode (0-2): "))

                duration = 0
                if mode == 2:  # BLANKING_DISRUPTION
                    duration = int(input("Enter disruption duration (tenths of seconds, 1-255): "))

                device.set_blanking(BlankingMode(mode), duration)

            elif choice == 's':  # SETSCHEME
                if not device.handler:
                    print("No handler for this board type")
                    continue

                if not hasattr(device.handler, 'set_indicator_scheme'):
                    print(f"Board type {device.handler.type_str} does not support schemes")
                    continue

                # Show available controls (deduplicated by name)
                if device.handler.config:
                    print("\nAvailable controls:")
                    name_to_schemes = {}  # name -> set of schemes

                    for ctrl_num, ctrl in sorted(device.handler.config.controls.items()):
                        if ctrl.name not in name_to_schemes:
                            name_to_schemes[ctrl.name] = set(['default'])

                        # Add schemes from this control
                        if hasattr(ctrl, 'schemes') and ctrl.schemes:
                            name_to_schemes[ctrl.name].update(ctrl.schemes.keys())

                    # Display
                    for name in sorted(name_to_schemes.keys()):
                        schemes = sorted(name_to_schemes[name])
                        schemes_str = ", ".join(schemes)
                        print(f"  {name} (schemes: {schemes_str})")

                control_name = input("\nEnter control name (or blank for all): ").strip()

                # Gather available schemes for selected control(s)
                available_schemes = set(['default'])
                if control_name == "":
                    # All controls
                    for ctrl in device.handler.config.controls.values():
                        if hasattr(ctrl, 'schemes') and ctrl.schemes:
                            available_schemes.update(ctrl.schemes.keys())
                else:
                    # Specific control name
                    for ctrl in device.handler.config.controls.values():
                        if ctrl.name == control_name:
                            if hasattr(ctrl, 'schemes') and ctrl.schemes:
                                available_schemes.update(ctrl.schemes.keys())

                schemes_list = ", ".join(sorted(available_schemes))
                scheme_name = input(f"Enter scheme name ({schemes_list}) [default]: ").strip() or "default"

                count = device.handler.set_indicator_scheme(scheme_name, control_name)
                print(f"Updated {count} control(s) to scheme '{scheme_name}'")

            else:
                print("Invalid choice")

        except ValueError as e:
            print(f"Invalid input: {e}")
        except Exception as e:
            print_error(f"Error: {e}")
            import traceback
            traceback.print_exc()

def main():
    global log_file

    # Route Ctrl-\ through KeyboardInterrupt instead of SIGQUIT's default core
    # dump, which triggers macOS's crash dialog (see hd.py).
    signal.signal(signal.SIGQUIT, signal.default_int_handler)

    parser = argparse.ArgumentParser(description='Enigma HID Device Manager')
    parser.add_argument('--log-level', type=str, default='debug',
                       choices=['error', 'warning', 'info', 'debug'],
                       help='Initial log level to set on devices')
    parser.add_argument('--config-dir', type=str, default='./configs',
                       help='Directory containing configuration files')
    parser.add_argument('--wire', action='store_true',
                       help='Show raw HID TX/RX packets for debugging')
    args = parser.parse_args()

    log_level_map = {
        'error': LogLevel.ERROR,
        'warning': LogLevel.WARNING,
        'info': LogLevel.INFO,
        'debug': LogLevel.DEBUG
    }
    initial_log_level = log_level_map[args.log_level]

    # Open log file
    log_file = open('output.log', 'a')
    log_event("="*60)
    log_event("ENIGMA INTERACTIVE TEST")
    log_event("="*60)
    log_event(f"Initial log level: {args.log_level.upper()}")
    log_event(f"Config directory: {args.config_dir}")

    print("="*60)
    print("ENIGMA INTERACTIVE TEST")
    print("="*60)
    print(f"Logging to: output.log (use 'tail -f output.log' to monitor)")
    print(f"Config directory: {args.config_dir}")

    # Create config manager
    config_manager = ConfigManager(Path(args.config_dir))

    # Create and start device manager
    manager = EnigmaManager(config_manager, debug_wire=args.wire)

    # Set up logging callback
    manager.on_log_message = lambda dev, level, msg: log_event(f"[{dev.get_board_id()}] {msg}")

    manager.start()

    print("\nScanning for devices...")
    time.sleep(2)  # Give it time to find devices

    devices = manager.get_all_devices()
    if devices:
        print(f"Found {len(devices)} device(s)")
        for board_id in devices:
            print(f"  - {board_id}")
    else:
        print("No devices found yet. They will appear when connected.")

    # Run interactive menu
    try:
        interactive_menu(manager, initial_log_level)
    except KeyboardInterrupt:
        print("\n\nInterrupted...")
    finally:
        manager.stop()

        if log_file:
            log_file.close()

if __name__ == '__main__':
    main()
