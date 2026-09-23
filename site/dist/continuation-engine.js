// Browser port of the Continuation workflow's computation: generate_json, the k
// orders, the alignment preview and the CPU alignment search of
// src/mxn_lh_continuation.py (src/mxn_rh_continuation.py runs the same code with
// its own order helpers), plus Workflow.run/pairs/describe of site/workflow.py
// without the rendering. Pure functions, no DOM; site/test_browser_continuation.py
// checks it against Python. Sums follow CPython 3.11 (left to right) and numpy
// (pairwise) so gap statistics match bit for bit up to libm differences.

const GRID = 42, GAP = GRID * (2 / 3), STRIDE = 4 * GAP, CX = 1274 - GRID, CY = 434 - GRID, TAIL = GRID + GRID / 3;
const BLACK = () => ({r: 0, g: 0, b: 0, a: 255});
// Python picks random colors for sets 3+; the site repaints every set anyway.
const FIXED = {1: {r: 255, g: 255, b: 255, a: 255}, 2: {r: 85, g: 170, b: 0, a: 255}};
const colorFor = set => ({...(FIXED[set] || {r: 128, g: 128, b: 128, a: 255})});
const RAD2DEG = 180 / Math.PI, DEG2RAD = Math.PI / 180;
const pyMod = (a, b) => { const r = a % b; return r !== 0 && (r < 0) !== (b < 0) ? r + b : r; };
const range = (a, b) => Array.from({length: Math.max(0, b - a)}, (_, i) => a + i);
const clone = x => JSON.parse(JSON.stringify(x));
const pt = p => ({x: p.x, y: p.y});
const mid = (a, b) => ({x: (a.x + b.x) / 2, y: (a.y + b.y) / 2});
const pySum = a => a.reduce((s, x) => s + x, 0);

/** Python's format(x, '.{f}f'): round half to even on exact binary ties, unlike toFixed. */
export function pyFixed(x, f) {
  if (!Number.isFinite(x)) return x > 0 ? 'inf' : x < 0 ? '-inf' : 'nan';
  const t = x * 2 * 10 ** f;
  if (Number.isInteger(t) && Math.abs(t % 2) === 1) {
    const lo = (t - 1) / 2, n = lo % 2 === 0 ? lo : lo + 1;
    return (n / 10 ** f).toFixed(f).replace(/^0/, x < 0 && n === 0 ? '-0' : '0');
  }
  const s = x.toFixed(f);
  return Object.is(x, -0) ? '-' + s : s;
}
const pyRound = (x, f) => Number.isFinite(x) ? Number(pyFixed(x, f)) : x;
const commas = v => String(v).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
const tupleRepr = t => t.length === 1 ? `(${t[0]},)` : `(${t.join(', ')})`;

// ---------------------------------------------------------------------------
// Orders (get_starting_order*, get_horizontal_order_k, get_vertical_order_k,
// get_mask_order_k of both hands)
// ---------------------------------------------------------------------------

function startingOrders(m, n, hand) {
  const V = range(n + 1, n + m + 1), H = range(1, n + 1), rV = [...V].reverse(), rH = [...H].reverse();
  const f = (a, s) => a.map(i => `${i}_${s}`);
  return hand === 'lh'
    ? [[...f(rV, 2), ...f(H, 2), ...f(V, 3), ...f(rH, 3)], [...f(V, 2), ...f(H, 3), ...f(rV, 3), ...f(rH, 2)]]
    : [[...f(V, 3), ...f(H, 3), ...f(rV, 2), ...f(rH, 2)], [...f(rV, 3), ...f(H, 2), ...f(V, 2), ...f(rH, 3)]];
}

/** get_horizontal_order_k (axis 'h') / get_vertical_order_k (axis 'v') of mxn_<hand>_continuation. */
export function orderK(m, n, k, direction, hand, axis) {
  const total = 2 * (m + n), P = 4 * (m + n);
  const sets = axis === 'h' ? range(1, n + 1) : range(n + 1, n + m + 1);
  const [a, b] = axis === 'h' && hand === 'lh' ? ['2', '3'] : ['3', '2'];
  const k0 = sets.flatMap(i => [`${i}_${a}`, `${i}_${b}`]), k1 = sets.flatMap(i => [`${i}_${b}`, `${i}_${a}`]);
  if (hand === 'lh') {
    if (direction === 'ccw') k = -k;
    if (k === 0) return k0;
    if (k === 1) return k1;
    if (k < 0) k = P + k;
  } else {
    k = direction === 'cw' ? pyMod(-k, P) : pyMod(k, P);
    if (k === 0) return k0;
    if (k === 1) return k1;
  }
  const [full, opposite] = startingOrders(m, n, hand);
  if (pyMod(k, 2) === 0) {
    const shift = Math.floor(k / 2);
    return k0.map(s => full.includes(s) ? full[pyMod(full.indexOf(s) - shift, total)] : s);
  }
  const shift = Math.floor((k - 1) / 2);
  return k1.map(s => opposite.includes(s) ? opposite[pyMod(opposite.indexOf(s) + shift, total)] : s);
}

function maskOrder(m, n, k, direction, hand) {
  const h = orderK(m, n, k, direction, hand, 'h'), v = orderK(m, n, k, direction, hand, 'v');
  if (!h.length || !v.length) return [];
  const even = h.filter((_, i) => i % 2 === 0), odd = h.filter((_, i) => i % 2 === 1);
  // LH: odd k pairs even vertical indexes with even horizontal ones; RH the reverse.
  const firstEven = (hand === 'lh') === (pyMod(k, 2) === 1);
  return v.flatMap((label, i) => ((i % 2 === 0) === firstEven ? even : odd).map(x => `${label}_${x}`));
}

const isMaxK = (m, n, k) => k === m + n && m !== n;
/** _get_effective_direction_for_max_k_special: LH uses the CCW path, RH the CW path. */
const effectiveDirection = (m, n, k, direction, hand) => isMaxK(m, n, k) ? (hand === 'lh' ? 'ccw' : 'cw') : direction;
const to45 = label => { const [set, s] = label.split('_'); return `${set}_${s === '2' ? '4' : '5'}`; };

/** _build_k_based_strand_sets: the k-based _4/_5 H and V orders. */
export function kOrders(m, n, k, direction, hand) {
  const d = effectiveDirection(m, n, k, direction, hand);
  return {h: orderK(m, n, k, d, hand, 'h').map(to45), v: orderK(m, n, k, d, hand, 'v').map(to45)};
}

export const directionFor = hand => hand === 'lh' ? 'cw' : 'ccw';

/** Workflow.pairs: opposite _2/_3 endpoint pairs, outermost first. */
export function pairs(m, n, k, hand) {
  const direction = directionFor(hand), out = [];
  for (const [axis, a] of [['H', 'h'], ['V', 'v']]) {
    const order = orderK(m, n, k, direction, hand, a);
    for (let i = 0; i < Math.floor(order.length / 2); i++) {
      const labels = [order[i], order[order.length - 1 - i]];
      out.push({axis, labels, key: labels.join('|')});
    }
  }
  return out;
}

// ---------------------------------------------------------------------------
// Continuation generator (generate_json of both hands)
// ---------------------------------------------------------------------------

