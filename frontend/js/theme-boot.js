// Runs before first paint so the saved theme and accent never flash the defaults.
(function () {
  // Installed (home-screen) app: CSS keys safe areas and the status-bar strip off this class.
  try {
    if (window.navigator.standalone === true || window.matchMedia('(display-mode: standalone)').matches) {
      document.documentElement.classList.add('standalone');
    }
  } catch (e) { /* no matchMedia: browser tab behaviour */ }
  var root = document.documentElement;
  // Which device this is, to pick the bottom bar that belongs to it while the account has not chosen one (navStyle() in ui.js, scanner.js and
  // bulk-scan.js read data-platform too). Outside the storage try: a browser that blocks storage still gets the bar of its device.
  var ua = navigator.userAgent || '';
  var platform = /iPhone|iPad|iPod/.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1) ? 'ios' : (/Android/i.test(ua) ? 'android' : 'other');
  root.setAttribute('data-platform', platform);
  var nav = platform === 'android' ? 'android' : 'ios';
  try {
    var p = JSON.parse(localStorage.getItem('pp-prefs') || '{}');
    if (p.theme === 'light' || p.theme === 'dark') root.setAttribute('data-theme', p.theme);
    if (p.navbar_style === 'ios' || p.navbar_style === 'android') nav = p.navbar_style;
    if (Number.isInteger(p.navbar_glass)) {                       // the same sums as applyNavGlass in ui.js, before the first paint
      var g = Math.min(100, Math.max(0, p.navbar_glass));
      root.style.setProperty('--nav-alpha', (1 - g * 0.0085).toFixed(3));
      root.style.setProperty('--nav-blur', (10 + g * 0.3).toFixed(1) + 'px');
    }
    if (/^#[0-9a-f]{6}$/i.test(p.accent || '')) root.style.setProperty('--accent', p.accent);
  } catch (e) { /* storage blocked: defaults are fine */ }
  root.setAttribute('data-nav', nav);
})();
