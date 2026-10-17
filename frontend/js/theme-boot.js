// Runs before first paint so the saved theme and accent never flash the defaults.
(function () {
  // Installed (home-screen) app: CSS keys safe areas and the status-bar strip off this class.
  try {
    if (window.navigator.standalone === true || window.matchMedia('(display-mode: standalone)').matches) {
      document.documentElement.classList.add('standalone');
    }
  } catch (e) { /* no matchMedia: browser tab behaviour */ }
  try {
    var p = JSON.parse(localStorage.getItem('pp-prefs') || '{}');
    var root = document.documentElement;
    if (p.theme === 'light' || p.theme === 'dark') root.setAttribute('data-theme', p.theme);
    if (/^#[0-9a-f]{6}$/i.test(p.accent || '')) root.style.setProperty('--accent', p.accent);
  } catch (e) { /* storage blocked: defaults are fine */ }
})();
