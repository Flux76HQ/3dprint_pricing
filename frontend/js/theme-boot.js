// Runs before first paint so the saved theme and accent never flash the defaults.
(function () {
  try {
    var p = JSON.parse(localStorage.getItem('pp-prefs') || '{}');
    var root = document.documentElement;
    if (p.theme === 'light' || p.theme === 'dark') root.setAttribute('data-theme', p.theme);
    if (/^#[0-9a-f]{6}$/i.test(p.accent || '')) root.style.setProperty('--accent', p.accent);
  } catch (e) { /* storage blocked: defaults are fine */ }
})();
