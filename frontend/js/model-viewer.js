// A small viewer for the 3D model of a print file: it draws the triangles the server read from the STL or 3MF
// (`GET /api/print-files/<id>/mesh`, see printfile.triangles), lets the model be turned and zoomed, and hands out a picture of what
// is on screen. It is written against WebGL directly, so there is no third-party code to vendor; the file itself is never parsed
// here (uploads are untrusted and are only read by the server).
import { downloadFile } from './api.js';
import { t } from './i18n.js';
import { h } from './ui.js';

const SIZE = 1024;                                // the picture is square and always this many pixels, whatever the screen
const BACKGROUND = [0.94, 0.94, 0.93];            // a plain light backdrop: the saved picture is a starting point, not the result
// How the model is turned is kept as a rotation matrix (three rows of three), not as two angles: with angles one direction is
// always blocked at the top; a matrix can be turned on, about any axis of the screen, for ever.
const rotX = (a) => [1, 0, 0, 0, Math.cos(a), -Math.sin(a), 0, Math.sin(a), Math.cos(a)];
const rotY = (a) => [Math.cos(a), 0, Math.sin(a), 0, 1, 0, -Math.sin(a), 0, Math.cos(a)];
const rotZ = (a) => [Math.cos(a), -Math.sin(a), 0, Math.sin(a), Math.cos(a), 0, 0, 0, 1];
const times = (a, b) => [0, 1, 2].flatMap((r) => [0, 1, 2].map((c) => a[r * 3] * b[c] + a[r * 3 + 1] * b[3 + c] + a[r * 3 + 2] * b[6 + c]));
/** The same turn with the rounding of many small steps taken out again: three rows of length one, square to each other. */
function squared(m) {
  const unit = (v) => { const l = Math.hypot(...v) || 1; return v.map((x) => x / l); };
  const x = unit(m.slice(0, 3));
  const dot = x[0] * m[3] + x[1] * m[4] + x[2] * m[5];
  const y = unit([m[3] - dot * x[0], m[4] - dot * x[1], m[5] - dot * x[2]]);
  return [...x, ...y, x[1] * y[2] - x[2] * y[1], x[2] * y[0] - x[0] * y[2], x[0] * y[1] - x[1] * y[0]];
}
// The sides a model can be looked at from, by name; `angled` is how it is shown first.
const VIEWS = {
  angled: () => times(rotX(0.42), rotY(-0.6)), front: () => rotY(0), back: () => rotY(Math.PI), left: () => rotY(Math.PI / 2),
  right: () => rotY(-Math.PI / 2), top: () => rotX(Math.PI / 2), bottom: () => rotX(-Math.PI / 2),
};
const ROLL_STEP = Math.PI / 12;                   // 15 degrees per press of a tilt button
const MAX_PAN = 1.6;                              // how far the model can be moved from the middle (its own radius is 1)
const FOV = 0.5;                                  // radians

const VERTEX = `
attribute vec3 aPosition;
attribute vec3 aNormal;
attribute vec4 aColour;
uniform mat4 uModel;
uniform mat4 uProjection;
varying vec3 vNormal;
varying vec4 vColour;
void main() {
  vec4 world = uModel * vec4(aPosition, 1.0);
  vNormal = (uModel * vec4(aNormal, 0.0)).xyz;
  vColour = aColour;
  gl_Position = uProjection * world;
}`;
// Two lamps and some ambient light; both sides of a triangle are lit, because not every file has its faces the right way round.
const FRAGMENT = `
precision mediump float;
uniform vec3 uColour;
uniform float uOwn;
varying vec3 vNormal;
varying vec4 vColour;
void main() {
  vec3 n = normalize(vNormal);
  if (!gl_FrontFacing) n = -n;
  float key = max(dot(n, normalize(vec3(0.45, 0.7, 0.75))), 0.0);
  float fill = max(dot(n, normalize(vec3(-0.7, 0.2, 0.5))), 0.0);
  float light = 0.34 + 0.62 * key + 0.2 * fill;
  // The colour the file names for this triangle, unless it names none or a colour was chosen for the whole item.
  vec3 base = mix(uColour, vColour.rgb, vColour.a * (1.0 - uOwn));
  // Black filament is still an object with a shape: a little light of its own on the edges and where the lamp hits, so that a
  // dark model does not become one black blot.
  float dark = 1.0 - clamp(dot(base, vec3(0.299, 0.587, 0.114)) * 4.0, 0.0, 1.0);        // 1 for black, 0 from a quarter grey up
  float rim = pow(1.0 - abs(n.z), 2.0);
  vec3 lift = vec3(0.10) * light + vec3(0.26) * rim + vec3(0.16) * pow(key, 5.0);
  gl_FragColor = vec4(base * light + lift * dark, 1.0);
}`;

