using System;
using System.Collections.Generic;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using System.Security.Cryptography;
using UnityEngine;

/// <summary>
/// Enigma display client for Unity - implements a Socket.IO server that
/// receives host_update events from an enigma application. Attach as a
/// component to a scene root GameObject once; other MonoBehaviours
/// subscribe to OnUpdate to consume state changes.
///
/// Compatible with python-socketio v4+ AsyncClient. Speaks the wire
/// protocol documented in enigma/docs/DISPLAY_WEBSOCKET_PROTOCOL.md.
/// </summary>
public class Enigma : MonoBehaviour
{
    [Header("Server Settings")]
    [SerializeField] private int port = 8082;

    private TcpListener listener;
    private Thread listenerThread;
    private List<ClientConnection> clients = new List<ClientConnection>();
    private bool isRunning = false;

    // Master copy of every spec key we've ever seen. The enigma application
    // sends deltas (only keys that changed in the last tick), so without a
    // cache here a consumer that subscribes mid-session would never see
    // spec values that haven't changed since it attached, leaving its state
    // stuck on defaults. The custom OnUpdate add accessor below replays the
    // cache into each newly-subscribed handler so anyone wiring
    // `enigma.OnUpdate += MyHandler` immediately gets the full current
    // state, no extra plumbing.
    private readonly Dictionary<string, object> _latestState = new Dictionary<string, object>();
    public IReadOnlyDictionary<string, object> LatestState => _latestState;

    private Action<Dictionary<string, object>> _onUpdateHandler;

    public event Action<Dictionary<string, object>> OnUpdate
    {
        add
        {
            _onUpdateHandler += value;
            // Replay cached state to the new subscriber so it doesn't miss
            // anything that was already published before it attached.
            if (value != null && _latestState.Count > 0)
            {
                try
                {
                    // Defensive copy so the subscriber can't mutate our cache.
                    value.Invoke(new Dictionary<string, object>(_latestState));
                }
                catch (Exception ex)
                {
                    Debug.LogException(ex);
                }
            }
        }
        remove
        {
            _onUpdateHandler -= value;
        }
    }

    // Queue for passing updates from background thread to main thread
    private Queue<Dictionary<string, object>> updateQueue = new Queue<Dictionary<string, object>>();

    // Generic event dispatch - for any inbound event name that isn't
    // host_update. Subscribers filter by event name in their handler.
    // The application can emit arbitrary named events over the same
    // socket; this is how out-of-band messaging works.
    public event Action<string, Dictionary<string, object>> OnEventReceived;
    private Queue<KeyValuePair<string, Dictionary<string, object>>> _eventQueue
        = new Queue<KeyValuePair<string, Dictionary<string, object>>>();

    // Fires (on the main thread) after any client completes the Socket.IO
    // CONNECT handshake. Subscribers use this to broadcast startup envelopes
    // that new clients need on join. Fires per-connect; handler can
    // EmitToAll (safe to send even to already-connected clients).
    public event Action OnClientConnected;
    private int _pendingConnectFires = 0;
    private readonly object _pendingConnectLock = new object();

    private const int PING_INTERVAL_MS = 25000;
    private const int PING_TIMEOUT_MS = 20000;

    private class ClientConnection
    {
        public TcpClient client;
        public NetworkStream stream;
        public string sid;
        public bool isWebSocket;
        public volatile bool awaitingPong;
        public readonly object writeLock = new object();
    }

    void Start()
    {
        StartServer();
    }

    void OnDestroy()
    {
        StopServer();
    }

    void OnApplicationQuit()
    {
        StopServer();
    }

