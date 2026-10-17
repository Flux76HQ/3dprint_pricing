// Native-app behaviour for the installed PWA: no zoom, no sideways swipes, no history to swipe back to.

export function isStandalone() {
  return window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
}

/** Navigate to an in-app hash route. Installed, it replaces the current entry instead of adding one. */
export function goTo(hash) {
  if (isStandalone()) window.location.replace(hash);
  else window.location.hash = hash;
}

export function installNativeBehaviour() {
  const block = (e) => e.preventDefault();

  // Pinch-to-zoom. iOS Safari reports it as gesture events, which the viewport tag alone does not stop;
  // the touchmove guard covers the browsers that do not have them. Double-tap zoom is stopped by
  // `touch-action` in the CSS.
  for (const type of ['gesturestart', 'gesturechange', 'gestureend']) {
    document.addEventListener(type, block, { passive: false });
  }
  document.addEventListener('touchmove', (e) => { if (e.touches.length > 1) e.preventDefault(); }, { passive: false });

  // The iOS edge-swipe goes back/forward through history. An installed app that never adds history
  // entries has nothing to swipe to, so every in-app link replaces the current entry.
  if (isStandalone()) {
    document.addEventListener('click', (e) => {
      const link = e.target.closest ? e.target.closest('a[href^="#/"]') : null;
      if (!link || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || link.target) return;
      e.preventDefault();
      window.location.replace(link.getAttribute('href'));
    });
  }
}
