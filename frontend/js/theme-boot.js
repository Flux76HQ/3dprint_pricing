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
    // Which device this is, to pick the bottom bar that belongs to it while the account has not chosen one (main.js reads data-platform too).
    var ua = navigator.userAgent || '';
    var platform = /iPhone|iPad|iPod/.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1) ? 'ios' : (/Android/i.test(ua) ? 'android' : 'other');
    root.setAttribute('data-platform', platform);
    root.setAttribute('data-nav', p.navbar_style === 'ios' || p.navbar_style === 'android' ? p.navbar_style : (platform === 'android' ? 'android' : 'ios'));
    if (Number.isInteger(p.navbar_glass)) root.style.setProperty('--nav-glass', String(p.navbar_glass));
    if (/^#[0-9a-f]{6}$/i.test(p.accent || '')) root.style.setProperty('--accent', p.accent);
  } catch (e) { /* storage blocked: defaults are fine */ }
})();