/** compute_emoji_pairings: where each _2/_3 end's matching emoji sits. */
function emojiPairings(strands, k, direction) {
  const eps = [];
  for (const s of strands) {
    if (s.type !== 'AttachedStrand' || !(s.layer_name.endsWith('_2') || s.layer_name.endsWith('_3'))) continue;
    const {x: sx, y: sy} = s.start, {x: ex, y: ey} = s.end, dx = ex - sx, dy = ey - sy;
    const [a, b] = Math.abs(dx) >= Math.abs(dy) ? (sx <= ex ? ['left', 'right'] : ['right', 'left'])
      : (sy <= ey ? ['top', 'bottom'] : ['bottom', 'top']);
    eps.push({layer: s.layer_name, type: 'start', x: sx, y: sy, side: a}, {layer: s.layer_name, type: 'end', x: ex, y: ey, side: b});
  }
  if (!eps.length) return {};
  const side = (name, key) => eps.filter(e => e.side === name).sort((p, q) => p[key] - q[key]);
  const top = side('top', 'x'), right = side('right', 'y'), bottom = side('bottom', 'x'), left = side('left', 'y');
  const perimeter = [...top, ...right, ...[...bottom].reverse(), ...[...left].reverse()];
  const topLabels = range(0, top.length), rightLabels = range(top.length, top.length + right.length);
  const base = [...topLabels, ...rightLabels, ...topLabels.slice(0, bottom.length).reverse(), ...rightLabels.slice(0, left.length).reverse()];
  // rotate_labels
  const total = base.length;
  let shift = pyMod(k, total);
  if (direction === 'ccw') shift = pyMod(total - shift, total);
  const rotated = new Array(total);
  base.forEach((label, i) => { rotated[(i + shift) % total] = label; });
  perimeter.forEach((e, i) => { e.emoji = rotated[i]; });
  const out = {};
  for (const e of perimeter) {
    if (e.type !== 'end') continue;
    const other = perimeter.find(o => !(o.layer === e.layer && o.type === e.type) && o.emoji === e.emoji);
    if (other) out[`${e.layer}_end`] = {x: other.x, y: other.y};
  }
  return out;
}

function strandBase(start, end, color, layer, set, type = 'Strand', attachedTo = null, side = null) {
  const s = {
    type, index: 0, start, end, width: 46, color, stroke_color: BLACK(), stroke_width: 4,
    has_circles: type === 'Strand' ? [true, true] : type === 'AttachedStrand' ? [true, false] : [false, false],
    layer_name: layer, set_number: set, is_first_strand: type === 'Strand', is_start_side: type !== 'AttachedStrand',
    start_line_visible: true, end_line_visible: true, is_hidden: false,
    start_extension_visible: false, end_extension_visible: false,
    start_arrow_visible: false, end_arrow_visible: false, full_arrow_visible: false,
    shadow_only: false, closed_connections: [false, false], arrow_color: null,
    arrow_transparency: 100, arrow_texture: 'none', arrow_shaft_style: 'solid',
    arrow_head_visible: true, arrow_casts_shadow: false, knot_connections: {},
    circle_stroke_color: BLACK(), start_circle_stroke_color: BLACK(), end_circle_stroke_color: BLACK(),
    control_points: type === 'MaskedStrand' ? [null, null] : [pt(start), pt(end)],
    control_point_center: mid(start, end), control_point_center_locked: false,
    bias_control: {triangle_bias: .5, circle_bias: .5, triangle_position: null, circle_position: null},
    triangle_has_moved: false, control_point2_shown: false, control_point2_activated: false,
  };
  if (attachedTo) Object.assign(s, {attached_to: attachedTo, attachment_side: side, angle: 0, length: 0, is_start_side: false});
  if (type === 'MaskedStrand') s.deletion_rectangles = [];
  return s;
}

function masked(v, layer, set, first, second) {
  // Python passes v's start/end dicts themselves, so a later retraction of a
  // vertical tail's end moves its mask too; sharing the objects reproduces that.
  return Object.assign(strandBase(v.start, v.end, v.color, layer, set, 'MaskedStrand'),
    {first_selected_strand: first, second_selected_strand: second});
}

/** mxn_<hand>_continuation.generate_json(m, n, k, 'cw' for LH / 'ccw' for RH), parsed. */
export function continuationDocument(m, n, k = 0, hand = 'lh', direction = directionFor(hand)) {
  const gap = hand === 'lh' ? GAP : -GAP;
  const s1 = [], s2 = [], s3 = [];
  const hTop = CY - (n - 1) / 2 * STRIDE, hBottom = CY + (n - 1) / 2 * STRIDE;
  for (let i = 0; i < m; i++) {
    const cx = CX + (i - (m - 1) / 2) * STRIDE, set = n + 1 + i, main = `${set}_1`, color = colorFor(set);
    const start = {x: cx + gap, y: hBottom + STRIDE / 2}, end = {x: cx - gap, y: hTop - STRIDE / 2};
    s1.push(strandBase(start, end, color, main, set));
    // LH: _3 leaves the vertical's end and _2 its start; RH swaps them.
    const [endTail, startTail] = hand === 'lh' ? [s3, s2] : [s2, s3];
    endTail.push(strandBase(end, {x: end.x, y: start.y + TAIL}, color, `${set}_${hand === 'lh' ? 3 : 2}`, set, 'AttachedStrand', main, 1));
    startTail.push(strandBase(start, {x: start.x, y: end.y - TAIL}, color, `${set}_${hand === 'lh' ? 2 : 3}`, set, 'AttachedStrand', main, 0));
  }
  const halfWidth = ((m - 1) * STRIDE + STRIDE) / 2;
  for (let i = 0; i < n; i++) {
    const cy = CY + (i - (n - 1) / 2) * STRIDE, set = 1 + i, main = `${set}_1`, color = colorFor(set);
    const start = {x: CX - halfWidth, y: cy + gap}, end = {x: CX + halfWidth, y: cy - gap};
    s1.push(strandBase(start, end, color, main, set));
    s2.push(strandBase(end, {x: start.x - TAIL, y: end.y}, color, `${set}_2`, set, 'AttachedStrand', main, 1));
    s3.push(strandBase(start, {x: end.x + TAIL, y: start.y}, color, `${set}_3`, set, 'AttachedStrand', main, 0));
  }
  const base = [...s1, ...s2, ...s3];
  const tails = base.filter(s => s.type === 'AttachedStrand');
  const baseMasked = [];
  for (const v of tails.filter(s => s.set_number > n)) for (const h of tails.filter(s => s.set_number <= n)) {
    const a = v.layer_name.slice(-2), b = h.layer_name.slice(-2);
    if ((a === '_2' && b === '_3') || (a === '_3' && b === '_2'))
      baseMasked.push(masked(v, `${v.layer_name}_${h.layer_name}`, Number(`${v.set_number}${h.set_number}`), v.layer_name, h.layer_name));
  }

  const eff = effectiveDirection(m, n, k, direction, hand);
  const pairings = emojiPairings(base, k, eff);
  const vOrder = orderK(m, n, k, eff, hand, 'v').map(to45), hOrder = orderK(m, n, k, eff, hand, 'h').map(to45);
  const special = {};
  if (isMaxK(m, n, k) && n > m) {
    const gapAbs = Math.abs(gap), lookup = Object.fromEntries(tails.map(s => [s.layer_name, s]));
    const startY = layer => lookup[`${layer.slice(0, -1)}${layer.endsWith('_4') ? 2 : 3}`].end.y;
    const hBase = suffix => tails.filter(s => s.set_number <= n && s.layer_name.endsWith(suffix)).map(s => s.end.y);
    const [innerTop, innerBottom] = hand === 'lh' ? ['_2', '_3'] : ['_3', '_2'];
    const topInner = Math.min(...hBase(innerTop)), bottomInner = Math.max(...hBase(innerBottom));
    const topOuter = topInner - TAIL, bottomOuter = bottomInner + TAIL;
    const horizontal = order => order.filter(l => Number(l.split('_')[0]) <= n);
    const straight = horizontal(vOrder), side = horizontal(hOrder);
    const st4 = straight.filter(l => l.endsWith('_4')), st5 = straight.filter(l => l.endsWith('_5'));
    const sd4 = side.filter(l => l.endsWith('_4')), sd5 = side.filter(l => l.endsWith('_5'));
    const x4 = sd4.map((_, i) => CX - (2 * m + 1 + 2 * i) * gapAbs);
    const x5 = sd5.map((_, i) => 2 * m + 1 + 2 * i).reverse().map(mult => CX + mult * gapAbs);
    const minY = list => { if (!list.length) throw new Error('min() arg is an empty sequence'); return Math.min(...list.map(startY)); };
    if (sd4.length) {
      const least = minY(st4), single = st4.length === 1;
      sd4.forEach((l, i) => { const y = startY(l); special[l] = {start: {x: x4[i], y}, end: {x: x4[i], y: y < least ? (single ? bottomOuter : bottomInner) : topOuter}}; });
    }
    if (sd5.length) {
      const least = minY(st5), single = st5.length === 1;
      sd5.forEach((l, i) => { const y = startY(l); special[l] = {start: {x: x5[i], y}, end: {x: x5[i], y: y < least ? bottomOuter : (single ? topOuter : topInner)}}; });
    }
    let left, right;
    if (hand === 'lh') {
      left = x4.length ? Math.min(...x4) - gapAbs : CX - (2 * m + 2) * gapAbs;
      right = x5.length ? Math.max(...x5) + gapAbs : CX + (2 * m + 2) * gapAbs;
    } else {
      left = x4.length ? Math.min(...x4) - (x4.length === 1 ? 2 * gapAbs : gapAbs) : CX - (3 * m + 2) * gapAbs;
      right = x5.length ? Math.max(...x5) + (x5.length === 1 ? 2 * gapAbs : gapAbs) : CX + (3 * m + 2) * gapAbs;
    }
    for (const l of st4) { const y = startY(l); special[l] = {start: {x: left, y}, end: {x: right + gapAbs, y}}; }
    for (const l of st5) { const y = startY(l); special[l] = {start: {x: right, y}, end: {x: left - gapAbs, y}}; }
  }

  const made = {};
  for (const s of tails) {
    const four = s.layer_name.endsWith('_2'), layer = `${s.set_number}_${four ? 4 : 5}`, layout = special[layer];
    let start, end;
    if (layout) {
      s.end.x = layout.start.x; s.end.y = layout.start.y;
      start = pt(layout.start); end = pt(layout.end);
    } else {
      // Retract the tail's end by 52 px (the default extension); _4/_5 start there.
      const dx = s.end.x - s.start.x, dy = s.end.y - s.start.y, length = Math.sqrt(dx * dx + dy * dy);
      if (length > .001) { s.end.x -= dx / length * 52; s.end.y -= dy / length * 52; }
      start = pt(s.end);
      const target = pairings[`${s.layer_name}_end`] || start;
      // extend_endpoint: reach tail_offset beyond the paired emoji position.
      const ex = target.x - start.x, ey = target.y - start.y, len = Math.sqrt(ex * ex + ey * ey);
      end = len < .001 ? pt(target) : {x: target.x + ex / len * TAIL, y: target.y + ey / len * TAIL};
    }
    if (s.control_points && s.control_points[1] != null) s.control_points[1] = pt(s.end);
    s.control_point_center = mid(s.start, s.end);
    made[layer] = strandBase(start, end, s.color, layer, s.set_number, 'AttachedStrand', s.layer_name, 1);
  }
  const continuation = [...vOrder, ...hOrder].filter(l => l in made).map(l => made[l]);
  const lookup = Object.fromEntries(continuation.map(s => [s.layer_name, s]));
  const contMasked = [];
  for (const entry of maskOrder(m, n, k, eff, hand)) {
    const parts = entry.split('_');
    if (parts.length !== 4) continue;
    const v = `${parts[0]}_${parts[1] === '2' ? 4 : 5}`, h = `${parts[2]}_${parts[3] === '2' ? 4 : 5}`;
    if (!lookup[v] || !lookup[h]) continue;
    contMasked.push(masked(lookup[v], `${v}_${h}`, Number(`${parts[0]}${parts[2]}`), v, h));
  }
  const strands = [...base, ...baseMasked, ...continuation, ...contMasked];
  strands.forEach((s, i) => { s.index = i; });
  return clone({
    type: 'OpenStrandStudioHistory', version: 1, current_step: 2, max_step: 2,
    states: [1, 2].map(step => ({step, data: {
      strands, groups: {}, selected_strand_name: null, locked_layers: [], lock_mode: false,
      shadow_enabled: false, show_control_points: step === 1, shadow_overrides: {},
    }})),
  });
}

