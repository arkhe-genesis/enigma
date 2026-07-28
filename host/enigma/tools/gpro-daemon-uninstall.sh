#!/bin/bash
# SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
# SPDX-License-Identifier: MIT

# Uninstall G Pro keyboard daemon

PLIST="/Library/LaunchDaemons/com.halcyon.gpro-daemon.plist"
BINARY="/usr/local/bin/enigma-gpro-daemon"
SOCKET="/tmp/gpro_daemon.sock"

echo "=== G Pro Daemon Uninstallation ==="
echo
echo "(need root access to remove system files)"

# Stop daemon if running
if [ -f "$PLIST" ]; then
    echo "Stopping daemon..."
    sudo launchctl unload "$PLIST" 2>/dev/null || echo "  (not running)"
fi

# Remove launchd plist
if [ -f "$PLIST" ]; then
    echo "Removing launchd service..."
    sudo rm "$PLIST"
    echo "  [OK] Removed $PLIST"
else
    echo "  (launchd service not found)"
fi

# Remove binary
if [ -f "$BINARY" ]; then
    echo "Removing daemon binary..."
    sudo rm "$BINARY"
    echo "  [OK] Removed $BINARY"
else
    echo "  (daemon binary not found)"
fi

# Also remove old binary name if it exists
if [ -f "/usr/local/bin/gpro_daemon" ]; then
    echo "Removing old daemon binary..."
    sudo rm "/usr/local/bin/gpro_daemon"
    echo "  [OK] Removed /usr/local/bin/gpro_daemon"
fi

# Clean up socket if present
if [ -S "$SOCKET" ]; then
    echo "Cleaning up socket..."
    sudo rm "$SOCKET"
    echo "  [OK] Removed $SOCKET"
fi

echo
echo "[OK] Uninstallation complete!"
