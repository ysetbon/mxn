// Browser port of src/mxn_emoji_renderer.py (EmojiRenderer): animal endpoint markers,
// strand-name labels and the k rotation indicator, as composited by
// RenderMixin._render_emoji_overlay_layer. Strands are OpenStrandStudio JSON strands
// (start/end/control_points/layer_name/width/set_number); coordinates are world units.
// site/test_browser_markers.py checks the placement data against the Python renderer.

export const PADDING = 100;
export const EMOJI_SETS = ['default', 'fluent', 'twemoji', 'openmoji', 'joypixels'];
export const ANIMALS = [
  0x1F436, 0x1F431, 0x1F42D, 0x1F430, 0x1F994, 0x1F98A, 0x1F43B, 0x1F43C, 0x1F428, 0x1F42F,
  0x1F981, 0x1F42E, 0x1F437, 0x1F438, 0x1F435, 0x1F414, 0x1F427, 0x1F426, 0x1F424, 0x1F986,
  0x1F989, 0x1F987, 0x1F43A, 0x1F417, 0x1F434, 0x1F984, 0x1F41D, 0x1F41B, 0x1F98B, 0x1F40C,
  0x1F41E, 0x1F422, 0x1F40D, 0x1F98E, 0x1F996, 0x1F995, 0x1F419, 0x1F991, 0x1F990, 0x1F99E,
  0x1F980, 0x1F421, 0x1F420, 0x1F41F, 0x1F42C, 0x1F433, 0x1F40A, 0x1F993, 0x1F992, 0x1F9AC,
].map(c => String.fromCodePoint(c));
const PT = 96 / 72; // Qt point sizes on a 96 dpi QImage
const EMOJI_FONT = `${20 * PT}px "Segoe UI Emoji", "Apple Color Emoji", "Noto Color Emoji", sans-serif`;
const NAME_FONT = `bold ${7 * PT}px "Segoe UI", system-ui, sans-serif`;
const K_FONT = `bold ${14 * PT}px "Segoe UI", system-ui, sans-serif`;
const EMOJI_SIZE = 38, GLYPH_SS = 3;

// QPointF is falsy at (0, 0), which the Python checks rely on.
const present = p => !!p && (p.x !== 0 || p.y !== 0);
// Python round(): half to even.
const pyRound = v => { const f = Math.floor(v), d = v - f; return d > .5 ? f + 1 : d < .5 ? f : f % 2 ? f + 1 : f; };
export const directionOf = o => o.direction || (o.hand === 'rh' ? 'ccw' : 'cw');

/** RenderMixin._calculate_strands_bounds: start, end and both control points, padded. */
export function strandBounds(strands, padding = PADDING) {
  if (!strands.length) return {x: 0, y: 0, width: 1200, height: 900};
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const s of strands) for (const p of [s.start, s.end, ...(s.control_points || []).slice(0, 2).filter(present)]) {
    minX = Math.min(minX, p.x); maxX = Math.max(maxX, p.x); minY = Math.min(minY, p.y); maxY = Math.max(maxY, p.y);
  }
  return {x: minX - padding, y: minY - padding, width: maxX - minX + 2 * padding, height: maxY - minY + 2 * padding};
}

function contentOf(b) {
  const left = b.x + PADDING, top = b.y + PADDING, width = Math.max(1, b.width - 2 * PADDING), height = Math.max(1, b.height - 2 * PADDING);
  return {left, top, width, height, right: left + width, bottom: top + height};
}

export function makeLabels(count, base = ANIMALS) {
  const out = [], len = Math.max(1, base.length);
  for (let i = 0; i < count; i++) { const round = Math.floor(i / len); out.push(round ? `${base[i % len]}${round + 1}` : base[i % len]); }
  return out;
}

export function rotateLabels(labels, k, direction) {
  const n = labels.length;
  if (!n) return labels;
  let shift = ((k % n) + n) % n;
  if (direction === 'ccw') shift = (n - shift) % n;
  const out = new Array(n);
  labels.forEach((label, i) => { out[(i + shift) % n] = label; });
  return out;
}

