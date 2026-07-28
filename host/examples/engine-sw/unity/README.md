# Unity display (reference)

`Enigma.cs` and `EngineReceiver.cs` are reference C#, not a runnable Unity
project. They show a Unity scene acting as an enigma display: `Enigma.cs` runs a
self-contained Socket.IO server inside the game process (the enigma application
connects out to it), and `EngineReceiver.cs` is a sample MonoBehaviour that reads
the published spec values. To use them you supply the Unity project and the wiring
below.

## Dependencies

`Enigma.cs` needs a JSON library to parse inbound event payloads and serialize
outbound ones. It calls `MiniJSON.Json.Deserialize` and `MiniJSON.Json.Serialize`,
which are **not bundled here**: without one of them the script will not compile.
Add [MiniJSON](https://gist.github.com/darktable/1411710) (a small public-domain
single-file parser) to your project, or replace those two calls with any JSON
library that produces `Dictionary<string, object>` / `List<object>` from a string
and back (for example the `com.unity.nuget.newtonsoft-json` package).

## Wiring it up

1. Create or open a Unity project and drop both scripts into `Assets/`.
2. Add a GameObject, attach the `Enigma` component, and set its listen `port`.
3. Add `EngineReceiver` to a GameObject and assign a `TextMesh` to its
   `thrustLabel`, or edit `HandleUpdate` to drive whatever visuals you want.
4. Point a display at the Unity server: add a `configs/UnityDisplay.json` with
   `"URL": "http://<unity-host>:<port>/update"` and a `Publish` list, plus an entry
   in `display_mappings.json`. See
   [DISPLAY_CONFIG.md](../../../enigma/docs/DISPLAY_CONFIG.md).
5. Run the Unity scene first, then run the application. Spec changes now drive the
   receiver, and `EngineReceiver.SendPurgeCommand` shows the display-to-application
   path back the other way.

## Scope

This is a minimal single-file server: enough to receive `host_update` events,
render a couple of spec values, and send events back. It is not hardened for
production (no TLS or auth), and its inbound handling assumes the event payload is
a JSON object. The wire protocol it speaks is documented in
[DISPLAY_WEBSOCKET_PROTOCOL.md](../../../enigma/docs/DISPLAY_WEBSOCKET_PROTOCOL.md).