// ---------------------------------------------------------------------------
// Document helpers (ui_utils._get_active_strands / _set_active_strands)
// ---------------------------------------------------------------------------

function activeState(doc) {
  if (!doc || doc.type !== 'OpenStrandStudioHistory') return null;
  const step = doc.current_step ?? 1;
  return (doc.states || []).find(s => s && s.step === step && s.data && typeof s.data === 'object') || null;
}
export function getActiveStrands(doc) {
  const state = activeState(doc);
  return state ? state.data.strands || [] : (doc && doc.strands) || [];
}
export function setActiveStrands(doc, strands) {
  const state = activeState(doc);
  if (state) state.data.strands = strands; else if (doc) doc.strands = strands;
}

// ---------------------------------------------------------------------------
// Angle ranges (_compute_pair_angle_range, get_parallel_alignment_preview)
// ---------------------------------------------------------------------------

const nearRef = (a, ref) => ref + (pyMod(a - ref + 180, 360) - 180);

/** _compute_pair_angle_range over strand angles in degrees; returns [initial, min, max]. */
function pairAngleRange(angles, mode, numOpposite) {
  const ref = angles[0];
  if (mode !== 'uniform' && mode !== 'avg_gaussian' && mode !== 'gaussian') return [ref, ref - 20, ref + 20];
  const num = angles.length, pairAngles = [];
  for (let i = 0; i < Math.floor(num / 2); i++) {
    const l = nearRef(angles[i], ref), r = nearRef(angles[num - 1 - i], ref);
    pairAngles.push(Math.abs(l - ref) <= Math.abs(r - ref) ? l : r);
  }
  if (num % 2 === 1) {
    let a = nearRef(angles[Math.floor(num / 2)], ref);
    if (Math.abs(a - ref) > 90) a -= 180;
    pairAngles.push(nearRef(a, ref));
  }
  // _compute_pair_angle_averages
  const uniform = pySum(pairAngles) / pairAngles.length;
  let gaussian = pairAngles[0];
  if (pairAngles.length > 1) {
    const count = pairAngles.length, sigma = Math.max(count / 2, 1), center = count - 1;
    let weights = pairAngles.map((_, i) => Math.exp(-.5 * ((i - center) / sigma) ** 2));
    const total = pySum(weights);
    weights = weights.map(w => w / total);
    gaussian = pySum(pairAngles.map((a, i) => a * weights[i]));
  }
  if (mode === 'uniform') return [uniform, uniform - 20, uniform + 20];
  let lo = Math.min(uniform, gaussian), hi = Math.max(uniform, gaussian);
  const minHalf = Math.atan(1 / Math.max(pairAngles.length, numOpposite)) * RAD2DEG / 2;
  if ((hi - lo) / 2 < minHalf) { const c = (lo + hi) / 2; lo = c - minHalf; hi = c + minHalf; }
  return [(lo + hi) / 2, lo, hi];
}
const angleOf = (s, t) => Math.atan2(t.y - s.y, t.x - s.x) * RAD2DEG;

/**
 * get_parallel_alignment_preview for the hand's ordering. mode 'custom' reports
 * first_strand ranges replaced by custom = {hMin, hMax, vMin, vMax}, as
 * Workflow.describe does.
 */