export function computeSlotsFromRect(rect, m, n) {
  if (m < 1 || n < 1) return [];
  const top = [], right = [], bottom = [], left = [];
  for (let i = 0; i < m; i++) {
    const x = rect.left + (i + .5) * (rect.width / m);
    top.push({side: 'top', side_index: i, x, y: rect.top, nx: 0, ny: -1});
    bottom.push({side: 'bottom', side_index: i, x, y: rect.bottom, nx: 0, ny: 1});
  }
  for (let j = 0; j < n; j++) {
    const y = rect.top + (j + .5) * (rect.height / n);
    right.push({side: 'right', side_index: j, x: rect.right, y, nx: 1, ny: 0});
    left.push({side: 'left', side_index: j, x: rect.left, y, nx: -1, ny: 0});
  }
  return [...top, ...right, ...bottom.reverse(), ...left.reverse()].map((s, id) => ({...s, id}));
}

/** EmojiRenderer.compute_slots_from_strands. */
export function computeSlotsFromStrands(strands, bounds, m, n) {
  const c = contentOf(bounds), tol = 8, sides = {top: [], right: [], bottom: [], left: []};
  for (const s of strands) for (const p of [s.start, s.end]) {
    if (!present(p)) continue;
    if (Math.abs(p.y - c.top) <= tol) sides.top.push(p);
    else if (Math.abs(p.x - c.right) <= tol) sides.right.push(p);
    else if (Math.abs(p.y - c.bottom) <= tol) sides.bottom.push(p);
    else if (Math.abs(p.x - c.left) <= tol) sides.left.push(p);
  }
  if (sides.top.length !== m || sides.bottom.length !== m || sides.left.length !== n || sides.right.length !== n) return computeSlotsFromRect(c, m, n);
  const normal = {top: [0, -1], right: [1, 0], bottom: [0, 1], left: [-1, 0]};
  const slots = side => sides[side].slice().sort((a, b) => side === 'top' || side === 'bottom' ? a.x - b.x : a.y - b.y)
    .map((p, i) => ({side, side_index: i, x: p.x, y: p.y, nx: normal[side][0], ny: normal[side][1]}));
  return [...slots('top'), ...slots('right'), ...slots('bottom').reverse(), ...slots('left').reverse()].map((s, id) => ({...s, id}));
}

// Unique perimeter endpoints of the _2/_3 strands in clockwise order from the top-left
// corner. `merge` is the draw path's handling of a repeated slot (widest strand wins).
function perimeterEndpoints(strands, bounds, merge) {
  const c = contentOf(bounds), map = new Map();
  const perimeter = (side, x, y) => side === 'top' ? x - c.left : side === 'right' ? c.width + (y - c.top)
    : side === 'bottom' ? c.width + c.height + (c.right - x) : 2 * c.width + c.height + (c.bottom - y);
  for (const s of strands) {
    if (!present(s.start) || !present(s.end)) continue;
    const name = s.layer_name || s.name || '';
    if (name ? name.endsWith('_1') || !(name.endsWith('_2') || name.endsWith('_3')) : ![2, 3].includes(Math.trunc(Number(s.set_number ?? -1)))) continue;
    const {x: x1, y: y1} = s.start, {x: x2, y: y2} = s.end, horizontal = Math.abs(x2 - x1) >= Math.abs(y2 - y1);
    const forward = horizontal ? x1 <= x2 : y1 <= y2, [lo, hi] = horizontal ? ['left', 'right'] : ['top', 'bottom'];
    const ep = (x, y, side) => ({x, y, side, nx: side === 'left' ? -1 : side === 'right' ? 1 : 0, ny: side === 'top' ? -1 : side === 'bottom' ? 1 : 0});
    const pair = forward ? [[ep(x1, y1, lo), 'start'], [ep(x2, y2, hi), 'end']] : [[ep(x2, y2, lo), 'end'], [ep(x1, y1, hi), 'start']];
    const width = Number(s.width ?? 46);
    for (const [e, type] of pair) {
      // Slots snap to 4 px along their side, keyed like Python's str((side, n)) for the tie-break.
      const key = `('${e.side}', ${pyRound((e.side === 'top' || e.side === 'bottom' ? e.x : e.y) / 4)})`;
      const old = map.get(key);
      if (!old) map.set(key, {key, ep: e, t: perimeter(e.side, e.x, e.y), width, strandName: name, epType: type});
      else if (merge) {
        old.width = Math.max(old.width, width);
        if (!old.strandName) Object.assign(old, {strandName: name, epType: type});
      }
    }
  }
  return [...map.values()].sort((a, b) => a.t - b.t || (a.key < b.key ? -1 : a.key > b.key ? 1 : 0));
}