    void Update()
    {
        // Process queued updates on main thread
        lock (updateQueue)
        {
            while (updateQueue.Count > 0)
            {
                var data = updateQueue.Dequeue();
                // Merge the delta into the master cache BEFORE dispatching,
                // so any new subscriber that attaches during a handler call
                // sees the freshest state.
                foreach (var kvp in data) _latestState[kvp.Key] = kvp.Value;
                _onUpdateHandler?.Invoke(data);
            }
        }
        lock (_eventQueue)
        {
            while (_eventQueue.Count > 0)
            {
                var kv = _eventQueue.Dequeue();
                try { OnEventReceived?.Invoke(kv.Key, kv.Value); }
                catch (Exception ex) { Debug.LogException(ex); }
            }
        }
        // Fire OnClientConnected on the main thread once per pending connect.
        int fires;
        lock (_pendingConnectLock) { fires = _pendingConnectFires; _pendingConnectFires = 0; }
        for (int i = 0; i < fires; i++)
        {
            try { OnClientConnected?.Invoke(); }
            catch (Exception ex) { Debug.LogException(ex); }
        }
    }

    private void StartServer()
    {
        if (isRunning) return;

        try
        {
            listener = new TcpListener(IPAddress.Any, port);
            listener.Start();
            isRunning = true;

            listenerThread = new Thread(ListenForClients);
            listenerThread.IsBackground = true;
            listenerThread.Start();

            Debug.Log($"WebSocket Server started on port {port}");
        }
        catch (Exception e)
        {
            Debug.LogError($"Failed to start WebSocket server: {e.Message}");
        }
    }

    private void StopServer()
    {
        if (!isRunning) return;

        isRunning = false;

        lock (clients)
        {
            foreach (var conn in clients)
            {
                try { conn.client.Close(); } catch { }
            }
            clients.Clear();
        }

        if (listener != null)
        {
            listener.Stop();
        }

        if (listenerThread != null && listenerThread.IsAlive)
        {
            listenerThread.Join(1000);
        }

        Debug.Log("WebSocket Server stopped");
    }

    private void ListenForClients()
    {
        while (isRunning)
        {
            try
            {
                if (listener.Pending())
                {
                    TcpClient tcpClient = listener.AcceptTcpClient();
                    var conn = new ClientConnection
                    {
                        client = tcpClient,
                        stream = tcpClient.GetStream(),
                        sid = GenerateSid(),
                        isWebSocket = false
                    };

                    lock (clients) { clients.Add(conn); }

                    Thread clientThread = new Thread(() => HandleClient(conn));
                    clientThread.IsBackground = true;
                    clientThread.Start();

                    Debug.Log($"Client connected, assigned sid: {conn.sid}");
                }
                else
                {
                    Thread.Sleep(10);
                }
            }
            catch (Exception e)
            {
                if (isRunning)
                {
                    Debug.LogError($"Error accepting client: {e.Message}");
                }
            }
        }
    }

    private string GenerateSid()
    {
        return Guid.NewGuid().ToString("N").Substring(0, 20);
    }

    private void HandleClient(ClientConnection conn)
    {
        try
        {
            byte[] buffer = new byte[8192];
            long lastPingTick = Environment.TickCount;
            conn.awaitingPong = false;

            while (isRunning && conn.client.Connected)
            {
                // Send Engine.IO pings to keep connection alive
                if (conn.isWebSocket)
                {
                    long elapsed = Environment.TickCount - lastPingTick;

                    if (conn.awaitingPong && elapsed > PING_TIMEOUT_MS)
                    {
                        Debug.Log($"Client {conn.sid} ping timeout");
                        break;
                    }

                    if (!conn.awaitingPong && elapsed > PING_INTERVAL_MS)
                    {
                        lock (conn.writeLock) { SendWebSocketText(conn.stream, "2"); } // Engine.IO ping
                        lastPingTick = Environment.TickCount;
                        conn.awaitingPong = true;
                    }
                }

                if (!conn.stream.DataAvailable)
                {
                    Thread.Sleep(5);
                    continue;
                }

                if (!conn.isWebSocket)
                {
                    // Read HTTP request
                    int bytesRead = conn.stream.Read(buffer, 0, buffer.Length);
                    if (bytesRead == 0) break;

                    string request = Encoding.UTF8.GetString(buffer, 0, bytesRead);
                    HandleHttpRequest(conn, request);
                }
                else
                {
                    // Handle WebSocket frames
                    string message = ReadWebSocketFrame(conn.stream);
                    if (message == null)
                    {
                        break; // Connection closed
                    }
                    if (!string.IsNullOrEmpty(message))
                    {
                        HandleSocketIOMessage(conn, message);
                    }
                }
            }
        }
        catch (Exception e)
        {
            Debug.Log($"Client {conn.sid} error: {e.Message}");
        }
        finally
        {
            lock (clients) { clients.Remove(conn); }
            try { conn.client.Close(); } catch { }
            Debug.Log($"Client {conn.sid} disconnected");
        }
    }

