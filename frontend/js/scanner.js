import { t } from './i18n.js';
import { h } from './ui.js';

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

export function cameraAvailable() {
  return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
}

/** Opens a camera dialog; resolves with the scanned text, or null when cancelled or unavailable. */
export function scanBarcode() {
  return new Promise((resolve) => {
    const video = h('video', { class: 'scan-video', playsinline: true, muted: true, autoplay: true });
    const status = h('p', { class: 'muted', role: 'status' }, t('scanner.starting'));
    let stopped = false;
    let stopScan = () => {};
    let result = null;

    const dialog = h('dialog', { class: 'glass sheet' },
      h('h2', {}, t('scanner.title')),
      h('div', { class: 'scan-frame' }, video, h('div', { class: 'scan-line', 'aria-hidden': 'true' })),
      status,
      h('div', { class: 'row end' },
        h('button', { class: 'btn', type: 'button', onclick: () => dialog.close() }, t('common.cancel'))));
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
    const fail = (message) => { status.textContent = message; status.classList.add('error'); };

    if (!cameraAvailable()) {
      fail(t('scanner.unavailable'));
      return;
    }

    (async () => {
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
        fail(cameraMessage(e));
      }
    })();
  });
}