// k = 0 labels: top and right get unique animals, bottom and left mirror them.
function mirroredLabels(ordered) {
  const idx = {top: [], right: [], bottom: [], left: []};
  ordered.forEach((e, i) => idx[e.ep.side].push(i));
  const unique = makeLabels(idx.top.length + idx.right.length), top = unique.slice(0, idx.top.length), right = unique.slice(idx.top.length);
  const out = new Array(ordered.length).fill(null);
  const fill = (dst, labels) => dst.forEach((d, j) => { if (j < labels.length) out[d] = labels[j]; });
  fill(idx.top, top); fill(idx.right, right); fill(idx.bottom, [...top].reverse()); fill(idx.left, [...right].reverse());
  const remaining = out.flatMap((v, i) => v === null ? [i] : []), extra = makeLabels(remaining.length);
  remaining.forEach((i, j) => { out[i] = extra[j]; });
  return out;
}

/**
 * EmojiRenderer.freeze_emoji_assignments: the animal on each strand endpoint, keyed
 * `${strandName}|${start|end}`, so it can follow the strand after alignment moves it.
 * Returns null when there are no labelled endpoints.
 */
export function freezeAssignments({strands, bounds = strandBounds(strands), k = 0, ...o}) {
  const ordered = perimeterEndpoints(strands, bounds, false);
  if (!ordered.length) return null;
  const rotated = rotateLabels(mirroredLabels(ordered), Math.trunc(k), directionOf(o)), frozen = {};
  ordered.forEach((e, i) => { if (rotated[i]) frozen[`${e.strandName}|${e.epType}`] = rotated[i]; });
  return frozen;
}

function frozenLabel(frozen, name, type) {
  const direct = frozen[`${name}|${type}`];
  if (direct) return direct;
  for (const [key, value] of Object.entries(frozen)) if (key.slice(0, key.lastIndexOf('|')) === name) return value;
  return null;
}

let measurer;
function measure(font, text) {
  measurer ||= globalThis.OffscreenCanvas ? new OffscreenCanvas(1, 1).getContext('2d') : globalThis.document?.createElement('canvas').getContext('2d');
  if (!measurer) return null;
  measurer.font = font;
  measurer.textAlign = 'center';
  measurer.textBaseline = 'alphabetic';
  return measurer.measureText(text);
}
// Qt AlignCenter puts the baseline (ascent - descent) / 2 below the rect's center.
const baselineShift = m => (m.fontBoundingBoxAscent - m.fontBoundingBoxDescent) / 2;

/** _get_visual_text_extents: ink extents of the emoji font's glyph around its AlignCenter point. */
export function emojiExtents(txt) {
  const m = measure(EMOJI_FONT, txt);
  if (!m) return {left: 10 * PT, right: 10 * PT, top: 10 * PT, bottom: 10 * PT};
  const shift = baselineShift(m);
  return {left: m.actualBoundingBoxLeft, right: m.actualBoundingBoxRight, top: m.actualBoundingBoxAscent - shift, bottom: m.actualBoundingBoxDescent + shift};
}

/** QFontMetrics(name font).boundingRect(text) width and height, as integers. */
export function nameSize(text) {
  const m = measure(NAME_FONT, text);
  return m ? [Math.round(m.width), Math.round(m.fontBoundingBoxAscent + m.fontBoundingBoxDescent)] : [text.length * 6, 12];
}