    private void HandleHttpRequest(ClientConnection conn, string request)
    {
        string[] lines = request.Split(new[] { "\r\n" }, StringSplitOptions.None);
        string requestLine = lines.Length > 0 ? lines[0] : "";

        // Check for WebSocket upgrade (Socket.IO with websocket transport)
        if (request.Contains("Upgrade: websocket"))
        {
            string key = GetHeader(lines, "Sec-WebSocket-Key");
            if (!string.IsNullOrEmpty(key))
            {
                // Send WebSocket handshake response
                string acceptKey = ComputeWebSocketAcceptKey(key);
                string response =
                    "HTTP/1.1 101 Switching Protocols\r\n" +
                    "Upgrade: websocket\r\n" +
                    "Connection: Upgrade\r\n" +
                    $"Sec-WebSocket-Accept: {acceptKey}\r\n\r\n";

                byte[] responseBytes = Encoding.UTF8.GetBytes(response);
                conn.stream.Write(responseBytes, 0, responseBytes.Length);
                conn.isWebSocket = true;

                Debug.Log($"Client {conn.sid} upgraded to WebSocket");

                // Send Engine.IO OPEN packet (type 0)
                // Format: 0{"sid":"...","upgrades":[],"pingInterval":25000,"pingTimeout":20000}
                string openPacket = $"0{{\"sid\":\"{conn.sid}\",\"upgrades\":[],\"pingInterval\":{PING_INTERVAL_MS},\"pingTimeout\":{PING_TIMEOUT_MS}}}";
                SendWebSocketText(conn.stream, openPacket);
            }
        }
        // Socket.IO polling request
        else if (requestLine.Contains("/socket.io/") && requestLine.Contains("transport=polling"))
        {
            // Engine.IO OPEN response for polling
            string openData = $"{{\"sid\":\"{conn.sid}\",\"upgrades\":[\"websocket\"],\"pingInterval\":{PING_INTERVAL_MS},\"pingTimeout\":{PING_TIMEOUT_MS}}}";
            // Engine.IO packet format for polling: <length>:<packet>
            string body = $"{openData.Length + 1}:0{openData}";

            string response =
                "HTTP/1.1 200 OK\r\n" +
                "Content-Type: text/plain; charset=UTF-8\r\n" +
                $"Content-Length: {body.Length}\r\n" +
                "Access-Control-Allow-Origin: *\r\n" +
                "Access-Control-Allow-Credentials: true\r\n" +
                "\r\n" + body;

            byte[] responseBytes = Encoding.UTF8.GetBytes(response);
            conn.stream.Write(responseBytes, 0, responseBytes.Length);
        }
        else
        {
            // Unknown request - 404
            string response = "HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n";
            byte[] responseBytes = Encoding.UTF8.GetBytes(response);
            conn.stream.Write(responseBytes, 0, responseBytes.Length);
        }
    }

    private void HandleSocketIOMessage(ClientConnection conn, string message)
    {
        if (message.Length == 0) return;

        // Engine.IO packet types: 0=open, 1=close, 2=ping, 3=pong, 4=message, 5=upgrade, 6=noop
        char engineType = message[0];

        switch (engineType)
        {
            case '2': // Ping from client - respond with pong
                SendWebSocketText(conn.stream, "3");
                break;

            case '3': // Pong from client (response to our ping)
                conn.awaitingPong = false;
                break;

            case '4': // Message (Socket.IO packet inside)
                if (message.Length > 1)
                {
                    HandleSocketIOPacket(conn, message.Substring(1));
                }
                break;

            case '5': // Upgrade
                Debug.Log($"Client {conn.sid} upgrade confirmed");
                break;
        }
    }

