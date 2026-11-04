import { t } from './i18n.js';
import { enhanceDialog, fill, h } from './ui.js';

// Barcode scanning with the camera. Uses the browser's own BarcodeDetector where it exists
// (Chrome/Edge/Android) and the vendored ZXing build everywhere else (Safari/iOS). A hardware
// scanner needs none of this: it types into the field like a keyboard.
const FORMATS = ['ean_13', 'ean_8', 'upc_a', 'upc_e', 'code_128', 'code_39', 'itf', 'qr_code'];
let zxingLoading = null;

function loadZXing() {
  if (window.ZXing) return Promise.resolve(window.ZXing);
  zxingLoading ??= new Promise((resolve, reject) => {
    const script = h('script', { src: '/vendor/zxing/zxing-library.min.js' });
    script.onload = () => resolve(window.ZXing);
    script.onerror = () => reject(new Error(t('scanner.library_failed')));
    document.head.append(script);
  });
  return zxingLoading;
}

// Plain words for the errors getUserMedia and ZXing throw; typing or a hardware scanner always works.
function cameraMessage(e) {
  switch (e && e.name) {
    case 'NotAllowedError':
    case 'SecurityError':
      return t('scanner.no_access');
    case 'NotFoundError':
    case 'OverconstrainedError':
      return t('scanner.no_camera');
    case 'NotReadableError':
      return t('scanner.in_use');
    default:
      return t('scanner.failed', { message: e && e.message ? e.message : e });
  }
}

// What to tap to give the app the camera back, for the device it runs on (data-platform is set before the first paint).
function accessSteps() {
  switch (document.documentElement.getAttribute('data-platform')) {
    case 'android':
      return [t('scanner.help.android_1'), t('scanner.help.android_2'), t('scanner.help.android_3'), t('scanner.help.android_4')];
    case 'ios':
      return [t('scanner.help.ios_1'), t('scanner.help.ios_2'), t('scanner.help.ios_3')];
    default:
      return [t('scanner.help.other_1'), t('scanner.help.other_2')];
  }
}

export function cameraAvailable() {
  return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
}

// Starts the camera in `video` and calls `onCode` with every barcode it reads (the same one again and again while it stays in view).
// Resolves with the function that stops it; rejects with what getUserMedia or ZXing threw.
async function readBarcodes(video, onCode) {
  if ('BarcodeDetector' in window) {
    const detector = new window.BarcodeDetector({ formats: FORMATS });
    const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' } }, audio: false });
    const release = () => stream.getTracks().forEach((track) => track.stop());
    video.srcObject = stream;
    try { await video.play(); } catch (e) { release(); throw e; }
    const timer = setInterval(async () => {
      try {
        for (const code of await detector.detect(video)) onCode(code.rawValue);
      } catch { /* a frame that cannot be read is fine */ }
    }, 200);
    return () => { clearInterval(timer); release(); };
  }
  const ZXing = await loadZXing();
  const hints = new Map([[ZXing.DecodeHintType.POSSIBLE_FORMATS, [
    ZXing.BarcodeFormat.EAN_13, ZXing.BarcodeFormat.EAN_8, ZXing.BarcodeFormat.UPC_A, ZXing.BarcodeFormat.UPC_E,
    ZXing.BarcodeFormat.CODE_128, ZXing.BarcodeFormat.CODE_39, ZXing.BarcodeFormat.ITF, ZXing.BarcodeFormat.QR_CODE]]]);
  const reader = new ZXing.BrowserMultiFormatReader(hints, 150);
  try {
    await reader.decodeFromVideoDevice(null, video, (res) => { if (res) onCode(res.getText()); });
  } catch (e) { reader.reset(); throw e; }
  return () => reader.reset();
}

/** The camera view with its status line and, when the camera is refused, the steps to allow it. `onCode` gets every barcode read, as
    trimmed text (the same one again while it stays in view). `start()` turns the camera on (also what `retry` does), `stop()` turns it off. */
export function cameraPanel(onCode) {
  const video = h('video', { class: 'scan-video', playsinline: true, muted: true, autoplay: true });
  const status = h('p', { class: 'muted', role: 'status' }, t('scanner.starting'));
  const help = h('div', { class: 'scan-help', hidden: true });
  const frame = h('div', { class: 'scan-frame' }, video, h('div', { class: 'scan-line', 'aria-hidden': 'true' }));
  const retry = h('button', { class: 'btn primary', type: 'button', hidden: true, onclick: () => start() }, t('scanner.retry'));
  let halt = () => {};
  let run = 0;                                                   // a start that is overtaken (stop, or start again) turns its camera off at once

  const fail = (message, steps) => {
    status.textContent = message;
    status.classList.add('error');
    frame.hidden = true;                                         // the black box only pushes the instructions off a phone screen
    fill(help, steps && h('div', {},
      h('p', {}, h('strong', {}, t('scanner.help.title'))),
      h('ol', {}, steps.map((step) => h('li', {}, step))),
      h('p', { class: 'muted' }, t('scanner.help.type'))));
    help.hidden = !steps;
    retry.hidden = false;
  };

  function stop() {
    run += 1;
    halt();
    halt = () => {};
  }

  async function start() {
    stop();
    const mine = run;
    status.textContent = t('scanner.starting');
    status.classList.remove('error');
    frame.hidden = false;
    help.hidden = true;
    retry.hidden = true;
    if (!cameraAvailable()) {
      fail(t('scanner.unavailable'));
      return;
    }
    try {
      const off = await readBarcodes(video, (text) => {
        const code = String(text ?? '').trim();
        if (mine === run && code) onCode(code);
      });
      if (mine !== run) { off(); return; }
      halt = off;
      status.textContent = t('scanner.hold');
    } catch (e) {
      if (mine !== run) return;
      const denied = e && (e.name === 'NotAllowedError' || e.name === 'SecurityError');
      fail(cameraMessage(e), denied ? accessSteps() : null);
    }
  }

  return { frame, status, help, retry, start, stop };
}

/** Opens a camera dialog; resolves with the scanned text, or null when cancelled or unavailable. */
export function scanBarcode() {
  return new Promise((resolve) => {
    let result = null;
    const camera = cameraPanel((code) => {
      if (result !== null) return;
      result = code;
      dialog.close();
    });
    const dialog = enhanceDialog(h('dialog', { class: 'glass sheet' },
      h('h2', {}, t('scanner.title')),
      camera.frame,
      camera.status,
      camera.help,
      h('div', { class: 'row end' },
        camera.retry,
        h('button', { class: 'btn', type: 'button', onclick: () => dialog.close() }, t('common.cancel')))));
    dialog.addEventListener('close', () => {
      camera.stop();
      dialog.remove();
      resolve(result);
    });
    document.body.append(dialog);
    dialog.showModal();
    camera.start();
  });
}
