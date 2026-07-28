/*
 * Enigma display debug panel (stock).
 *
 * Drop-in overlay that lists every SpecVar the display has cached from the
 * server, with live updates while open. Include this script and debug-panel.css
 * and it auto-initializes: a gear button appears in the corner; clicking it
 * opens a dismissable list of the subscribed SpecVars and their current values.
 *
 * Depends only on the Enigma client (Enigma.getAll() and Enigma.subscribe()).
 * Optional hint label: drop `<div class="enigma-debug-hint">...</div>` anywhere
 * in the page and debug-panel.css positions it next to the gear.
 */
(function () {
  const html = `
    <button class="enigma-debug-btn" id="enigma-debug-btn" title="Show subscribed SpecVars"
            aria-label="Show subscribed SpecVars">&#9881;</button>
    <div class="enigma-debug-overlay" id="enigma-debug-overlay">
      <div class="enigma-debug-dialog">
        <div class="enigma-debug-header">
          <span>SUBSCRIBED SPECVARS</span>
          <button class="enigma-debug-close" id="enigma-debug-close" aria-label="Close">&times;</button>
        </div>
        <div class="enigma-debug-content" id="enigma-debug-content">
          <div class="enigma-debug-empty">No data received yet</div>
        </div>
      </div>
    </div>`;

  function init() {
    if (typeof Enigma === 'undefined') {
      console.warn('[enigma] debug-panel: Enigma client not found; panel disabled');
      return;
    }
    const root = document.querySelector('.display-root') || document.body;
    root.insertAdjacentHTML('beforeend', html);

    const btn = document.getElementById('enigma-debug-btn');
    const overlay = document.getElementById('enigma-debug-overlay');
    const closeBtn = document.getElementById('enigma-debug-close');
    const content = document.getElementById('enigma-debug-content');

    function fmt(v) {
      if (typeof v === 'number') return v.toLocaleString(undefined, { maximumFractionDigits: 4 });
      if (v !== null && typeof v === 'object') return JSON.stringify(v);
      return String(v);
    }

    function refresh() {
      const values = Enigma.getAll();
      const keys = Object.keys(values).sort();
      if (!keys.length) {
        content.innerHTML = '<div class="enigma-debug-empty">No data received yet</div>';
        return;
      }
      content.innerHTML = keys.map((k) =>
        '<div class="enigma-debug-item">' +
        '<span class="enigma-debug-key"></span>' +
        '<span class="enigma-debug-value"></span></div>'
      ).join('');
      // set text via textContent to avoid HTML injection from values
      const items = content.querySelectorAll('.enigma-debug-item');
      keys.forEach((k, i) => {
        items[i].querySelector('.enigma-debug-key').textContent = k;
        items[i].querySelector('.enigma-debug-value').textContent = fmt(values[k]);
      });
    }

    function open() { refresh(); overlay.classList.add('visible'); }
    function close() { overlay.classList.remove('visible'); }

    btn.addEventListener('click', open);
    closeBtn.addEventListener('click', close);
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') close(); });

    // Live-refresh while the panel is open.
    Enigma.subscribe(() => { if (overlay.classList.contains('visible')) refresh(); });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