export function alignmentPreview(strands, m, n, k, hand, angleMode = 'first_strand', custom = null) {
  const mode = angleMode === 'custom' ? 'first_strand' : angleMode;
  const orders = kOrders(m, n, k, directionFor(hand), hand), out = {horizontal: null, vertical: null};
  const collect = order => {
    const names = new Set(order), list = [];
    for (const s of strands) {
      if (s.type !== 'AttachedStrand' || !names.has(s.layer_name)) continue;
      if (!(s.layer_name.endsWith('_4') || s.layer_name.endsWith('_5'))) continue;
      const base = s.layer_name.slice(0, s.layer_name.lastIndexOf('_')) + (s.layer_name.endsWith('_4') ? '_2' : '_3');
      if (strands.some(x => x.layer_name === base)) list.push({strand: s, start: pt(s.start), target: pt(s.end)});
    }
    const index = new Map(order.map((name, i) => [name, i]));
    if (list.length >= 2) list.sort((a, b) => (index.get(a.strand.layer_name) ?? 999) - (index.get(b.strand.layer_name) ?? 999));
    return list;
  };
  const h = collect(orders.h), v = collect(orders.v);
  const pairsOf = list => list.length >= 2 ? Math.floor((list.length + 1) / 2) : 1;
  for (const [name, list, opposite, axis] of [['horizontal', h, pairsOf(v), 'h'], ['vertical', v, pairsOf(h), 'v']]) {
    if (list.length < 2) continue;
    const [initial, lo, hi] = pairAngleRange(list.map(e => angleOf(e.start, e.target)), mode, opposite);
    const first = list[0], last = list[list.length - 1];
    out[name] = {
      first_start: first.start, first_target: first.target, last_start: last.start, last_target: last.target,
      initial_angle: initial, angle_min: lo, angle_max: hi,
      first_name: first.strand.layer_name, last_name: last.strand.layer_name,
      strand_order: list.map(e => e.strand.layer_name),
    };
    if (angleMode === 'custom' && custom) Object.assign(out[name], {angle_min: custom[axis + 'Min'], angle_max: custom[axis + 'Max']});
  }
  return out;
}

// ---------------------------------------------------------------------------
// Manual pair extensions (inline in Workflow.run)
// ---------------------------------------------------------------------------

/** Move each pair's _2/_3 end and _4/_5 start `value` px along the _2/_3 direction, in place. */
export function applyExtensions(strands, pairList, extensions = {}) {
  if (!extensions || typeof extensions !== 'object' || Array.isArray(extensions)
      || Object.keys(extensions).some(key => !pairList.some(p => p.key === key))) throw new Error('Invalid opposite pair');
  const lookup = {};
  for (const s of strands) lookup[s.layer_name] = s;
  for (const pair of pairList) {
    const value = extensions[pair.key] ?? 0;
    if (typeof value !== 'number' || !Number.isFinite(value) || value < -200 || value > 500)
      throw new Error('Manual extension must be between -200 and 500 px');
    for (const label of pair.labels) {
      const base = lookup[label], tail = lookup[label.slice(0, -1) + (label.endsWith('2') ? '4' : '5')];
      if (!base || !tail || !value) continue;
      const dx = base.end.x - base.start.x, dy = base.end.y - base.start.y, length = Math.hypot(dx, dy);
      if (length < .001) continue;
      const point = {x: tail.start.x + value * dx / length, y: tail.start.y + value * dy / length};
      tail.start = pt(point); base.end = pt(point);
      for (const [strand, index] of [[tail, 0], [base, 1]]) {
        if ((strand.control_points || []).length > index) strand.control_points[index] = pt(point);
        strand.control_point_center = mid(strand.start, strand.end);
      }
    }
  }
  return strands;
}

// ---------------------------------------------------------------------------
// Combo search (_evaluate_combo_indices, _numpy_try_all_angles,
// try_angle_configuration_first_last). A task is a plain structured-cloneable
// object so Web Workers can evaluate chunks of it.
// ---------------------------------------------------------------------------

/** numpy's pairwise_sum (np.add.reduce on a contiguous float64 array). */
function npPairwise(a, lo, n) {
  if (n < 8) { let r = 0; for (let i = 0; i < n; i++) r += a[lo + i]; return r; }
  if (n <= 128) {
    const r = [];
    for (let j = 0; j < 8; j++) r.push(a[lo + j]);
    let i = 8;
    for (; i < n - n % 8; i += 8) for (let j = 0; j < 8; j++) r[j] += a[lo + i + j];
    let res = ((r[0] + r[1]) + (r[2] + r[3])) + ((r[4] + r[5]) + (r[6] + r[7]));
    for (; i < n; i++) res += a[lo + i];
    return res;
  }
  let n2 = Math.floor(n / 2); n2 -= n2 % 8;
  return npPairwise(a, lo, n2) + npPairwise(a, lo + n2, n - n2);
}
const npSum = (a, n) => 0 + npPairwise(a, 0, n);

// cos/sin of every search angle h/100° and of h/100° + 180°, cached by h.
const TRIG_SPAN = 72000, trig = new Float64Array((2 * TRIG_SPAN + 1) * 4).fill(NaN);
function trigAt(h, out) {
  const i = (h + TRIG_SPAN) * 4;
  if (h >= -TRIG_SPAN && h <= TRIG_SPAN && !Number.isNaN(trig[i])) { out[0] = trig[i]; out[1] = trig[i + 1]; out[2] = trig[i + 2]; out[3] = trig[i + 3]; return; }
  const rad = h / 100 * DEG2RAD;
  out[0] = Math.cos(rad); out[1] = Math.sin(rad); out[2] = Math.cos(rad + Math.PI); out[3] = Math.sin(rad + Math.PI);
  if (h >= -TRIG_SPAN && h <= TRIG_SPAN) trig.set(out, i);
}

/** _start_clearances for arms p→q against the other group's arms (task.other = [rx, ry, ex, ey]*). */
function startClearances(px, py, qx, qy, count, other) {
  const out = [];
  for (let i = 0; i < count; i++) {
    const d0 = qx[i] - px[i], d1 = qy[i] - py[i], length = Math.hypot(d0, d1);
    let best = Infinity;
    for (let j = 0; j < other.length; j += 4) {
      const e0 = other[j + 2], e1 = other[j + 3], denom = d0 * e1 - d1 * e0;
      const w0 = other[j] - px[i], w1 = other[j + 1] - py[i];
      const t = (w0 * e1 - w1 * e0) / denom, u = (w0 * d1 - w1 * d0) / denom;
      if (Math.abs(denom) > 1e-9 && u >= 0 && u <= 1) best = Math.min(best, t * length);
    }
    out.push(best);
  }
  return out;
}

/** precompute_line_params + fast_perpendicular_distance. */
function lineDistance(s, e, px, py) {
  const dx = e.x - s.x, dy = e.y - s.y, c = e.x * s.y - e.y * s.x, lsq = dx * dx + dy * dy;
  if (lsq < .000001) return 0;
  return (dy * px + -dx * py + c) * (1 / Math.sqrt(lsq));
}

function makeWork(t) {
  const N = t.n, f = () => new Float64Array(N);
  return {sx: f(), sy: f(), dx: f(), dy: f(), gp: new Uint8Array(N), proj: f(), c: f(), s: f(), ex: f(), ey: f(),
    ldx: f(), ldy: f(), lc: f(), inv: f(), sg: f(), abs: f(), sq: f(), tr: new Float64Array(4)};
}

/** _build_config_dict at extension 0 (the combo search never extends the inner arms). */
function buildConfig(t, w, i, cos, sin, angle, gp) {
  if (!t.s23ok[i]) return null;
  const es = {x: w.sx[i] + 0 * t.nx[i], y: w.sy[i] + 0 * t.ny[i]};
  const length = (t.tx[i] - es.x) * cos + (t.ty[i] - es.y) * sin;
  if (length <= 10) return null;
  return {i, extended_start: es, end: {x: es.x + length * cos, y: es.y + length * sin}, length, extension: 0, angle, goes_positive: !!gp};
}

