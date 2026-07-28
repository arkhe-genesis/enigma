# SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
# SPDX-License-Identifier: MIT

"""
Newline-delimited JSON wire protocol for the out-of-process audio backend.

Every message is one line:

    {"call": "<method>", "args": [...]}

No id, no reply channel: the parent dispatches one-shot, the daemon executes,
done. Kept tiny and dependency-free so both sides can import it in isolation.
"""

import json


def encode(call, *args):
    """Pack a method call into a single newline-terminated UTF-8 line."""
    payload = json.dumps({"call": call, "args": list(args)},
                         separators=(",", ":"))
    return (payload + "\n").encode("utf-8")


def decode(line):
    """Unpack one line from the parent. Returns (call, args), or (None, None)
    on malformed input (the caller logs and continues)."""
    line = line.strip()
    if not line:
        return None, None
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None, None
    call = obj.get("call")
    if not call:
        return None, None
    args = obj.get("args", [])
    if not isinstance(args, list):
        return None, None
    return call, args
