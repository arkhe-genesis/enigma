#!/bin/bash
# SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
# SPDX-License-Identifier: MIT

# Build and install G Pro keyboard daemon, plus the LaunchDaemon plist
# that makes it auto-start at boot and respawn on crash.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DAEMON_DIR="$SCRIPT_DIR/../boards/gpro_daemon"
BINARY_DST="/usr/local/bin/enigma-gpro-daemon"
PLIST_LABEL="com.halcyon.gpro-daemon"
PLIST_SRC="$DAEMON_DIR/${PLIST_LABEL}.plist"
PLIST_DST="/Library/LaunchDaemons/${PLIST_LABEL}.plist"

echo "=== G Pro Daemon Installation ==="
echo

# Check for hidapi (don't auto-install to avoid sudo/brew conflict).
if ! brew list hidapi &>/dev/null; then
    echo "[FAIL] hidapi not found. Please install it first:"
    echo "   brew install hidapi"
    exit 1
fi

# Stop any running daemon BEFORE overwriting the binary on disk -
# otherwise the running process keeps the old text mapped and the next
# launchd respawn might be confused. Also avoids a fight over the HID
# device during the install window.
if pgrep -x enigma-gpro-daemon >/dev/null || \
   sudo launchctl print "system/${PLIST_LABEL}" >/dev/null 2>&1; then
    echo "Stopping currently-running daemon..."
    "$SCRIPT_DIR/gpro-daemon-stop.sh"
    echo
fi

# Build.
echo "Building daemon..."
cd "$DAEMON_DIR"
make

# Install binary.
echo "Installing binary to ${BINARY_DST}..."
echo "(need root access to install system files)"
sudo make install

# LaunchDaemon registration is DISABLED on modern macOS: launchctl
# bootstrap refuses to load LaunchDaemons whose binary isn't signed
# with a real Developer ID and notarized by Apple, returning
# "Bootstrap failed: 5: Input/output error" before the daemon ever
# executes. spctl's per-binary --add exemption was removed by Apple,
# and we don't want to disable Gatekeeper system-wide.
#
# Until the daemon binary has proper Developer ID signing + notarization,
# we skip the plist install and rely on gpro-daemon-start.sh's
# direct-spawn fallback (sudo nohup). Trade-off: no KeepAlive
# auto-restart on crash, no RunAtLoad start-at-boot - the daemon must
# be started manually each session.
#
# If a stale plist exists from a previous install, remove it so the
# start script's "plist absent" branch fires cleanly.
if [ -f "$PLIST_DST" ]; then
    echo "Removing stale LaunchDaemon plist at ${PLIST_DST}..."
    echo "  (launchd would reject it as un-notarized - see comments in this script)"
    sudo rm -f "$PLIST_DST"
fi
echo "Skipping LaunchDaemon registration (un-notarized binary)."
echo "  Daemon will be started directly by gpro-daemon-start.sh."

echo
echo "[OK] Build + install complete."
echo
echo "Starting daemon..."
echo
"$SCRIPT_DIR/gpro-daemon-start.sh"