/** The model of a print file: { positions, colours }. `positions` holds nine numbers per triangle (x, y, z of the three corners, in
 *  millimetres, Z up); `colours` four bytes per triangle (red, green, blue, and 255 or 0 for "the file names none"), or null when
 *  the file names no colours at all. `plate` asks for one build plate of a slicer project. The layout is the server's
 *  (printfile.triangles). */
export async function loadMesh(fileId, plate = '') {
  const { blob } = await downloadFile(`/api/print-files/${fileId}/mesh${plate ? `?plate=${plate}` : ''}`);
  const buffer = await blob.arrayBuffer();
  const head = new DataView(buffer);
  if (buffer.byteLength < 12 || head.getUint32(0, false) !== 0x50504d31) throw new Error(t('ai.view3d_unreadable'));       // "PPM1"
  const count = head.getUint32(4, true);
  const coloured = head.getUint32(8, true) === 1;
  if (buffer.byteLength < 12 + count * (coloured ? 40 : 36)) throw new Error(t('ai.view3d_unreadable'));
  return { positions: new Float32Array(buffer, 12, count * 9), colours: coloured ? new Uint8Array(buffer, 12 + count * 36, count * 4) : null };
}

/** The model centred in a ball of radius 1 with Y up (the printer's Z), and a normal per corner (flat faces). */
function prepare(mesh, colours) {
  const lo = [Infinity, Infinity, Infinity];
  const hi = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < mesh.length; i += 3) {
    for (let k = 0; k < 3; k += 1) {
      const v = mesh[i + k];
      if (v < lo[k]) lo[k] = v;
      if (v > hi[k]) hi[k] = v;
    }
  }
  const centre = [(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2];
  const radius = Math.hypot(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]) / 2 || 1;
  const positions = new Float32Array(mesh.length);
  const normals = new Float32Array(mesh.length);
  for (let i = 0; i < mesh.length; i += 3) {                       // (x, y, z) with Z up becomes (x, z, -y) with Y up
    positions[i] = (mesh[i] - centre[0]) / radius;
    positions[i + 1] = (mesh[i + 2] - centre[2]) / radius;
    positions[i + 2] = -(mesh[i + 1] - centre[1]) / radius;
  }
  for (let i = 0; i < positions.length; i += 9) {
    const ux = positions[i + 3] - positions[i], uy = positions[i + 4] - positions[i + 1], uz = positions[i + 5] - positions[i + 2];
    const vx = positions[i + 6] - positions[i], vy = positions[i + 7] - positions[i + 1], vz = positions[i + 8] - positions[i + 2];
    let nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
    const length = Math.hypot(nx, ny, nz) || 1;
    nx /= length; ny /= length; nz /= length;
    for (let k = 0; k < 9; k += 3) { normals[i + k] = nx; normals[i + k + 1] = ny; normals[i + k + 2] = nz; }
  }
  // One colour per triangle becomes one per corner. Without colours in the file every corner says "none" (all zeros): the buffer
  // is always there, so the shader never reads a switched-off attribute, which not every graphics driver does the same way.
  const shades = new Uint8Array(mesh.length / 3 * 4);
  if (colours) {
    for (let n = 0; n < colours.length; n += 4) {
      for (let k = 0; k < 3; k += 1) shades.set(colours.subarray(n, n + 4), n * 3 + k * 4);
    }
  }
  return { positions, normals, shades };
}

function compile(gl, type, source) {
  const shader = gl.createShader(type);
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(shader) || 'shader');
  return shader;
}

/** "#rrggbb" as three numbers from 0 to 1. */
function rgb(hex) {
  const value = /^#[0-9a-f]{6}$/i.test(hex) ? hex : '#8c96a3';
  return [1, 3, 5].map((at) => parseInt(value.slice(at, at + 2), 16) / 255);
}

/** The model on a canvas that can be turned all the way round in every direction, tilted, moved in the picture and zoomed. Returns
 *  { element, controls: { zoom, mode, side, tilt, reset }, setColour(hex, own), snapshot() } or null when the browser has no WebGL. The model is drawn in the colours its file names; `colour` is for what the file names none for, and with `own` it
 *  is the colour of the whole item instead. `snapshot()` resolves a PNG of what is shown. */
