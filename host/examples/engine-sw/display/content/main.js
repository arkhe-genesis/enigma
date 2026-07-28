/*
 * Engine display - programmatic Enigma consumer.
 *
 * Everything the declarative data-* bindings can express lives in
 * index.html. This file handles the cases the declarative layer
 * can't:
 *   - derivations that depend on more than one spec value,
 *   - reactions to connection lifecycle.
 */

// Derive an "operational mode" label from two spec values. Declarative
// bindings can't express multi-value logic - each binding reads a
// single key. Any derivation with a cross-dependency belongs here.
//
// Both watchers below run whenever either input changes. They share a
// single render function to keep the two branches in sync.
function refreshMode() {
  const state = Enigma.get('PortEngineSpec.State');
  const purge = Enigma.get('PortEngineSpec.PurgeActive');
  const el = document.getElementById('operational-mode');
  if      (state === 'SCRAMMED')  el.textContent = 'SHUTDOWN';
  else if (state === 'OFFLINE')   el.textContent = 'STANDBY';
  else if (purge === true)        el.textContent = 'PURGING';
  else if (state === 'ONLINE')    el.textContent = 'NOMINAL';
  else                            el.textContent = '--';
}
Enigma.watch(['PortEngineSpec.State', 'PortEngineSpec.PurgeActive'], refreshMode);

// Connection status -> CSS class on the corner dot. The callback is
// called immediately with the current status, then on every edge.
Enigma.onStatus((connected) => {
  document.getElementById('conn-dot').className = connected ? 'ok' : 'lost';
});
