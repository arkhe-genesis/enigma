/*
 * Simulated engine panel.
 *
 * Each widget POSTs its value to /input on the application's own input server,
 * which stores it as a SimPanel class attribute for the device to read. This
 * stands in for a hardware panel; in a hardware build the device reads the real
 * board instead. The display server is not involved.
 */
(function () {
  function post(body) {
    fetch('/input', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).catch(function (e) { console.warn('input failed', e); });
  }

  // Throttle -> SimPanel.throttle
  const throttle = document.getElementById('throttle');
  const throttleVal = document.getElementById('throttle-val');
  throttle.addEventListener('input', function () {
    const n = Number(throttle.value);
    throttleVal.textContent = n.toLocaleString() + ' N';
    post({ throttle: n });
  });

  // State -> SimPanel.state
  const stateBtns = document.getElementById('state-btns');
  stateBtns.addEventListener('click', function (e) {
    const b = e.target.closest('button[data-state]');
    if (!b) return;
    stateBtns.querySelectorAll('button').forEach(function (x) {
      x.classList.toggle('active', x === b);
    });
    post({ state: b.dataset.state });
  });

  // Purge -> SimPanel.purge (toggle: click to hold it on, click again to clear).
  // A mouse click is too brief to register as a momentary press against the tick
  // rate, so the simulated panel uses a toggle; engine-full's physical button is
  // momentary.
  const purge = document.getElementById('purge');
  let purgeOn = false;
  purge.addEventListener('click', function () {
    purgeOn = !purgeOn;
    purge.classList.toggle('active', purgeOn);
    post({ purge: purgeOn });
  });

  // Temp cap -> SimPanel.tempcap
  const tempcap = document.getElementById('tempcap');
  const tempcapVal = document.getElementById('tempcap-val');
  tempcap.addEventListener('input', function () {
    const n = Number(tempcap.value);
    tempcapVal.textContent = n + ' MK';
    post({ tempcap: n });
  });
})();