export function modelViewer({ positions: mesh, colours }, colour, own = false) {
  const canvas = h('canvas', { class: 'model-canvas', width: SIZE, height: SIZE, tabindex: '0', role: 'img', 'aria-label': t('ai.view3d_canvas') });
  // The drawing is kept after it is shown, so that a picture can be taken of it at any moment.
  const gl = canvas.getContext('webgl', { antialias: true, preserveDrawingBuffer: true });
  if (!gl) return null;
  const program = gl.createProgram();
  gl.attachShader(program, compile(gl, gl.VERTEX_SHADER, VERTEX));
  gl.attachShader(program, compile(gl, gl.FRAGMENT_SHADER, FRAGMENT));
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(program) || 'program');
  gl.useProgram(program);
  const { positions, normals, shades } = prepare(mesh, colours);
  for (const [name, data] of [['aPosition', positions], ['aNormal', normals]]) {
    const at = gl.getAttribLocation(program, name);
    gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
    gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
    gl.enableVertexAttribArray(at);
    gl.vertexAttribPointer(at, 3, gl.FLOAT, false, 0, 0);
  }
  const shade = gl.getAttribLocation(program, 'aColour');
  gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
  gl.bufferData(gl.ARRAY_BUFFER, shades, gl.STATIC_DRAW);
  gl.enableVertexAttribArray(shade);
  gl.vertexAttribPointer(shade, 4, gl.UNSIGNED_BYTE, true, 0, 0);
  const uniform = (name) => gl.getUniformLocation(program, name);
  gl.enable(gl.DEPTH_TEST);
  gl.viewport(0, 0, SIZE, SIZE);
  gl.clearColor(...BACKGROUND, 1);

  // The model can be turned any way round, tilted, moved in the picture and brought closer.
  const view = { turn: VIEWS.angled(), x: 0, y: 0, zoom: 1 };
  let tint = rgb(colour);
  let whole = own;
  let queued = false;
  const distanceNow = () => 1.12 / Math.sin(FOV / 2) / view.zoom;  // far enough for the whole ball to fit, then the zoom

  function draw() {
    queued = false;
    const m = view.turn;
    const distance = distanceNow();
    // The turn, then the place in the picture and the way from the camera. Column-major, as WebGL reads it.
    const model = new Float32Array([
      m[0], m[3], m[6], 0,
      m[1], m[4], m[7], 0,
      m[2], m[5], m[8], 0,
      view.x, view.y, -distance, 1]);
    const f = 1 / Math.tan(FOV / 2), near = Math.max(0.05, distance - 1.2), far = distance + 1.2;
    const projection = new Float32Array([
      f, 0, 0, 0,
      0, f, 0, 0,
      0, 0, (far + near) / (near - far), -1,
      0, 0, (2 * far * near) / (near - far), 0]);
    gl.uniformMatrix4fv(uniform('uModel'), false, model);
    gl.uniformMatrix4fv(uniform('uProjection'), false, projection);
    gl.uniform3fv(uniform('uColour'), tint);
    gl.uniform1f(uniform('uOwn'), whole ? 1 : 0);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    gl.drawArrays(gl.TRIANGLES, 0, positions.length / 3);
  }
  const redraw = () => { if (!queued) { queued = true; requestAnimationFrame(draw); } };

  const zoom = h('input', { type: 'range', min: '0.5', max: '3', step: '0.05', value: String(view.zoom), 'aria-label': t('ai.view3d_zoom'),
    oninput: () => { view.zoom = Number(zoom.value); redraw(); } });
  const setZoom = (value) => { view.zoom = Math.min(3, Math.max(0.5, value)); zoom.value = String(view.zoom); redraw(); };
  // Turning follows the screen: sideways about the upright of the screen, up and down about its level line, whatever way the
  // model already lies. So it goes all the way round in every direction.
  const turn = (dx, dy) => { view.turn = squared(times(rotX(dy), times(rotY(dx), view.turn))); redraw(); };
  const roll = (angle) => { view.turn = squared(times(rotZ(angle), view.turn)); redraw(); };
  const move = (dx, dy) => {
    view.x = Math.min(MAX_PAN, Math.max(-MAX_PAN, view.x + dx));
    view.y = Math.min(MAX_PAN, Math.max(-MAX_PAN, view.y + dy));
    redraw();
  };
  // a distance on screen (in the pixels of the page) as a distance where the model is
  const inModel = (pixels) => (pixels * 2 * distanceNow() * Math.tan(FOV / 2)) / (canvas.clientWidth || SIZE);

  // What one finger (or the mouse) does: turn, or move. Two fingers always do all of it: spread to zoom, twist to tilt, drag to move.
  let dragMoves = false;
  const modeButton = (moves, label) => h('button', { class: 'seg', type: 'button', 'aria-pressed': String(dragMoves === moves),
    onclick: () => { dragMoves = moves; for (const b of mode.children) b.setAttribute('aria-pressed', String(b === (moves ? mode.lastChild : mode.firstChild))); } }, t(label));
  const mode = h('div', { class: 'segmented', role: 'group', 'aria-label': t('ai.view3d_drag') });
  mode.append(modeButton(false, 'ai.view3d_drag_turn'), modeButton(true, 'ai.view3d_drag_move'));

  const fingers = new Map();
  let pair = null;                                                 // the two fingers as they were: how far apart, at what angle, where
  const pairNow = () => {
    const [a, b] = [...fingers.values()];
    return { spread: Math.hypot(a.x - b.x, a.y - b.y), angle: Math.atan2(b.y - a.y, b.x - a.x), x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
  };
  canvas.addEventListener('pointerdown', (e) => {
    canvas.setPointerCapture(e.pointerId);
    fingers.set(e.pointerId, { x: e.clientX, y: e.clientY, moves: dragMoves || e.shiftKey || e.button === 2 || e.button === 1 });
    pair = fingers.size === 2 ? pairNow() : null;
  });
  canvas.addEventListener('pointermove', (e) => {
    const was = fingers.get(e.pointerId);
    if (!was) return;
    fingers.set(e.pointerId, { ...was, x: e.clientX, y: e.clientY });
    if (fingers.size === 1) {
      if (was.moves) move(inModel(e.clientX - was.x), -inModel(e.clientY - was.y));
      else turn((e.clientX - was.x) * 0.012, (e.clientY - was.y) * 0.012);
    } else if (fingers.size === 2 && pair) {
      const now = pairNow();
      if (pair.spread > 0) setZoom(view.zoom * (now.spread / pair.spread));
      roll(pair.angle - now.angle);                                // the screen counts angles clockwise, the model the other way
      move(inModel(now.x - pair.x), -inModel(now.y - pair.y));
      pair = now;
    }
  });
  const lift = (e) => { fingers.delete(e.pointerId); pair = null; };
  canvas.addEventListener('pointerup', lift);
  canvas.addEventListener('pointercancel', lift);
  canvas.addEventListener('contextmenu', (e) => e.preventDefault());        // the right button moves the model
  canvas.addEventListener('keydown', (e) => {
    const step = 0.1;
    const arrows = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
    if (arrows[e.key]) {
      e.preventDefault();
      if (e.shiftKey) move(arrows[e.key][0] * 0.08, -arrows[e.key][1] * 0.08);
      else turn(arrows[e.key][0] * step, arrows[e.key][1] * step);
    } else if (e.key === 'q' || e.key === 'Q') { e.preventDefault(); roll(ROLL_STEP); }
    else if (e.key === 'e' || e.key === 'E') { e.preventDefault(); roll(-ROLL_STEP); }
    else if (e.key === '+' || e.key === '=') { e.preventDefault(); setZoom(view.zoom * 1.1); }
    else if (e.key === '-') { e.preventDefault(); setZoom(view.zoom / 1.1); }
  });

  // Straight onto a side, with the model back in the middle; from there it is turned on by hand.
  const side = h('select', { 'aria-label': t('ai.view3d_side'), onchange: () => { show(side.value); } },
    Object.keys(VIEWS).map((name) => h('option', { value: name }, t(`ai.view3d_side_${name}`))));
  const show = (name) => {
    Object.assign(view, { turn: VIEWS[name](), x: 0, y: 0, zoom: 1 });
    zoom.value = '1';
    side.value = name;
    redraw();
  };
  const tilt = h('div', { class: 'row' },
    h('button', { class: 'btn small', type: 'button', 'aria-label': t('ai.view3d_tilt_left'), title: t('ai.view3d_tilt_left'), onclick: () => roll(ROLL_STEP) }, '↺'),
    h('button', { class: 'btn small', type: 'button', 'aria-label': t('ai.view3d_tilt_right'), title: t('ai.view3d_tilt_right'), onclick: () => roll(-ROLL_STEP) }, '↻'));
  const reset = h('button', { class: 'btn small', type: 'button', onclick: () => show('angled') }, t('ai.view3d_reset'));
  draw();
  return {
    element: canvas,
    controls: { zoom, mode, side, tilt, reset },
    setColour(hex, asWhole = false) { tint = rgb(hex); whole = asWhole; redraw(); },
    snapshot() {
      draw();                                                        // what is on screen now, not what was there a frame ago
      return new Promise((resolve, reject) => canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error('snapshot'))), 'image/png'));
    },
  };
}