/** _numpy_try_all_angles with allow_inner_extensions=False over angles h/100°, h = h0, h0+step … ≤ h1. */
function tryAllAngles(t, w, h0, h1, step) {
  const N = t.n, {sx, sy, dx, dy, gp, proj, c, s, ex, ey, ldx, ldy, lc, inv, sg, abs, sq, tr} = w;
  const minGap = t.strandWidth + 10, maxGap = t.strandWidth * 1.5;
  const clearanceActive = t.other.length > 0 && t.minClearance > 0;
  for (let i = 0; i < N; i++) {
    dx[i] = t.tx[i] - sx[i]; dy[i] = t.ty[i] - sy[i];
    if (Math.sqrt(dx[i] * dx[i] + dy[i] * dy[i]) < .001) return null;
  }
  // Each arm runs along the search angle or against it, by its dot product with the first arm.
  const ref = Math.atan2(dy[0], dx[0]), cr = Math.cos(ref), sr = Math.sin(ref);
  for (let i = 0; i < N; i++) gp[i] = dx[i] * cr + dy[i] * sr >= 0 ? 1 : 0;
  // numpy computes every arm's projection, line and gap before rejecting an
  // angle; any failed check rejects it, so arms are built lazily and checks stop
  // at the first failure. arm(i) is false when the projection is <= 10 or the line degenerate.
  const arm = i => {
    const cc = gp[i] ? tr[0] : tr[2], ss = gp[i] ? tr[1] : tr[3], p = dx[i] * cc + dy[i] * ss;
    if (!(p > 10)) return false;
    proj[i] = p; c[i] = cc; s[i] = ss;
    ex[i] = sx[i] + proj[i] * c[i]; ey[i] = sy[i] + proj[i] * s[i];
    ldx[i] = ex[i] - sx[i]; ldy[i] = ey[i] - sy[i]; lc[i] = ex[i] * sy[i] - ey[i] * sx[i];
    const ll = Math.sqrt(ldx[i] * ldx[i] + ldy[i] * ldy[i]);
    inv[i] = 1 / ll;
    return ll >= .001;
  };
  let best = null, bestDist = Infinity, bestVar = Infinity, clearances = null;
  for (let h = h0; h <= h1; h += step) {
    const at = (h + TRIG_SPAN) * 4;
    if (h >= -TRIG_SPAN && h <= TRIG_SPAN && !Number.isNaN(trig[at])) { tr[0] = trig[at]; tr[1] = trig[at + 1]; tr[2] = trig[at + 2]; tr[3] = trig[at + 3]; }
    else trigAt(h, tr);
    let ok = true;
    if (!arm(0)) continue;
    if (N > 2) {
      const lastSg = (ldy[0] * sx[N - 1] + -ldx[0] * sy[N - 1] + lc[0]) * inv[0], positive = lastSg >= 0;
      for (let i = 0; i < N - 1 && ok; i++) {
        if (i > 0 && !arm(i)) { ok = false; break; }
        let g = (ldy[i] * sx[i + 1] + -ldx[i] * sy[i + 1] + lc[i]) * inv[i];
        if (i % 2 === 1) g = -g;
        sg[i] = g; abs[i] = Math.abs(g);
        ok = (positive ? g > 0 : g < 0) && abs[i] >= minGap && abs[i] <= maxGap;
      }
      if (!ok || !arm(N - 1)) continue;
      sg[N - 1] = lastSg;
    } else if (!arm(1)) continue;
    const rad = h / 100 * DEG2RAD, deg = h / 100;
    if (N === 2) {
      const gap = Math.abs(ldy[0] * inv[0] * sx[1] + -ldx[0] * inv[0] * sy[1] + lc[0] * inv[0]);
      if (!(gap >= minGap && gap <= maxGap)) continue;
      if (clearanceActive) {
        clearances = startClearances(sx, sy, ex, ey, N, t.other);
        if (Math.min(...clearances) < t.minClearance) continue;
      }
      if (gap < bestDist || (gap === bestDist && 0 < bestVar)) {
        bestDist = gap; bestVar = 0;
        const c1 = buildConfig(t, w, 0, c[0], s[0], gp[0] ? rad : rad + Math.PI, gp[0]);
        const c2 = buildConfig(t, w, 1, c[1], s[1], gp[1] ? rad : rad + Math.PI, gp[1]);
        if (c1 && c2) {
          const d = lineDistance(c1.extended_start, c1.end, c2.extended_start.x, c2.extended_start.y), a = Math.abs(d);
          best = {valid: true, configurations: [c1, c2], gaps: [a], signed_gaps: [d], gap_variance: 0, average_gap: a,
            worst_gap: a, angle: rad, angle_degrees: deg, min_gap: minGap, max_gap: maxGap, first_last_distance: a,
            start_clearances: clearances};
        }
      }
      continue;
    }
    if (clearanceActive) {
      clearances = startClearances(sx, sy, ex, ey, N, t.other);
      if (Math.min(...clearances) < t.minClearance) continue;
    }
    const mean = npSum(abs, N - 1) / (N - 1);
    for (let i = 0; i < N - 1; i++) { const x = abs[i] - mean; sq[i] = x * x; }
    const variance = npSum(sq, N - 1) / (N - 1), dist = Math.abs(sg[N - 1]);
    if (!(dist < bestDist || (dist === bestDist && variance < bestVar))) continue;
    bestDist = dist; bestVar = variance;
    const configs = [];
    for (let i = 0; i < N; i++) {
      const cfg = buildConfig(t, w, i, c[i], s[i], gp[i] ? rad : rad + Math.PI, gp[i]);
      if (!cfg) break;
      configs.push(cfg);
    }
    if (configs.length < N) continue;
    const gaps = [], signed = [];
    for (let i = 0; i < N - 1; i++) {
      let d = lineDistance(configs[i].extended_start, configs[i].end, configs[i + 1].extended_start.x, configs[i + 1].extended_start.y);
      if (i % 2 === 1) d = -d;
      signed.push(d); gaps.push(Math.abs(d));
    }
    best = {valid: true, configurations: configs, gaps, signed_gaps: signed, gap_variance: variance, average_gap: mean,
      worst_gap: Math.min(...gaps), angle: rad, angle_degrees: deg, min_gap: minGap, max_gap: maxGap,
      first_last_distance: dist, start_clearances: clearances};
  }
  return best;
}

/** try_angle_configuration_first_last(allow_inner_extensions=False); returns the fallback or null. */
function firstLastFallback(t, w, h) {
  const N = t.n, minGap = t.strandWidth + 10, maxGap = t.strandWidth * 1.5;
  let rad = 0, ca = 1, sa = 0, cb = Math.cos(Math.PI), sb = Math.sin(Math.PI);
  if (h != null) { trigAt(h, w.tr); rad = h / 100 * DEG2RAD; [ca, sa, cb, sb] = w.tr; }
  const configs = [];
  for (let i = 0; i < N; i++) {
    const dx = t.tx[i] - w.sx[i], dy = t.ty[i] - w.sy[i];
    if (Math.sqrt(dx * dx + dy * dy) < .001) return null;
    const gp = dx * ca + dy * sa >= 0, cfg = buildConfig(t, w, i, gp ? ca : cb, gp ? sa : sb, gp ? rad : rad + Math.PI, gp);
    if (!cfg) return null;
    configs.push(cfg);
  }
  const signed = [];
  for (let i = 0; i < N - 1; i++) {
    let d = lineDistance(configs[i].extended_start, configs[i].end, configs[i + 1].extended_start.x, configs[i + 1].extended_start.y);
    if (i % 2 === 1) d = -d;
    signed.push(d);
  }
  const gaps = signed.map(Math.abs), average = pySum(gaps) / gaps.length;
  const fallback = {configurations: configs, gaps, signed_gaps: signed,
    gap_variance: N === 2 ? 0 : pySum(gaps.map(g => (g - average) ** 2)) / gaps.length,
    average_gap: average, worst_gap: Math.min(...gaps), angle: rad, min_gap: minGap, max_gap: maxGap};
  if (N === 2) return gaps[0] >= minGap && gaps[0] <= maxGap ? null : fallback;
  const first = lineDistance(configs[0].extended_start, configs[0].end, configs[N - 1].extended_start.x, configs[N - 1].extended_start.y);
  const positive = first >= 0;
  for (const d of signed) {
    if (positive ? d <= 0 : d >= 0) return null; // directions_valid False: not a fallback candidate
    if (Math.abs(d) < minGap || Math.abs(d) > maxGap) return fallback;
  }
  return null;
}

