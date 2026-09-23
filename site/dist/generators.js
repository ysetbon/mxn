// Browser port of the starting-stitch generators in src/: mxn_lh.py, mxn_rh.py,
// mxn_lh_strech.py and mxn_rh_stretch.py (generate_json). The four files differ
// only in the constants below, so one builder takes a per-variant config.
// site/test_browser_generators.py checks this against the Python output.

const GRID = 42;
const VARIANTS = {
  // Baseline: gap ±42, stride 4·42, tails hard-coded to 82 px, verticals end
  // 4/3 grid units beyond the outer horizontals' edges.
  standard: {gap: 42, stride: 168, length: 196, cx: 1274, cy: 434, tail: 82, reach: 42 + GRID + GRID / 3},
  // Stretch: gap 2/3 grid, stride 4·gap, shifted one grid unit up-left, tails of
  // 4/3 grid units, verticals end half a stride beyond the outer horizontals.
  stretch: {gap: GRID * 2 / 3, stride: 4 * GRID * 2 / 3, length: 4 * GRID * 2 / 3, cx: 1274 - GRID, cy: 434 - GRID, tail: GRID + GRID / 3, reach: 2 * GRID * 2 / 3},
};
const BLACK = () => ({r: 0, g: 0, b: 0, a: 255});
// The generators pick random colors for sets 3+; the site always repaints every
// set from the palette, so a fixed placeholder stands in for them.
const FIXED = {1: {r: 255, g: 255, b: 255, a: 255}, 2: {r: 85, g: 170, b: 0, a: 255}};
const colorFor = set => ({...(FIXED[set] || {r: 128, g: 128, b: 128, a: 255})});

function common() {
  return {
    start_line_visible: true, end_line_visible: true, is_hidden: false,
    start_extension_visible: false, end_extension_visible: false,
    start_arrow_visible: false, end_arrow_visible: false, full_arrow_visible: false,
    shadow_only: false, closed_connections: [false, false], arrow_color: null,
    arrow_transparency: 100, arrow_texture: 'none', arrow_shaft_style: 'solid',
    arrow_head_visible: true, arrow_casts_shadow: false, knot_connections: {},
    circle_stroke_color: BLACK(), start_circle_stroke_color: BLACK(), end_circle_stroke_color: BLACK(),
  };
}
const bias = () => ({triangle_bias: .5, circle_bias: .5, triangle_position: null, circle_position: null});
const mid = (a, b) => ({x: (a.x + b.x) / 2, y: (a.y + b.y) / 2});

function strand(start, end, color, layer, set, type = 'Strand', attachedTo = null, side = null) {
  const s = {
    type, index: 0, start, end, width: 46, color, stroke_color: BLACK(), stroke_width: 4,
    has_circles: type === 'Strand' ? [true, true] : [true, false],
    layer_name: layer, set_number: set, is_first_strand: type === 'Strand', is_start_side: type === 'Strand',
    ...common(),
    control_points: [{...start}, {...end}], control_point_center: mid(start, end),
    control_point_center_locked: false, bias_control: bias(),
    triangle_has_moved: false, control_point2_shown: false, control_point2_activated: false,
  };
  if (attachedTo) Object.assign(s, {attached_to: attachedTo, attachment_side: side, angle: 0, length: 0, is_start_side: false});
  return s;
}

function masked(v, h, index) {
  return {
    type: 'MaskedStrand', index, start: v.start, end: v.end, width: v.width, color: v.color,
    stroke_color: v.stroke_color, stroke_width: v.stroke_width, has_circles: [false, false],
    layer_name: `${v.layer_name}_${h.layer_name}`, set_number: Number(`${v.set_number}${h.set_number}`),
    is_first_strand: false, is_start_side: true, ...common(),
    control_points: [null, null], control_point_center: mid(v.start, v.end),
    control_point_center_locked: false, bias_control: bias(),
    triangle_has_moved: false, control_point2_shown: false, control_point2_activated: false,
    deletion_rectangles: [], first_selected_strand: v.layer_name, second_selected_strand: h.layer_name,
  };
}