/** Geometry of draw_rotation_indicator, in world units (icon parts in its 604×604 SVG space). */
export function rotationIndicatorLayout(bounds, k, direction, transparent = true) {
  const size = 96, margin = 20, cx = bounds.x + bounds.width - margin - size / 2, cy = bounds.y + margin + size / 2;
  const extra = transparent ? 8 : 5, capDeg = transparent ? 8 : 6, r = 215, wOut = 80 + 2 * extra;
  // The fill start moves back by capDeg along the clockwise span so the arc end stays put.
  const shift = -capDeg, start = 15 + shift, span = -320 - shift, rad = Math.PI / 180;
  const theta = start * rad, nx = Math.cos(theta), ny = -Math.sin(theta), tx = -Math.sin(theta), ty = -Math.cos(theta);
  const ext = r * Math.abs(shift) * rad * .3 * (shift > 0 ? -1 : 1), rIn = r - wOut / 2, rOut = r + wOut / 2;
  const pIn = [302 + rIn * nx, 302 + rIn * ny], pOut = [302 + rOut * nx, 302 + rOut * ny];
  const cos = Math.cos(25.1 * rad), sin = Math.sin(25.1 * rad);
  return {
    center: [cx, cy], size, origin: [cx - size / 2, cy - size / 2], scale: size / 604, mirrored: direction !== 'cw',
    arc: {rect: [87, 87, 430, 430], start16: Math.trunc(start * 16), span16: Math.trunc(span * 16)},
    arcOutlineWidth: wOut, arcWidth: 80,
    cap: [pIn, pOut, [pOut[0] + tx * ext, pOut[1] + ty * ext], [pIn[0] + tx * ext, pIn[1] + ty * ext]],
    arrowhead: [[0, -95], [0, 95], [190, 0]].map(([x, y]) => [393 + x * cos - y * sin, 107 + x * sin + y * cos]),
    arrowheadOutlineWidth: 2 * extra, text: k >= 0 ? `+${k}` : `${k}`, textOutlineWidth: transparent ? 4 : 2,
    outline: transparent ? 'rgb(255,255,255)' : null,
  };
}

/**
 * Placement of everything draw_endpoint_emojis and draw_rotation_indicator paint:
 * one item per labelled perimeter endpoint, with its animal and name boxes.
 * `frozen` (from freezeAssignments) keeps animals with strand endpoints instead of
 * assigning them by perimeter order. `extents`/`nameSize` measure fonts; tests inject them.
 */
export function computeMarkerLayout({strands, bounds = strandBounds(strands), k = 0, animals = true, names = false, frozen = null, transparent = true, extents = emojiExtents, nameSize: size = nameSize, ...o}) {
  const direction = directionOf(o), items = [];
  if (animals || names) {
    const ordered = perimeterEndpoints(strands, bounds, true), c = contentOf(bounds);
    const rotated = rotateLabels(mirroredLabels(ordered), Math.trunc(k), direction);
    ordered.forEach((e, i) => {
      const txt = frozen ? frozenLabel(frozen, e.strandName, e.epType) : rotated[i];
      if (!txt) return;
      const {side, nx, ny} = e.ep, outward = Math.min(e.width * .5 + 50 * .65 + 10, Math.max(24, PADDING * .8));
      // Project onto the content border so markers on one side line up.
      const bx = side === 'left' ? c.left : side === 'right' ? c.right : e.ep.x, by = side === 'top' ? c.top : side === 'bottom' ? c.bottom : e.ep.y;
      const x = bx + nx * outward, y = by + ny * outward, item = {slot: e.key, side, txt, strandName: e.strandName, epType: e.epType, x, y};
      if (animals) item.emoji = {x: x - EMOJI_SIZE / 2, y: y - EMOJI_SIZE / 2, w: EMOJI_SIZE, h: EMOJI_SIZE};
      if (names && e.strandName) {
        // Halfway between the endpoint and the emoji glyph's inner edge.
        const ext = extents(txt), inward = Math.abs(nx) > .5 ? (nx < 0 ? ext.right : ext.left) : (ny < 0 ? ext.bottom : ext.top);
        const mid = Math.max(1, outward - inward) * .5, cx = bx + nx * mid, cy = by + ny * mid, [w, h] = size(e.strandName);
        const nw = Math.max(1, w + 4), nh = Math.max(1, h + 2);
        item.name = {text: e.strandName, cx, cy, x: cx - nw / 2, y: cy - nh / 2, w: nw, h: nh};
      }
      items.push(item);
    });
  }
  return {bounds, direction, items, indicator: animals ? rotationIndicatorLayout(bounds, Math.trunc(k), direction, transparent) : null};
}

