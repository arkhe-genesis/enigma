#!/bin/bash
# SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
# SPDX-License-Identifier: MIT

# Start G Pro keyboard daemon.
#
# Two modes:
#   - LaunchDaemon installed: bootstrap (or kickstart) via launchctl so
#     launchd manages the lifetime. KeepAlive=true in the plist means the
#     daemon will auto-restart on crash.
#   - Plist absent: spawn directly with sudo nohup as the legacy path.
#
# After startup, we verify BOTH the IPC socket appeared AND the HID open
# succeeded - the daemon will happily create a socket even when HID open
# fails, so socket-existence alone isn't a sufficient success indicator.

DAEMON="/usr/local/bin/enigma-gpro-daemon"
SOCKET="/tmp/gpro_daemon.sock"
LOG="/tmp/gpro_daemon.log"
PLIST_LABEL="com.halcyon.gpro-daemon"
PLIST_PATH="/Library/LaunchDaemons/${PLIST_LABEL}.plist"

if [ ! -f "$DAEMON" ]; then
    echo "[FAIL] Daemon not installed. Run gpro-daemon-build-install.sh first."
    exit 1
fi

# Already running? Don't try to spawn a sibling.
if pgrep -x enigma-gpro-daemon >/dev/null; then
    echo "[WARN]  Daemon already running."
    echo "    If HID appears locked, recycle with gpro-daemon-restart.sh"
    exit 0
fi

# Clean up stale socket if it exists.
if [ -S "$SOCKET" ]; then
    echo "Cleaning up stale socket..."
    sudo rm -f "$SOCKET"
fi

# Snapshot log length so we only inspect lines emitted after THIS start.
LOG_BEFORE=0
[ -f "$LOG" ] && LOG_BEFORE=$(wc -l < "$LOG")

# Prefer launchd when the plist is installed.
if [ -f "$PLIST_PATH" ]; then
    if sudo launchctl print "system/${PLIST_LABEL}" >/dev/null 2>&1; then
        echo "Kickstarting launchd job ${PLIST_LABEL}..."
        sudo launchctl kickstart -k "system/${PLIST_LABEL}"
    else
        echo "Bootstrapping launchd job from ${PLIST_PATH}..."
        sudo launchctl bootstrap system "$PLIST_PATH"
    fi
else
    echo "Starting G Pro daemon..."
    echo "(need root access to access HID devices)"
    sudo sh -c "nohup $DAEMON >> $LOG 2>&1 &"
fi

# Give it a moment to open the socket + HID device.
sleep 1

# Verify BOTH socket presence AND no HID failure in the just-emitted log
# lines. The daemon creates the socket on the IPC layer's startup, which
# runs independently of HID open - so socket-alive != HID-alive.
SOCKET_OK=false
HID_OK=true
[ -S "$SOCKET" ] && SOCKET_OK=true

NEW_LOG=$(tail -n +$((LOG_BEFORE + 1)) "$LOG" 2>/dev/null || true)
if echo "$NEW_LOG" | grep -qE 'Failed|hid_open_path|exclusive access'; then
    HID_OK=false
fi

if $SOCKET_OK && $HID_OK; then
    echo "[OK] Daemon started (socket + HID OK)"
elif $SOCKET_OK; then
    echo "[WARN]  Daemon running but HID failed to open."
    echo "    Last log lines:"
    echo "$NEW_LOG" | sed 's/^/      /'
    echo ""
    echo "    Another process is holding the device. Check:"
    echo "      ps -ax | grep enigma-gpro-daemon | grep -v grep"
    echo "      ps -axo pid,user,command | grep -iE 'python|hd\\.py'"
    echo "    Then physically unplug + replug the pedalboard if needed."
    exit 1
else
    echo "[FAIL] Daemon failed to start (no socket)."
    echo "    Check logs: tail -f $LOG"
    exit 1
fi
