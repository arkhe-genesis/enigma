# G Pro Keyboard Daemon

A lightweight C daemon that provides socket-based access to the Logitech G Pro keyboard's RGB control and keyboard input interfaces.

## What It Does

- Opens HID interfaces for RGB control and keyboard input (requires root/sudo)
- Initializes all keyboard LEDs to black on startup (prevents light leakage)
- Creates Unix socket at `/tmp/gpro_daemon.sock`
- Forwards RGB commands from Python -> Keyboard
- Forwards keyboard events from Keyboard -> Python (with 0xFF marker)
- Completely protocol-agnostic: just forwards raw bytes

## Files

- `gpro_daemon.c`: Main daemon source code
- `Makefile`: Build configuration
- [`INSTALL.md`](INSTALL.md): Detailed installation and setup instructions
- `com.halcyon.gpro-daemon.plist`: macOS launchd service configuration

## Quick Start

### Using Management Scripts (Recommended)

```bash
# From project root, build and install daemon
enigma/tools/gpro-daemon-build-install.sh
enigma/tools/gpro-daemon-start.sh

# Stop/restart as needed
enigma/tools/gpro-daemon-stop.sh
enigma/tools/gpro-daemon-restart.sh

# Uninstall
enigma/tools/gpro-daemon-uninstall.sh
```

### Manual Installation

```bash
# Install dependencies (macOS)
brew install hidapi

# Build
make

# Test run (keyboard will go black, press Ctrl+C to stop)
sudo ./gpro_daemon

# Install to /usr/local/bin
make install

# Set up auto-start (macOS)
sudo cp com.halcyon.gpro-daemon.plist /Library/LaunchDaemons/
sudo launchctl load /Library/LaunchDaemons/com.halcyon.gpro-daemon.plist
```

See [`INSTALL.md`](INSTALL.md) for complete instructions.

## Protocol

### Python -> Daemon (RGB Commands)
Send 64-byte packets with RGB protocol data (from `gpro_test.py`)

### Daemon -> Python (Responses)
- **RGB responses:** 64-byte packets (ACKs, etc.)
- **Key events:** `0xFF` + 8-byte HID keyboard report

## Integration

This daemon is designed to work with `enigma/boards/gpro.py`, which:
- Connects to the socket
- Sends RGB commands to control LED colors
- Receives keyboard events for input handling