/**
 * _evaluate_combo_indices for combos [start, end) (or the explicit `indices`,
 * with an optional guided `angleFraction` [lo, hi]). `onTick(done)` reports progress.
 */
export function evaluateCombos(t, start, end, indices = null, angleFraction = null, onTick = null) {
  const N = t.n, P = t.pairs.length / 2, ext = t.ext, R = ext.length, w = makeWork(t);
  const custom = t.customMin != null && t.customMax != null, step = Math.max(1, Math.trunc(t.angleStep * 100));
  const combo = new Array(P).fill(0), valid = [];
  let fallback = null, worst = -Infinity, fallbackExt = new Array(P).fill(0), fallbackAngle = 0;
  const count = indices ? indices.length : end - start;
  for (let q = 0; q < count; q++) {
    const index = indices ? indices[q] : start + q;
    let rest = index;
    for (let p = P - 1; p >= 0; p--) { combo[p] = ext[rest % R]; rest = Math.floor(rest / R); }
    for (let p = 0; p < P; p++) {
      const e = combo[p], l = t.pairs[2 * p], r = t.pairs[2 * p + 1];
      w.sx[l] = t.porig[4 * p] + e * t.pdir[4 * p]; w.sy[l] = t.porig[4 * p + 1] + e * t.pdir[4 * p + 1];
      if (r >= 0) { w.sx[r] = t.porig[4 * p + 2] + e * t.pdir[4 * p + 2]; w.sy[r] = t.porig[4 * p + 3] + e * t.pdir[4 * p + 3]; }
    }
    let lo = t.customMin, hi = t.customMax;
    if (!custom) {
      const isFirst = t.angleMode !== 'uniform' && t.angleMode !== 'avg_gaussian' && t.angleMode !== 'gaussian';
      const angles = [];
      for (let i = 0; i < (isFirst ? 1 : N); i++) angles.push(Math.atan2(t.ty[i] - w.sy[i], t.tx[i] - w.sx[i]) * RAD2DEG);
      [, lo, hi] = pairAngleRange(angles, t.angleMode, t.numOpposite);
    }
    if (angleFraction) { const span = hi - lo; [lo, hi] = [lo + span * angleFraction[0], lo + span * angleFraction[1]]; }
    const h0 = Math.trunc(lo * 100), h1 = Math.trunc(hi * 100);
    const result = tryAllAngles(t, w, h0, h1, step);
    if (result) {
      valid.push(Object.assign(result, {pair_extensions: combo.slice(), combo_index: index}));
    } else {
      const steps = h1 >= h0 ? Math.floor((h1 - h0) / step) + 1 : 0, middle = steps ? h0 + Math.floor(steps / 2) * step : null;
      const f = firstLastFallback(t, w, middle);
      if (f && f.worst_gap > worst) { worst = f.worst_gap; fallback = f; fallbackExt = combo.slice(); fallbackAngle = middle == null ? 0 : middle / 100; }
    }
    if (onTick && (q + 1) % 1024 === 0) onTick(q + 1, valid.length);
  }
  return {chunk_start: start, chunk_end: end, combos_evaluated: count, valid_results: valid, best_fallback: fallback,
    best_fallback_worst_gap: worst, best_fallback_extensions: fallbackExt, best_fallback_angle: fallbackAngle};
}

/** Merge chunk results in combo order, as the serial _search_combo_space_cpu would. */
export function mergeChunks(chunks, numPairs) {
  const out = {valid_results: [], best_fallback: null, best_fallback_worst_gap: -Infinity,
    best_fallback_extensions: new Array(numPairs).fill(0), best_fallback_angle: 0, combos_evaluated: 0};
  for (const c of [...chunks].sort((a, b) => a.chunk_start - b.chunk_start)) {
    if (c.best_fallback && c.best_fallback_worst_gap > out.best_fallback_worst_gap)
      Object.assign(out, {best_fallback: c.best_fallback, best_fallback_worst_gap: c.best_fallback_worst_gap,
        best_fallback_extensions: c.best_fallback_extensions, best_fallback_angle: c.best_fallback_angle});
    out.valid_results.push(...c.valid_results);
    out.combos_evaluated += c.combos_evaluated;
  }
  out.valid_results.sort((a, b) => a.combo_index - b.combo_index);
  return out;
}

// ---------------------------------------------------------------------------
// Selection (_select_best_result, _pick_lowest_variance)
// ---------------------------------------------------------------------------

const SHORT_ARM_VARIANCE_TOLERANCE = 1;
const totalExtension = r => pySum(r.pair_extensions || [0]);
const minBy = (list, less) => list.reduce((best, r) => less(r, best) ? r : best);
const fld = r => r.first_last_distance ?? Infinity, variance = r => r.gap_variance ?? Infinity;

function pickLowestVariance(results, preferShort) {
  const lowest = Math.min(...results.map(variance));
  if (!preferShort) return minBy(results, (a, b) => variance(a) < variance(b));
  const near = results.filter(r => variance(r) <= lowest + SHORT_ARM_VARIANCE_TOLERANCE);
  return minBy(near, (a, b) => totalExtension(a) < totalExtension(b) || (totalExtension(a) === totalExtension(b) && variance(a) < variance(b)));
}

export function selectBestResult(valid, preferShort = true, tolerance = 2, singleTolerance = 6) {
  if (!valid.length) return null;
  const sorted = [...valid].sort((a, b) => fld(a) - fld(b)), smallest = fld(sorted[0]);
  if (valid.every(r => (r.gaps || []).length <= 1))
    return minBy(sorted.filter(r => fld(r) <= smallest + singleTolerance), (a, b) => totalExtension(a) < totalExtension(b));
  const group1 = sorted.filter(r => fld(r) <= smallest + tolerance), best1 = pickLowestVariance(group1, preferShort);
  if (group1.length > 1) return best1;
  const remaining = sorted.filter(r => fld(r) > smallest + tolerance);
  if (!remaining.length) return best1;
  const next = fld(remaining[0]), best2 = pickLowestVariance(remaining.filter(r => fld(r) <= next + tolerance), preferShort);
  return variance(best2) < variance(best1) ? best2 : best1;
}

// ---------------------------------------------------------------------------
// Group and level alignment (align_horizontal/vertical_strands_parallel,
// align_level_parallel, apply_parallel_alignment). The *Steps generators yield
// each exhaustive search as {axis, task, total} and expect the merged chunk
// result back, so a driver can run it inline or across Web Workers.
// ---------------------------------------------------------------------------

const preserve = (width, message) => ({success: true, preserve_continuation: true, angle: 0, angle_degrees: 0,
  configurations: [], gaps: [], signed_gaps: [], average_gap: 0, gap_variance: 0, min_gap: width, max_gap: width * 1.5, message});

/** _other_group_arms as [[x, y], [x, y]] segments. */
export function groupArms(strands, names) {
  if (!names || !names.length) return [];
  const wanted = new Set(names);
  return strands.filter(s => s.type === 'AttachedStrand' && wanted.has(s.layer_name)).map(s => [[s.start.x, s.start.y], [s.end.x, s.end.y]]);
}
const flatArms = arms => Float64Array.from(arms.flatMap(([r, s]) => [r[0], r[1], s[0] - r[0], s[1] - r[1]]));

/** _group_start_clearance: smallest start clearance of `names` against `otherNames`. */
export function groupStartClearance(strands, names, otherNames) {
  const arms = groupArms(strands, names), others = groupArms(strands, otherNames);
  if (!arms.length || !others.length) return null;
  const col = (i, j) => Float64Array.from(arms, a => a[i][j]);
  return Math.min(...startClearances(col(0, 0), col(0, 1), col(1, 0), col(1, 1), arms.length, flatArms(others)));
}