// --- Images: src/emoji_assets/<set>/<codepoints>.png, copied to emoji/<set>/ ---
const images = new Map(), glyphs = new Map();
const splitSuffix = txt => { const m = /^(.*?)(\d*)$/su.exec(txt || ''); return [m[1], m[2]]; };
const assetCode = base => [...base].map(ch => ch.codePointAt(0)).filter(cp => cp !== 0xFE0F).map(cp => cp.toString(16)).join('-');

// Animals the original asset sets lack; they fall back to the emoji font, as in Python.
const MISSING = new Set(['fluent/1f996']);

function loadImage(set, code) {
  const key = `${set}/${code}`;
  if (MISSING.has(key)) images.set(key, null);
  if (!images.has(key)) images.set(key, new Promise(resolve => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = new URL(`emoji/${set}/${code}.png`, import.meta.url).href;
  }).then(img => { images.set(key, img); return img; }));
  return images.get(key);
}

/** Load (once) the PNGs of `set` for the given labels (default: the whole animal pool). */
export async function preloadEmojiSet(set, labels = ANIMALS) {
  const codes = [...new Set(labels.map(txt => assetCode(splitSuffix(txt)[0])).filter(Boolean))];
  await Promise.all(codes.map(code => loadImage(set, code)));
}

function glyphCanvas(w, h) {
  if (globalThis.OffscreenCanvas) return new OffscreenCanvas(w, h);
  return Object.assign(document.createElement('canvas'), {width: w, height: h});
}

function textInRect(ctx, text, x, y, w, h) {
  ctx.textAlign = 'center';
  ctx.textBaseline = 'alphabetic';
  ctx.fillText(text, x + w / 2, y + h / 2 + baselineShift(ctx.measureText(text)));
}

// _get_emoji_glyph_image: the PNG cropped to its visible pixels, stretched into a 3×
// supersampled square, with any numeric suffix (labels beyond the 50-animal pool) on top.
function glyph(set, txt) {
  const key = `${set}/${txt}`;
  if (glyphs.has(key)) return glyphs.get(key);
  const [base, suffix] = splitSuffix(txt), img = images.get(`${set}/${assetCode(base)}`);
  if (!(img instanceof Image)) return null; // not loaded (yet); not cached so a later preload can fill it
  const size = EMOJI_SIZE * GLYPH_SS, out = glyphCanvas(size, size), ctx = out.getContext('2d');
  const probe = glyphCanvas(img.naturalWidth, img.naturalHeight).getContext('2d', {willReadFrequently: true});
  probe.drawImage(img, 0, 0);
  const a = probe.getImageData(0, 0, img.naturalWidth, img.naturalHeight).data;
  let x1 = Infinity, y1 = Infinity, x2 = -1, y2 = -1;
  for (let y = 0; y < img.naturalHeight; y++) for (let x = 0; x < img.naturalWidth; x++) if (a[(y * img.naturalWidth + x) * 4 + 3] > 1) {
    if (x < x1) x1 = x; if (x > x2) x2 = x; if (y < y1) y1 = y; if (y > y2) y2 = y;
  }
  ctx.imageSmoothingQuality = 'high';
  if (x2 < 0) ctx.drawImage(img, 0, 0, size, size);
  else ctx.drawImage(img, x1, y1, x2 - x1 + 1, y2 - y1 + 1, 0, 0, size, size);
  if (suffix) {
    ctx.font = `bold ${Math.max(8, Math.trunc(size * .18)) * PT}px "Segoe UI", system-ui, sans-serif`;
    const [rx, ry, rw, rh] = [size * .58, size * .56, size * .4, size * .4];
    ctx.fillStyle = 'rgba(0,0,0,0.902)'; textInRect(ctx, suffix, rx - 2, ry - 2, rw + 2, rh + 2);
    ctx.fillStyle = '#fff'; textInRect(ctx, suffix, rx, ry, rw, rh);
  }
  glyphs.set(key, out);
  return out;
}

