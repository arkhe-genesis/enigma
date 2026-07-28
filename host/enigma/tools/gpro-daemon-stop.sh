#!/bin/bash
# SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
# SPDX-License-Identifier: MIT

# Stop G Pro keyboard daemon.
#
# The installed LaunchDaemon plist has KeepAlive=true, so simply killing
# the process makes launchd respawn it within ~1 second. This script
# bootouts the launchd registration first (which sends a clean SIGTERM
# and stops the respawn watcher), then mops up any process that survived.

PLIST_LABEL="com.halcyon.gpro-daemon"
SOCKET="/tmp/gpro_daemon.sock"

echo "Stopping G Pro daemon..."

# If launchd is currently managing the daemon, bootout removes the
# registration AND signals the running process to exit cleanly. Without
# this step, KeepAlive=true respawns the daemon every time we kill it.
if sudo launchctl print "system/${PLIST_LABEL}" >/dev/null 2>&1; then
    echo "Bootout-ing launchd job ${PLIST_LABEL}..."
    sudo launchctl bootout "system/${PLIST_LABEL}" 2>/dev/null
    sleep 0.5
fi

# Mop up any orphan (process that survived bootout, or a manually-started
# instance that launchd never knew about).
if pgrep -x enigma-gpro-daemon >/dev/null; then
    # SIGTERM first so the daemon can close HID handles (prevents IOKit lock).
    sudo pkill -TERM enigma-gpro-daemon 2>/dev/null
    sleep 1

    # Escalate to SIGKILL only if SIGTERM didn't work.
    if pgrep -x enigma-gpro-daemon >/dev/null; then
        echo "[WARN]  SIGTERM didn't work, sending SIGKILL (may lock HID devices)..."
        sudo pkill -9 enigma-gpro-daemon 2>/dev/null
        sleep 0.5
    fi
fi

if pgrep -x enigma-gpro-daemon >/dev/null; then
    echo "[FAIL] Failed to stop daemon"
    exit 1
fi

echo "[OK] Daemon stopped"

# Clean up socket.
sudo rm -f "$SOCKET" 2>/dev/null
