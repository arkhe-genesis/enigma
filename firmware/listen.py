#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
# SPDX-License-Identifier: MIT

"""
USB Vendor Event Listener for ESP32-S3
Listens for custom vendor events from ESP32-S3 devices
"""

import usb.core
import usb.util
import usb.backend.libusb1
import time
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from enigma.colors import print_error

# Explicitly set libusb backend for macOS
backend = usb.backend.libusb1.get_backend(find_library=lambda x: "/opt/homebrew/lib/libusb-1.0.dylib")
if backend is None:
    # Try alternative path for Intel Macs
    backend = usb.backend.libusb1.get_backend(find_library=lambda x: "/usr/local/lib/libusb-1.0.dylib")
if backend is None:
    print_error("ERROR: libusb not found. Install with: brew install libusb")
    sys.exit(1)

# Espressif VID and custom temporary PID
ESPRESSIF_VID = 0x303A
CUSTOM_PID = 0x8001  # Temporary unique PID

# USB endpoint configuration
EP_IN = 0x81  # Endpoint for reading data from device

def find_devices():
    """Find all connected ESP32-S3 devices with our PID"""
    devices = usb.core.find(find_all=True, idVendor=ESPRESSIF_VID, idProduct=CUSTOM_PID, backend=backend)
    return list(devices)

def setup_device(dev):
    """Configure the USB device for communication"""
    try:
        # Detach kernel driver if active
        if dev.is_kernel_driver_active(0):
            try:
                dev.detach_kernel_driver(0)
                print("Kernel driver detached")
            except usb.core.USBError as e:
                print_error(f"Could not detach kernel driver: {e}")
        
        # Set configuration
        dev.set_configuration()
        
        # Get the interface
        cfg = dev.get_active_configuration()
        intf = cfg[(0, 0)]
        
        return True
    except usb.core.USBError as e:
        print_error(f"Error setting up device: {e}")
        return False

def read_vendor_event(dev, timeout=1000):
    """Read vendor event from the device"""
    try:
        # Read from the IN endpoint
        data = dev.read(EP_IN, 64, timeout=timeout)
        return bytes(data)
    except usb.core.USBTimeoutError:
        return None
    except usb.core.USBError as e:
        print_error(f"USB Error: {e}")
        return None

def monitor_devices():
    """Main monitoring loop"""
    print(f"Looking for ESP32-S3 devices (VID:0x{ESPRESSIF_VID:04X}, PID:0x{CUSTOM_PID:04X})...")
    
    active_devices = {}
    
    while True:
        try:
            # Find all matching devices
            current_devices = find_devices()
            current_ids = {(dev.bus, dev.address) for dev in current_devices}
            
            # Check for newly connected devices
            for dev in current_devices:
                dev_id = (dev.bus, dev.address)
                
                if dev_id not in active_devices:
                    print(f"\n[+] New device connected: Bus {dev.bus}, Address {dev.address}")
                    if setup_device(dev):
                        active_devices[dev_id] = dev
                        print(f"    Device ready for communication")
            
            # Remove disconnected devices
            for dev_id in list(active_devices.keys()):
                if dev_id not in current_ids:
                    print(f"\n[-] Device disconnected: Bus {dev_id[0]}, Address {dev_id[1]}")
                    del active_devices[dev_id]
            
            # Read events from all active devices
            for dev_id, dev in list(active_devices.items()):
                try:
                    data = read_vendor_event(dev, timeout=100)
                    if data:
                        # Decode the message
                        try:
                            message = data.decode('utf-8').rstrip('\x00')
                            print(f"[Bus {dev_id[0]}, Addr {dev_id[1]}] {message}")
                        except UnicodeDecodeError:
                            print(f"[Bus {dev_id[0]}, Addr {dev_id[1]}] Raw: {data.hex()}")
                except Exception as e:
                    # Device might have been disconnected
                    if dev_id in active_devices:
                        print_error(f"Error reading from device {dev_id}: {e}")
                        del active_devices[dev_id]
            
            time.sleep(0.01)  # Small delay to prevent CPU spinning
            
        except KeyboardInterrupt:
            print("\n\nStopping monitor...")
            break
        except Exception as e:
            print_error(f"Error in main loop: {e}")
            time.sleep(1)

if __name__ == "__main__":
    try:
        monitor_devices()
    except Exception as e:
        print_error(f"Fatal error: {e}")
        sys.exit(1)