/** _resolve_min_clearance without the environment: an override, else half a strand width. */
const resolveClearance = (width, override) => override != null ? Math.max(0, Number(override)) : width / 2;

function* alignGroupSteps(axis, strands, m, n, k, hand, direction, o = {}, otherArms = null, pass = 1) {
  const width = o.strand_width ?? 46, word = axis === 'h' ? 'horizontal' : 'vertical';
  if (k === 0) return preserve(width, 'k=0: _4/_5 alignment matches continuation exactly, no adjustment needed');
  if (isMaxK(m, n, k)) return preserve(width, 'Special max-k case: preserve the exact generated _4/_5 continuation, no alignment needed');
  const orders = kOrders(m, n, k, direction, hand), order = orders[axis], opposite = axis === 'h' ? orders.v : orders.h;
  const numOpposite = Math.max(Math.floor((opposite.length + 1) / 2), 1), names = new Set(order);
  const s2 = [], s3 = [], s4 = [], s5 = [];
  for (const s of strands) {
    if (s.type !== 'AttachedStrand') continue;
    const l = s.layer_name;
    if (l.endsWith('_2')) s2.push(s); else if (l.endsWith('_3')) s3.push(s);
    else if (l.endsWith('_4')) { if (names.has(l)) s4.push(s); } else if (l.endsWith('_5')) { if (names.has(l)) s5.push(s); }
  }
  if (!s4.length && !s5.length) return {success: false, message: `No ${word} _4/_5 strands found`};
  const group = [];
  for (const [list, bases, type] of [[s4, s2, '_4'], [s5, s3, '_5']]) for (const s of list) {
    const b = bases.find(x => x.set_number === s.set_number);
    if (b) group.push({s45: s, s23: b, type, set: s.set_number, os: pt(s.start), tp: pt(s.end)});
  }
  const index = new Map(order.map((name, i) => [name, i]));
  group.sort((a, b) => (index.get(a.s45.layer_name) ?? 999) - (index.get(b.s45.layer_name) ?? 999));
  const N = group.length;
  if (N < 2) return {success: false, message: `Need at least 2 ${word} strands for parallel alignment`};
  const pairIdx = [];
  for (let i = 0; i < Math.floor(N / 2); i++) pairIdx.push(i, N - 1 - i);
  if (N % 2 === 1) pairIdx.push(Math.floor(N / 2), -1);
  // The _2/_3 direction ([0, 0] when shorter than 0.001) and its length.
  const unit = s => {
    const dx = s.end.x - s.start.x, dy = s.end.y - s.start.y, len = Math.sqrt(dx * dx + dy * dy);
    return len > .001 ? [dx / len, dy / len, len] : [0, 0, len];
  };
  const pdir = [], porig = [];
  for (let p = 0; p < pairIdx.length; p += 2) {
    const l = group[pairIdx[p]], r = pairIdx[p + 1] >= 0 ? group[pairIdx[p + 1]] : null;
    const [lx, ly] = unit(l.s23), [rx, ry] = r ? unit(r.s23) : [0, 0];
    pdir.push(lx, ly, rx, ry);
    porig.push(l.os.x, l.os.y, r ? r.os.x : 0, r ? r.os.y : 0);
  }
  const maxPair = o.max_pair_extension ?? 200, pairStep = o.pair_extension_step ?? 10;
  if (!Number.isInteger(maxPair) || !Number.isInteger(pairStep)) throw new Error("'float' object cannot be interpreted as an integer");
  if (pairStep === 0) throw new Error('range() arg 3 must not be zero');
  const ext = [];
  for (let e = 0; pairStep > 0 ? e < maxPair + pairStep : e > maxPair + pairStep; e += pairStep) ext.push(e);
  const numPairs = pairIdx.length / 2, total = ext.length ** numPairs;
  // get_alignment_combo_guard (CPU limit)
  const limit = o.combo_limit === undefined ? 10_000_000 : o.combo_limit;
  if (limit != null && total > limit) {
    const count = s => s <= 0 ? 1 : Math.max(0, Math.ceil((maxPair + s) / s));
    let suggested = 1;
    if (numPairs > 0 && maxPair > 0) while (count(suggested) ** numPairs > limit) suggested++;
    const big = BigInt(ext.length) ** BigInt(numPairs), sugTotal = BigInt(count(suggested)) ** BigInt(Math.max(numPairs, 0));
    let message = `CPU search skipped: ${commas(big)} pair-extension combos exceeds the CPU limit of ${commas(limit)}. `
      + `Increase Pair ext step to at least ${suggested}px or lower Pair ext max.`;
    if (suggested !== pairStep) message += ` At ${suggested}px, the search drops to about ${commas(sugTotal)} combos.`;
    return {success: false, message};
  }
  if (otherArms == null) otherArms = groupArms(strands, opposite);
  const minClearance = otherArms.length ? resolveClearance(width, o.min_clearance) : 0;
  const custom = o.custom_angle_min != null && o.custom_angle_max != null;
  const task = {
    n: N, tx: Float64Array.from(group, g => g.tp.x), ty: Float64Array.from(group, g => g.tp.y),
    nx: Float64Array.from(group, g => unit(g.s23)[0]), ny: Float64Array.from(group, g => unit(g.s23)[1]),
    s23ok: Uint8Array.from(group, g => unit(g.s23)[2] >= .001 ? 1 : 0),
    pairs: Int32Array.from(pairIdx), pdir: Float64Array.from(pdir), porig: Float64Array.from(porig), ext: Int32Array.from(ext),
    angleStep: o.angle_step_degrees ?? .5, strandWidth: width,
    customMin: custom ? o.custom_angle_min : null, customMax: custom ? o.custom_angle_max : null,
    angleMode: o.angle_mode ?? 'first_strand', numOpposite, other: flatArms(otherArms), minClearance,
  };
  let summary = null;
  if (typeof o.guided_search === 'function') {
    // Hook for a policy-guided search (Python's guided_search); none ships in the browser.
    summary = o.guided_search({axis: word, task, total, numPairs, ext,
      evaluate: (indices, fraction) => evaluateCombos(task, 0, 0, indices, fraction)});
  }
  const search = summary == null ? {mode: 'exhaustive'} : summary.valid_results?.length ? {...summary.info, mode: 'guided'} : {mode: 'exhaustive', guided_attempt: summary.info};
  const found = summary?.valid_results?.length ? summary : yield {axis: word, pass, task, total};
  const comboCount = summary?.valid_results?.length ? summary.combos_evaluated : total;
  const configs = list => list.map(c => ({layer_name: group[c.i].s45.layer_name, base_layer_name: group[c.i].s23.layer_name,
    extended_start: c.extended_start, end: c.end, length: c.length, extension: c.extension, angle: c.angle, goes_positive: c.goes_positive}));
  const best = selectBestResult(found.valid_results, o.prefer_short_arms ?? true);
  if (best) {
    const exts = best.pair_extensions || [0];
    return {success: true, angle: best.angle, angle_degrees: best.angle_degrees, configurations: configs(best.configurations),
      average_gap: best.average_gap, gap_variance: best.gap_variance, first_last_distance: best.first_last_distance,
      start_clearances: best.start_clearances, pair_extension: exts.length ? exts[0] : 0, pair_extensions: exts,
      min_gap: best.min_gap ?? width, max_gap: best.max_gap ?? width * 1.5,
      message: `Found ${axis === 'v' ? 'vertical ' : ''}parallel configuration at ${pyFixed(best.angle_degrees, 2)}° (pair exts: ${tupleRepr(exts)})`,
      search, clearance_rule_px: minClearance};
  }
  const f = found.best_fallback;
  if (f) {
    const exts = found.best_fallback_extensions, worst = found.best_fallback_worst_gap;
    return {success: false, is_fallback: true, angle: f.angle, angle_degrees: found.best_fallback_angle,
      configurations: configs(f.configurations), average_gap: f.average_gap, gap_variance: f.gap_variance, worst_gap: worst,
      gaps: f.gaps, pair_extension: exts.length ? exts[0] : 0, pair_extensions: exts,
      min_gap: f.min_gap ?? width, max_gap: f.max_gap ?? width * 1.5,
      message: `Fallback: best candidate at ${pyFixed(found.best_fallback_angle, 2)}° (worst gap: ${pyFixed(worst, 1)}px)`,
      search, clearance_rule_px: minClearance};
  }
  return {success: false, message: `Could not find any valid configuration or fallback (${comboCount} extension combos tried)`};
}