    private void HandleSocketIOPacket(ClientConnection conn, string packet)
    {
        if (packet.Length == 0) return;

        // Socket.IO packet types: 0=CONNECT, 1=DISCONNECT, 2=EVENT, 3=ACK, 4=ERROR, 5=BINARY_EVENT
        char socketType = packet[0];
        string data = packet.Length > 1 ? packet.Substring(1) : "";

        switch (socketType)
        {
            case '0': // CONNECT
                Debug.Log($"Socket.IO CONNECT from {conn.sid}");
                // Send CONNECT acknowledgment: 40 (Engine.IO message + Socket.IO connect)
                // With namespace support it would be 40{"sid":"..."} but default namespace is fine
                lock (conn.writeLock) { SendWebSocketText(conn.stream, $"40{{\"sid\":\"{conn.sid}\"}}"); }
                // Signal main-thread subscribers so they can broadcast startup
                // envelopes that new clients need. OnClientConnected fires on
                // the next Update().
                lock (_pendingConnectLock) { _pendingConnectFires++; }
                break;

            case '2': // EVENT
                HandleEventPacket(data);
                break;
        }
    }

    private void HandleEventPacket(string data)
    {
        try
        {
            // Format: ["event_name", {data}] or ["event_name", arg1, arg2, ...]
            // For host_update: ["host_update", {"key": "value", ...}]

            if (!data.StartsWith("[")) return;

            // Simple parsing - find event name
            int firstQuote = data.IndexOf('"');
            int secondQuote = data.IndexOf('"', firstQuote + 1);
            if (firstQuote < 0 || secondQuote < 0) return;

            string eventName = data.Substring(firstQuote + 1, secondQuote - firstQuote - 1);

            // Find the JSON object once - both host_update and generic events
            // pass through the same payload extract.
            int braceStart = data.IndexOf('{');
            int braceEnd = data.LastIndexOf('}');
            if (braceStart < 0 || braceEnd < 0) return;

            string jsonData = data.Substring(braceStart, braceEnd - braceStart + 1);
            var parsed = MiniJSON.Json.Deserialize(jsonData) as Dictionary<string, object>;
            if (parsed == null) return;

            if (eventName == "host_update")
            {
                lock (updateQueue) { updateQueue.Enqueue(parsed); }
            }
            else
            {
                // Any non-host_update event goes through the generic dispatch.
                // Subscribers filter by name.
                lock (_eventQueue)
                {
                    _eventQueue.Enqueue(new KeyValuePair<string, Dictionary<string, object>>(eventName, parsed));
                }
            }
        }
        catch (Exception e)
        {
            Debug.LogError($"Error parsing event: {e.Message}");
        }
    }

    private string GetHeader(string[] lines, string headerName)
    {
        foreach (string line in lines)
        {
            if (line.StartsWith(headerName + ":", StringComparison.OrdinalIgnoreCase))
            {
                return line.Substring(headerName.Length + 1).Trim();
            }
        }
        return null;
    }

    private string ComputeWebSocketAcceptKey(string key)
    {
        string combined = key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11";
        byte[] hash = SHA1.Create().ComputeHash(Encoding.UTF8.GetBytes(combined));
        return Convert.ToBase64String(hash);
    }

