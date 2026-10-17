# ZXing (vendored)

`zxing-library.min.js` is `@zxing/library` 0.21.3 (`umd/index.min.js`), Apache-2.0 (see `LICENSE`),
copied unmodified from the npm package. It is only loaded when a browser has no native
`BarcodeDetector` (Safari/iOS), to scan filament barcodes with the camera.

It is self-hosted on purpose: the Content-Security-Policy only allows scripts from this origin.
To update: `npm pack @zxing/library@<version>`, copy `umd/index.min.js` over this file and run the
scan test in a browser.
