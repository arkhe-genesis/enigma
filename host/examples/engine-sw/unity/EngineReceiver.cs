using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// Sample consumer of Enigma updates. Subscribes to OnUpdate and reacts
/// to two spec paths from the port engine display example. Attach to
/// any GameObject in the same scene as the Enigma component.
///
/// This is a minimal template - real applications typically split
/// concerns across several MonoBehaviours (one per system, one per
/// visual layer, etc.).
/// </summary>
public class EngineReceiver : MonoBehaviour
{
    [Tooltip("Reference to the Enigma component. Auto-found via " +
             "FindObjectOfType at Start if left blank.")]
    [SerializeField] private Enigma enigma;

    [Tooltip("Optional: text mesh to display current thrust.")]
    [SerializeField] private TextMesh thrustLabel;

    void Start()
    {
        if (enigma == null) enigma = FindObjectOfType<Enigma>();
        if (enigma == null)
        {
            Debug.LogError("EngineReceiver: no Enigma component found in scene.");
            enabled = false;
            return;
        }

        // Subscribing here fires immediately with the cached snapshot,
        // so first-frame state is correct without a hand-rolled seed step.
        enigma.OnUpdate += HandleUpdate;

        // Custom out-of-band events use OnEventReceived - filter by name.
        enigma.OnEventReceived += HandleCustomEvent;
    }

    void OnDestroy()
    {
        if (enigma != null)
        {
            enigma.OnUpdate -= HandleUpdate;
            enigma.OnEventReceived -= HandleCustomEvent;
        }
    }

    void HandleUpdate(Dictionary<string, object> deltas)
    {
        // Filter for the keys we care about. Both TryGetValue and null-
        // checked System.Convert are needed because the payload arrives as
        // object with dynamic type; incoming numbers may be double, long,
        // or int depending on how the application encoded them.
        if (deltas.TryGetValue("PortEngineSpec.Thrust", out var thrustObj)
            && thrustObj != null)
        {
            float thrust = System.Convert.ToSingle(thrustObj);
            if (thrustLabel != null)
            {
                thrustLabel.text = (thrust / 1_000_000f).ToString("F1") + " MN";
            }
        }

        if (deltas.TryGetValue("PortEngineSpec.State", out var stateObj))
        {
            string state = stateObj?.ToString() ?? "";
            // Do whatever state-specific work you like here - swap a
            // material, play an animation, hide the object.
            if (state == "SCRAMMED")
            {
                Debug.Log("EngineReceiver: SCRAM detected - trigger visual cue.");
            }
        }
    }

    void HandleCustomEvent(string eventName, Dictionary<string, object> payload)
    {
        // Example: application emits a "game_state_change" event when the
        // engine's parent system transitions to combat. Filter on name.
        if (eventName == "game_state_change")
        {
            // ...respond to phase change...
        }
    }

    /// <summary>
    /// Example: send a message BACK to the connected enigma application.
    /// EmitToAll fans out to every connected client; when only one client
    /// (the application) is connected, this is effectively a targeted
    /// send.
    /// </summary>
    public void SendPurgeCommand(bool active)
    {
        if (enigma == null) return;
        enigma.EmitToAll("user_action", new Dictionary<string, object> {
            { "action", "toggle_purge" },
            { "value",  active },
        });
    }
}
