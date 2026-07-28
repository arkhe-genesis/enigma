#!/bin/bash
# SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
# SPDX-License-Identifier: MIT

# Restart G Pro keyboard daemon

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Restarting G Pro Daemon ==="
echo

"$SCRIPT_DIR/gpro-daemon-stop.sh"
sleep 0.5
"$SCRIPT_DIR/gpro-daemon-start.sh"