/** apply_parallel_alignment: returns the strands (by layer name) with the result's arms. */
export function applyAlignment(strands, result) {
  if (result.preserve_continuation) return strands;
  const configs = result.configurations || [];
  if (!configs.length) return strands;
  const lookup = new Map(strands.map(s => [s.layer_name, s]));
  for (const c of configs) {
    const arm = lookup.get(c.layer_name), base = lookup.get(c.base_layer_name);
    if (arm) Object.assign(arm, {start: pt(c.extended_start), end: pt(c.end), control_points: [pt(c.extended_start), pt(c.end)],
      control_point_center: mid(c.extended_start, c.end)});
    if (base) {
      base.end = pt(c.extended_start);
      if (base.control_points && base.control_points.length > 1) base.control_points[1] = pt(c.extended_start);
      base.control_point_center = mid(base.start, c.extended_start);
    }
  }
  return [...lookup.values()];
}

/** align_level_parallel as a generator of search requests; returns {strands, h, v, level}. */
export function* alignLevelSteps(strands, m, n, k, hand, hOptions = {}, vOptions = {}, maxPasses = 3) {
  const direction = directionFor(hand);
  const rule = resolveClearance(hOptions.strand_width ?? 46, hOptions.min_clearance);
  const orders = k !== 0 ? kOrders(m, n, k, direction, hand) : null;
  const base = clone(strands), history = [];
  let finalV = null, passes = 0, current, h, v;
  for (;;) {
    passes++;
    current = clone(base);
    h = yield* alignGroupSteps('h', current, m, n, k, hand, direction, hOptions, finalV, passes);
    if (h.success || h.is_fallback) current = applyAlignment(current, h);
    v = yield* alignGroupSteps('v', current, m, n, k, hand, direction, vOptions, null, passes);
    if (v.success || v.is_fallback) current = applyAlignment(current, v);
    const clearance = rule && orders ? groupStartClearance(current, orders.h, orders.v) : null;
    history.push({pass: passes, h_clearance_px: clearance == null ? null : pyRound(clearance, 1)});
    if (clearance == null || clearance >= rule || !h.success || passes >= maxPasses) break;
    finalV = groupArms(current, orders.v);
  }
  return {strands: current, h, v, level: {passes, clearance_rule_px: rule, h_clearance_px: history[history.length - 1].h_clearance_px, history}};
}

/** Run a *Steps generator, evaluating each search inline. onProgress({axis, pass, completed, total, valid}). */
export function runSteps(gen, onProgress = null) {
  let step = gen.next();
  while (!step.done) {
    const {axis, pass, task, total} = step.value, report = (completed, valid) => onProgress && onProgress({axis, pass, completed, total, valid});
    report(0, 0);
    const chunk = evaluateCombos(task, 0, total, null, null, onProgress && report);
    report(total, chunk.valid_results.length);
    step = gen.next(mergeChunks([chunk], task.pairs.length / 2));
  }
  return step.value;
}

/** align_level_parallel on copies of `strands`: {strands, h, v, level, reports}. */
export function alignLevel(strands, m, n, k, hand, hOptions = {}, vOptions = {}, onProgress = null) {
  const out = runSteps(alignLevelSteps(strands, m, n, k, hand, hOptions, vOptions), onProgress);
  return {...out, reports: alignmentReports(out)};
}

/** search_report of site/workflow.py. */
export function searchReport(search) {
  if (!search || typeof search !== 'object') return {mode: 'exhaustive'};
  const info = search.mode === 'guided' ? search : search.guided_attempt || {};
  return {mode: search.mode ?? 'exhaustive', policy: info.policy ?? null, calls: info.policy_calls ?? null,
    inputTokens: info.policy_input_tokens ?? null, evaluated: info.combos_evaluated ?? null, total: info.combos_total ?? null};
}

/** The per-axis reports Workflow.run returns as `alignment`. */
export function alignmentReports({h, v, level}) {
  return [['h', h], ['v', v]].map(([axis, r]) => ({axis, success: !!r.success, fallback: !!r.is_fallback,
    message: r.message ?? r.reason ?? '', angle: r.angle_degrees ?? null, gap: r.average_gap ?? null,
    passes: level.passes, search: searchReport(r.search)}));
}

// ---------------------------------------------------------------------------
// Workflow.run without rendering
// ---------------------------------------------------------------------------

/** Validate Workflow.run options; returns them normalised plus per-axis align options. */
export function workflowOptions(options = {}) {
  if (!options || typeof options !== 'object' || Array.isArray(options)) throw new Error('Invalid alignment settings');
  const o = {...options}, mode = o.mode ?? 'first_strand';
  if (!['first_strand', 'avg_gaussian', 'custom'].includes(mode)) throw new Error('Invalid angle mode');
  const number = (name, fallback, low, high) => {
    const value = name in o ? o[name] : fallback;
    if (typeof value !== 'number' || !Number.isFinite(value) || value < low || value > high) throw new Error(`${name} must be between ${low} and ${high}`);
    return value;
  };
  for (const axis of ['h', 'v']) {
    const lo = number(axis + 'Min', axis === 'h' ? 0 : -90, -360, 360), hi = number(axis + 'Max', axis === 'h' ? 40 : -50, -360, 360);
    if (mode === 'custom' && lo > hi) throw new Error('Minimum angle must not exceed maximum angle');
    o[axis + 'Min'] = lo; o[axis + 'Max'] = hi;
  }
  const maximum = number('maximum', 200, 0, 1000), step = number('step', 10, 1, 100);
  const group = axis => ({angle_step_degrees: .5, max_extension: 100,
    custom_angle_min: mode === 'custom' ? o[axis + 'Min'] : null, custom_angle_max: mode === 'custom' ? o[axis + 'Max'] : null,
    max_pair_extension: maximum, pair_extension_step: step, angle_mode: mode === 'custom' ? 'first_strand' : mode,
    guided_search: o.guidedSearch ?? null});
  return {options: o, mode, h: group('h'), v: group('v')};
}

/**
 * Workflow.run for 'continue' | 'preview' | 'extend' | 'align' as a generator of
 * search requests. `document` is the continuation snapshot (left untouched);
 * returns {document, alignment, ranges, pairs}.
 */
export function* runActionSteps(action, settings, document = null, options = {}) {
  const {m, n, k, hand} = settings;
  if (!['continue', 'preview', 'extend', 'align'].includes(action)) throw new Error('Unknown continuation action');
  const describe = (doc, mode = 'first_strand', o = null) => ({document: doc,
    ranges: alignmentPreview(getActiveStrands(doc), m, n, k, hand, mode, o), pairs: pairs(m, n, k, hand)});
  if (action === 'continue') return {...describe(continuationDocument(m, n, k, hand)), alignment: []};
  if (!document) throw new Error('Generate continuation first');
  const doc = clone(document), {options: o, mode, h, v} = workflowOptions(options);
  let strands = getActiveStrands(doc);
  applyExtensions(strands, pairs(m, n, k, hand), o.extensions ?? {});
  let alignment = [];
  if (action === 'align') {
    const out = yield* alignLevelSteps(strands, m, n, k, hand, h, v);
    strands = out.strands;
    alignment = alignmentReports(out);
  }
  setActiveStrands(doc, strands);
  return {...describe(doc, mode, o), alignment};
}

export const runAction = (action, settings, document = null, options = {}, onProgress = null) =>
  runSteps(runActionSteps(action, settings, document, options), onProgress);
