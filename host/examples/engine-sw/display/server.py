#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
# SPDX-License-Identifier: MIT

"""
Minimal Enigma display server.

Serves a static content directory (HTML/CSS/JS) and accepts spec-value
updates from an enigma application over Socket.IO. Re-broadcasts every
update to connected browser clients as an `update` event.

This is the reference server for the DISPLAY_CONFIG.md tutorial. It's
intentionally small; a production display server can be more
elaborate (auth, TLS, per-page routing) but the protocol semantics
below are what enigma's DisplayManager expects.

Usage:
    python3 server.py --port 8080 --content ./content
"""

import argparse
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from flask_socketio import SocketIO, emit


app = Flask(__name__)
app.config['SECRET_KEY'] = 'engine-example-not-a-secret'
socketio = SocketIO(app, cors_allowed_origins='*')

# Master cache of every spec value we've ever received. Any newly-connected
# browser client is sent this as one `update` event so it doesn't have to
# wait for the next application-side change to have a full picture.
current_data: dict = {}

# Set by main() before app.run(); referenced by the static-file route.
content_dir: Path = Path('content')


# ---------------------------------------------------------------------------
# Static file serving
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    return send_from_directory(content_dir, 'index.html')


@app.route('/<path:filename>')
def static_files(filename):
    return send_from_directory(content_dir, filename)


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------

@app.route('/update', methods=['POST'])
def http_update():
    """POST /update - legacy HTTP entry point.

    Enigma's DisplayManager uses the persistent WebSocket connection
    below, but this HTTP endpoint is retained as a fallback and as a
    convenient way to test the server from the command line:

        curl -X POST http://localhost:8080/update \\
             -H 'Content-Type: application/json' \\
             -d '{"PortEngineSpec.Thrust": 4200000}'
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'no JSON body'}), 400
    current_data.update(data)
    socketio.emit('update', data)
    return jsonify({'status': 'ok', 'received': len(data)}), 200


@app.route('/heartbeat', methods=['GET'])
def heartbeat():
    """Health check + snapshot of every key we've seen."""
    return jsonify({
        'status': 'alive',
        'data_keys': sorted(current_data.keys()),
    }), 200


# ---------------------------------------------------------------------------
# Socket.IO event handlers
# ---------------------------------------------------------------------------

@socketio.on('connect')
def on_connect():
    """New client (browser or application). Send the current cache
    immediately so it doesn't render on stale defaults."""
    if current_data:
        emit('update', current_data)


@socketio.on('get_data')
def on_get_data():
    """Client explicitly requested a snapshot."""
    emit('update', current_data)


@socketio.on('host_update')
def on_host_update(data):
    """Persistent-connection entry point. Every update the enigma
    application publishes lands here, whether it's a delta or (on
    reconnect) a full snapshot. Merge into the cache and re-broadcast
    to every browser client."""
    if not isinstance(data, dict):
        return
    current_data.update(data)
    emit('update', data, broadcast=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global content_dir

    parser = argparse.ArgumentParser(description='Enigma display server')
    parser.add_argument('--port', type=int, default=8080,
                        help='TCP port to listen on (default: 8080)')
    parser.add_argument('--host', default='0.0.0.0',
                        help='Bind address (default: 0.0.0.0, all interfaces)')
    parser.add_argument('--content', type=Path, default=Path(__file__).parent / 'content',
                        help='Static content directory (default: ./content)')
    args = parser.parse_args()

    # Resolve to an absolute path relative to the CWD. Flask's send_from_directory
    # re-roots a *relative* directory under the app's root_path (this file's dir),
    # which would double-nest a path like "display/content" into 404s. An absolute
    # path is used verbatim, so a relative --content behaves as the caller expects.
    content_dir = args.content.resolve()

    print(f"[enigma] Serving {content_dir} on http://{args.host}:{args.port}/")
    print(f"[enigma]   GET  /              - index.html")
    print(f"[enigma]   POST /update        - inject a value (HTTP fallback)")
    print(f"[enigma]   GET  /heartbeat     - server health + cached keys")
    print(f"[enigma]   WS   /socket.io/    - persistent connection (application + browsers)")

    socketio.run(app, host=args.host, port=args.port, allow_unsafe_werkzeug=True)


if __name__ == '__main__':
    main()