function drawIndicator(ctx, g) {
  const outline = g.outline, [ax, ay, aw] = g.arc.rect, r = aw / 2, rad = Math.PI / 180;
  const arc = width => {
    ctx.lineWidth = width; ctx.lineCap = 'butt'; ctx.beginPath();
    // Qt angles are counter-clockwise on screen; canvas angles are clockwise.
    ctx.arc(ax + r, ay + r, r, -g.arc.start16 / 16 * rad, -(g.arc.start16 + g.arc.span16) / 16 * rad, g.arc.span16 > 0);
    ctx.stroke();
  };
  const poly = pts => { ctx.beginPath(); pts.forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)); ctx.closePath(); };
  ctx.save();
  ctx.translate(...g.origin); ctx.scale(g.scale, g.scale);
  if (g.mirrored) { ctx.translate(604, 0); ctx.scale(-1, 1); }
  if (outline) {
    ctx.strokeStyle = outline; arc(g.arcOutlineWidth);
    ctx.fillStyle = outline; poly(g.cap); ctx.fill();
  }
  ctx.strokeStyle = '#000'; arc(g.arcWidth);
  poly(g.arrowhead);
  if (outline) { ctx.strokeStyle = outline; ctx.lineWidth = g.arrowheadOutlineWidth; ctx.lineJoin = 'round'; ctx.lineCap = 'round'; ctx.stroke(); }
  ctx.fillStyle = '#000'; ctx.fill();
  ctx.restore();
  // The signed k, centered on its ink bounds like the QPainterPath text.
  ctx.save();
  ctx.font = K_FONT; ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
  const m = ctx.measureText(g.text), x = g.center[0] - (m.actualBoundingBoxRight - m.actualBoundingBoxLeft) / 2, y = g.center[1] - (m.actualBoundingBoxDescent - m.actualBoundingBoxAscent) / 2;
  if (outline) { ctx.strokeStyle = outline; ctx.lineWidth = g.textOutlineWidth; ctx.lineJoin = 'round'; ctx.strokeText(g.text, x, y); }
  ctx.fillStyle = '#000'; ctx.fillText(g.text, x, y);
  ctx.restore();
}

/**
 * Paint markers, labels and the rotation indicator over already-rendered strands.
 * World point p lands on pixel (p - bounds.origin) * scale. Call preloadEmojiSet first;
 * animals whose PNG is missing fall back to the emoji font, as in Python.
 */
export function drawMarkers(ctx, {scale = 1, emojiSet = 'fluent', ...options}, layout = computeMarkerLayout(options)) {
  const b = layout.bounds;
  ctx.save();
  ctx.setTransform(scale, 0, 0, scale, -b.x * scale, -b.y * scale);
  ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = 'high';
  for (const item of layout.items) {
    if (item.emoji) {
      const {x, y, w, h} = item.emoji, image = glyph(emojiSet, item.txt);
      if (image) ctx.drawImage(image, x, y, w, h);
      else { ctx.font = EMOJI_FONT; ctx.fillStyle = '#000'; textInRect(ctx, item.txt, x, y, w, h); }
    }
    if (item.name) {
      const {x, y, w, h, text} = item.name;
      ctx.fillStyle = 'rgba(0,0,0,0.588)'; ctx.beginPath(); ctx.roundRect(x - 1, y - 1, w + 2, h + 2, 2); ctx.fill();
      ctx.font = NAME_FONT; ctx.fillStyle = '#fff'; textInRect(ctx, text, x, y, w, h);
    }
  }
  if (layout.indicator) drawIndicator(ctx, layout.indicator);
  ctx.restore();
}