    private string ReadWebSocketFrame(NetworkStream stream)
    {
        try
        {
            int b1 = stream.ReadByte();
            int b2 = stream.ReadByte();
            if (b1 == -1 || b2 == -1) return null;

            int opcode = b1 & 0x0F;
            bool masked = (b2 & 0x80) != 0;
            long length = b2 & 0x7F;

            if (length == 126)
            {
                int hi = stream.ReadByte();
                int lo = stream.ReadByte();
                if (hi == -1 || lo == -1) return null;
                length = (hi << 8) | lo;
            }
            else if (length == 127)
            {
                byte[] lenBytes = new byte[8];
                int read = stream.Read(lenBytes, 0, 8);
                if (read < 8) return null;
                length = 0;
                for (int i = 0; i < 8; i++)
                    length = (length << 8) | lenBytes[i];
            }

            byte[] maskKey = null;
            if (masked)
            {
                maskKey = new byte[4];
                int read = stream.Read(maskKey, 0, 4);
                if (read < 4) return null;
            }

            byte[] payload = new byte[length];
            int totalRead = 0;
            while (totalRead < length)
            {
                int r = stream.Read(payload, totalRead, (int)(length - totalRead));
                if (r == 0) return null;
                totalRead += r;
            }

            if (masked && maskKey != null)
            {
                for (int i = 0; i < payload.Length; i++)
                    payload[i] ^= maskKey[i % 4];
            }

            switch (opcode)
            {
                case 0x08: // Close
                    return null;
                case 0x09: // Ping
                    SendWebSocketFrame(stream, payload, 0x0A); // Pong
                    return "";
                case 0x01: // Text
                    return Encoding.UTF8.GetString(payload);
                default:
                    return "";
            }
        }
        catch
        {
            return null;
        }
    }

    private void SendWebSocketText(NetworkStream stream, string text)
    {
        byte[] payload = Encoding.UTF8.GetBytes(text);
        SendWebSocketFrame(stream, payload, 0x01);
    }

    /// <summary>
    /// Emit a Socket.IO event to all connected WebSocket clients.
    /// Safe to call from the Unity main thread.
    /// </summary>
    public void EmitToAll(string eventName, Dictionary<string, object> data)
    {
        // Fast path: flat scalar-only payloads hand-serialize for zero
        // allocation cost. Nested dict/list values require MiniJSON; take
        // that path when any non-scalar is present.
        bool needsMiniJson = false;
        foreach (var kvp in data)
        {
            var v = kvp.Value;
            if (v is float || v is double || v is bool || v is int || v is long || v is string || v == null) continue;
            needsMiniJson = true;
            break;
        }
        string payload;
        if (needsMiniJson)
        {
            payload = MiniJSON.Json.Serialize(data);
        }
        else
        {
            var flat = new System.Text.StringBuilder("{");
            bool firstFlat = true;
            foreach (var kvp in data)
            {
                if (!firstFlat) flat.Append(',');
                flat.Append('"').Append(kvp.Key).Append("\":");
                var v = kvp.Value;
                if (v is float f)
                    flat.Append(f.ToString("G6", System.Globalization.CultureInfo.InvariantCulture));
                else if (v is double d)
                    flat.Append(d.ToString("G6", System.Globalization.CultureInfo.InvariantCulture));
                else if (v is bool b)
                    flat.Append(b ? "true" : "false");
                else if (v is int || v is long)
                    flat.Append(v);
                else if (v == null)
                    flat.Append("null");
                else
                    flat.Append('"').Append(v).Append('"');
                firstFlat = false;
            }
            flat.Append('}');
            payload = flat.ToString();
        }
        string msg = "42[\"" + eventName + "\"," + payload + "]";

        lock (clients)
        {
            foreach (var conn in clients)
            {
                if (!conn.isWebSocket) continue;
                lock (conn.writeLock)
                {
                    try { SendWebSocketText(conn.stream, msg); } catch { }
                }
            }
        }
    }

    private void SendWebSocketFrame(NetworkStream stream, byte[] payload, int opcode)
    {
        try
        {
            List<byte> frame = new List<byte>();
            frame.Add((byte)(0x80 | opcode)); // FIN + opcode

            if (payload.Length < 126)
            {
                frame.Add((byte)payload.Length);
            }
            else if (payload.Length < 65536)
            {
                frame.Add(126);
                frame.Add((byte)(payload.Length >> 8));
                frame.Add((byte)(payload.Length & 0xFF));
            }
            else
            {
                frame.Add(127);
                for (int i = 7; i >= 0; i--)
                    frame.Add((byte)((payload.Length >> (i * 8)) & 0xFF));
            }

            frame.AddRange(payload);
            stream.Write(frame.ToArray(), 0, frame.Count);
        }
        catch { }
    }
}