// 1×1 shadow overrides from mxn_rh.py; the LH files swap 2_2 and 2_3.
function shadowOverrides(hand) {
  const o = {
    '1_3': {'1_1': {visibility: true, allow_full_shadow: true, subtracted_layers: ['2_2', '2_3']},
            '2_1': {visibility: true, allow_full_shadow: true, subtracted_layers: []},
            '2_2': {visibility: false, allow_full_shadow: false},
            '1_2': {visibility: false, allow_full_shadow: false},
            '2_3': {visibility: true, allow_full_shadow: false}},
    '2_3': {'2_1': {visibility: true, subtracted_layers: [], allow_full_shadow: true},
            '2_2': {visibility: true, allow_full_shadow: false},
            '1_2': {visibility: true, allow_full_shadow: false},
            '1_1': {visibility: true, subtracted_layers: ['1_2'], allow_full_shadow: true}},
    '1_2': {'1_1': {visibility: true, allow_full_shadow: true, subtracted_layers: ['2_2', '2_3']},
            '2_1': {visibility: true, allow_full_shadow: false},
            '2_2': {visibility: true, allow_full_shadow: true, subtracted_layers: []}},
    '2_2': {'1_1': {visibility: true, subtracted_layers: [], allow_full_shadow: true},
            '2_1': {visibility: true, allow_full_shadow: true, subtracted_layers: []}},
  };
  if (hand === 'rh') return o;
  const swap = name => ({'2_2': '2_3', '2_3': '2_2'}[name] || name);
  const swapAll = obj => Object.fromEntries(Object.entries(obj).map(([k, v]) => [swap(k),
    v && typeof v === 'object' && !Array.isArray(v) ? swapAll(v) : Array.isArray(v) ? v.map(swap) : v]));
  return swapAll(o);
}

/** Same OpenStrandStudioHistory document as the Python generate_json(m, n). */
export function generateDocument(m, n, hand = 'lh', stretch = false) {
  const c = VARIANTS[stretch ? 'stretch' : 'standard'];
  const gap = hand === 'lh' ? c.gap : -c.gap;
  // The tail leaving a vertical's end is _3 for LH and _2 for RH.
  const [endTail, startTail] = hand === 'lh' ? ['3', '2'] : ['2', '3'];
  const mains = [], twos = [], threes = [];
  const push = (s, suffix) => (suffix === '2' ? twos : threes).push(s);

  const hTop = c.cy - (n - 1) / 2 * c.stride, hBottom = c.cy + (n - 1) / 2 * c.stride;
  for (let i = 0; i < m; i++) {
    const x = c.cx + (i - (m - 1) / 2) * c.stride, set = n + 1 + i, main = `${set}_1`, color = colorFor(set);
    const start = {x: x + gap, y: hBottom + c.reach}, end = {x: x - gap, y: hTop - c.reach};
    mains.push(strand(start, end, color, main, set));
    push(strand(end, {x: end.x, y: start.y + c.tail}, color, `${set}_${endTail}`, set, 'AttachedStrand', main, 1), endTail);
    push(strand(start, {x: start.x, y: end.y - c.tail}, color, `${set}_${startTail}`, set, 'AttachedStrand', main, 0), startTail);
  }
  const halfWidth = ((m - 1) * c.stride + c.length) / 2;
  for (let i = 0; i < n; i++) {
    const y = c.cy + (i - (n - 1) / 2) * c.stride, set = 1 + i, main = `${set}_1`, color = colorFor(set);
    const start = {x: c.cx - halfWidth, y: y + gap}, end = {x: c.cx + halfWidth, y: y - gap};
    mains.push(strand(start, end, color, main, set));
    twos.push(strand(end, {x: start.x - c.tail, y: end.y}, color, `${set}_2`, set, 'AttachedStrand', main, 1));
    threes.push(strand(start, {x: end.x + c.tail, y: start.y}, color, `${set}_3`, set, 'AttachedStrand', main, 0));
  }
  const strands = [...mains, ...twos, ...threes];
  strands.forEach((s, i) => { s.index = i; });

  const tails = strands.filter(s => s.type === 'AttachedStrand');
  const vTails = tails.filter(s => s.set_number > n), hTails = tails.filter(s => s.set_number <= n);
  for (const v of vTails) for (const h of hTails) {
    const vs = v.layer_name.slice(-2), hs = h.layer_name.slice(-2);
    if ((vs === '_2' && hs === '_3') || (vs === '_3' && hs === '_2')) strands.push(masked(v, h, strands.length));
  }

  const overrides = m === 1 && n === 1 ? shadowOverrides(hand) : {};
  return {
    type: 'OpenStrandStudioHistory', version: 1, current_step: 3, max_step: 3,
    states: [1, 2, 3].map(step => ({step, data: {
      strands, groups: {}, selected_strand_name: null, locked_layers: [], lock_mode: false,
      shadow_enabled: false, show_control_points: step === 1, shadow_overrides: overrides,
    }})),
  };
}

/** Repaint each strand set from the palette, as native_renderer.render does. */
export function applyColors(document, colors) {
  for (const state of document.states || [{data: document}]) {
    for (const s of state.data.strands || []) {
      const c = colors[(s.set_number || 0) - 1];
      if (c) s.color = {r: parseInt(c.slice(1, 3), 16), g: parseInt(c.slice(3, 5), 16), b: parseInt(c.slice(5, 7), 16), a: 255};
    }
  }
  return document;
}
