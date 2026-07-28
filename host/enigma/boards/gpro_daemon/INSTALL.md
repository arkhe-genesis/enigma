# G Pro Daemon: Installation & Setup Guide

This daemon provides a Unix socket interface to the Logitech G Pro keyboard for RGB control and key event forwarding.

## Prerequisites

### macOS (Homebrew)

```bash
brew install hidapi
```

### Linux (Debian/Ubuntu)

```bash
sudo apt-get install libhidapi-dev libhidapi-libusb0
```

### Linux (Fedora/RHEL)

```bash
sudo dnf install hidapi-devel
```

---

## Building

```bash
cd gpro_daemon
make
```

This creates the `gpro_daemon` executable.

---

## Running the Daemon

### Option 1: Manual Execution (Testing)

Run with sudo (needed for HID device access):

```bash
sudo ./gpro_daemon
```

The daemon will:
1. Open the G Pro keyboard (RGB and keyboard interfaces)
2. Initialize all keys to black (prevents light leakage)
3. Create socket at `/tmp/gpro_daemon.sock`
4. Wait for Python client connections

**To stop:** Press `Ctrl+C` (or `Ctrl+\` for immediate kill)

---

### Option 2: Install & Run from /usr/local/bin

```bash
make install
sudo /usr/local/bin/gpro_daemon
```

---

### Option 3: Auto-Start with launchd (macOS)

Create a launchd service that starts the daemon automatically on boot.

#### 3.1 Install the daemon

```bash
make install
```

#### 3.2 Create launchd plist

Create `/Library/LaunchDaemons/com.halcyon.gpro-daemon.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.halcyon.gpro-daemon</string>

    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/gpro_daemon</string>
    </array>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>/tmp/gpro_daemon.log</string>

    <key>StandardErrorPath</key>
    <string>/tmp/gpro_daemon.log</string>
</dict>
</plist>
```

#### 3.3 Load and start the service

```bash
sudo cp com.halcyon.gpro-daemon.plist /Library/LaunchDaemons/
sudo chown root:wheel /Library/LaunchDaemons/com.halcyon.gpro-daemon.plist
sudo chmod 644 /Library/LaunchDaemons/com.halcyon.gpro-daemon.plist
sudo launchctl load /Library/LaunchDaemons/com.halcyon.gpro-daemon.plist
```

#### 3.4 Check status

```bash
# View logs
tail -f /tmp/gpro_daemon.log

# Check if running
ps aux | grep gpro_daemon

# Stop service
sudo launchctl unload /Library/LaunchDaemons/com.halcyon.gpro-daemon.plist

# Start service
sudo launchctl load /Library/LaunchDaemons/com.halcyon.gpro-daemon.plist
```

---

### Option 4: systemd Service (Linux)

Create `/etc/systemd/system/gpro-daemon.service`:

```ini
[Unit]
Description=Logitech G Pro Keyboard Daemon
After=multi-user.target

[Service]
Type=simple
ExecStart=/usr/local/bin/gpro_daemon
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable gpro-daemon
sudo systemctl start gpro-daemon
sudo systemctl status gpro-daemon
```

View logs:

```bash
journalctl -u gpro-daemon -f
```

---

## Notes

### Restarting the Daemon

If the daemon crashes or is killed, it's safe to restart immediately. The OS automatically cleans up:
- HID device handles
- Socket connections
- Background threads

The new daemon instance will remove the old socket file and create a fresh one. Python clients will see a broken connection and can reconnect.

---

## Troubleshooting

### "No G Pro keyboard found"

- Make sure the keyboard is plugged in
- Check vendor/product ID: `lsusb | grep Logitech` (Linux) or `system_profiler SPUSBDataType` (macOS)
- If IDs differ from 046d:c339, update `GPRO_VID` and `GPRO_PID` in `gpro_daemon.c`

### "Failed to open RGB interface"

**macOS:**
- Must run with `sudo` (or via launchd as root)
- No way around this without kernel extensions

**Linux:**
- Option A: Run with `sudo`
- Option B: Create udev rule (see below)

### Permission denied on socket

The socket `/tmp/gpro_daemon.sock` has permissions `0660` (owner + group can read/write).

To allow non-root Python access:
```bash
# Add your user to the daemon's group (if needed)
# Or change socket permissions in daemon code to 0666
```

---

## Linux: udev Rules (Alternative to sudo)

Instead of running daemon as root, grant your user permission to access the HID device.

Create `/etc/udev/rules.d/99-logitech-gpro.rules`:

```bash
# Logitech G Pro Keyboard - RGB Interface
SUBSYSTEM=="usb", ATTRS{idVendor}=="046d", ATTRS{idProduct}=="c339", MODE="0666"

# Alternative: Grant access to specific group
# SUBSYSTEM=="usb", ATTRS{idVendor}=="046d", ATTRS{idProduct}=="c339", GROUP="plugdev", MODE="0660"
```

Reload udev rules:

```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Unplug and replug the keyboard, then run daemon **without** sudo:

```bash
./gpro_daemon
```

---

## Testing the Daemon

### Check if running

```bash
ls -l /tmp/gpro_daemon.sock
# Should show: srw-rw---- ... /tmp/gpro_daemon.sock
```

### Test with netcat (before Python client is ready)

```bash
# In terminal 1: Run daemon
sudo ./gpro_daemon

# In terminal 2: Connect to socket
nc -U /tmp/gpro_daemon.sock

# Type random data and press enter - daemon should forward to keyboard
# (Won't do anything visible unless you send valid RGB commands)
```

---

## Uninstall

```bash
# Stop service (if using launchd/systemd)
sudo launchctl unload /Library/LaunchDaemons/com.halcyon.gpro-daemon.plist  # macOS
sudo systemctl stop gpro-daemon  # Linux

# Remove files
make uninstall
sudo rm /Library/LaunchDaemons/com.halcyon.gpro-daemon.plist  # macOS
sudo rm /etc/systemd/system/gpro-daemon.service  # Linux
```

---

## Next Steps

Once the daemon is running, proceed to implement the Python client in `enigma/boards/gpro.py` that connects to the socket and sends RGB commands.
