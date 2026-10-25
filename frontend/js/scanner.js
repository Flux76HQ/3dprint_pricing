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

/** Opens a camera dialog; resolves with the scanned text, or null when cancelled or unavailable. */
export function scanBarcode() {
  return new Promise((resolve) => {
    const video = h('video', { class: 'scan-video', playsinline: true, muted: true, autoplay: true });
    const status = h('p', { class: 'muted', role: 'status' }, t('scanner.starting'));
    const help = h('div', { class: 'scan-help', hidden: true });
    const frame = h('div', { class: 'scan-frame' }, video, h('div', { class: 'scan-line', 'aria-hidden': 'true' }));
    let stopped = false;
    let stopScan = () => {};
    let result = null;
    const retry = h('button', { class: 'btn primary', type: 'button', hidden: true, onclick: () => start() }, t('scanner.retry'));

    const dialog = enhanceDialog(h('dialog', { class: 'glass sheet' },
      h('h2', {}, t('scanner.title')),
      frame,
      status,
      help,
      h('div', { class: 'row end' },
        retry,
        h('button', { class: 'btn', type: 'button', onclick: () => dialog.close() }, t('common.cancel')))));
    dialog.addEventListener('close', () => {
      stopped = true;
      stopScan();
      dialog.remove();
      resolve(result);
    });
    document.body.append(dialog);
    dialog.showModal();

    const found = (text) => {
      if (stopped || !text) return;
      result = String(text).trim();
      dialog.close();
    };
    const fail = (message, steps) => {
      status.textContent = message;
      status.classList.add('error');
      frame.hidden = true;                                   // the black box only pushes the instructions off a phone screen
      fill(help, steps && h('div', {},
        h('p', {}, h('strong', {}, t('scanner.help.title'))),
        h('ol', {}, steps.map((step) => h('li', {}, step))),
        h('p', { class: 'muted' }, t('scanner.help.type'))));
      help.hidden = !steps;
      retry.hidden = false;
    };

    // Also what "Try again" runs, after the person has changed the permission.
    const start = async () => {
      stopScan();
      stopScan = () => {};
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
        if ('BarcodeDetector' in window) {
          const detector = new window.BarcodeDetector({ formats: FORMATS });
          const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' } }, audio: false });
          video.srcObject = stream;
          await video.play();
          status.textContent = t('scanner.hold');
          const timer = setInterval(async () => {
            try {
              const codes = await detector.detect(video);
              if (codes.length) found(codes[0].rawValue);
            } catch { /* a frame that cannot be read is fine */ }
          }, 200);
          stopScan = () => { clearInterval(timer); stream.getTracks().forEach((t) => t.stop()); };
        } else {
          const ZXing = await loadZXing();
          const hints = new Map([[ZXing.DecodeHintType.POSSIBLE_FORMATS, [
            ZXing.BarcodeFormat.EAN_13, ZXing.BarcodeFormat.EAN_8, ZXing.BarcodeFormat.UPC_A, ZXing.BarcodeFormat.UPC_E,
            ZXing.BarcodeFormat.CODE_128, ZXing.BarcodeFormat.CODE_39, ZXing.BarcodeFormat.ITF, ZXing.BarcodeFormat.QR_CODE]]]);
          const reader = new ZXing.BrowserMultiFormatReader(hints, 150);
          stopScan = () => reader.reset();
          status.textContent = t('scanner.hold');
          await reader.decodeFromVideoDevice(null, video, (res) => { if (res) found(res.getText()); });
        }
      } catch (e) {
        const denied = e && (e.name === 'NotAllowedError' || e.name === 'SecurityError');
        fail(cameraMessage(e), denied ? accessSteps() : null);
      }
    };
    start();
  });
}
