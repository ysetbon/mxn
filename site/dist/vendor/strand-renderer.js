// Vendored verbatim from OpenStrandJS web/strand-renderer.js
// https://github.com/ysetbon/OpenStrandJS/blob/c0b13dfe7582218ba0c6c1c4696476ba1e71ccbb/web/strand-renderer.js
// Update by copying a newer revision and changing the commit above.
// Shared OpenStrandJS renderer. Loaded by both the headless harness
// (render.html, driven by Playwright) and the interactive viewer (viewer.html).
// Requires paper.js to be loaded first (global `paper`).

// ---- small vector helpers (plain {x,y}, world space) ----
const vsub = (a, b) => ({ x: a.x - b.x, y: a.y - b.y });
const vadd = (a, b) => ({ x: a.x + b.x, y: a.y + b.y });
const vmul = (a, s) => ({ x: a.x * s, y: a.y * s });
const vlen = (v) => Math.hypot(v.x, v.y);
const vdist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
const vnorm = (v) => { const l = vlen(v); return l < 0.001 ? { x: 0, y: 0 } : { x: v.x / l, y: v.y / l }; };

function toColor(c) {
  if (!c) return new paper.Color(0, 0, 0, 1);
  const a = (c.a == null ? 255 : c.a) / 255;
  return new paper.Color(c.r / 255, c.g / 255, c.b / 255, a);
}

// Grid line positions in TARGET-canvas pixel coords (LIVE EDITOR ONLY — the
// offline oracle never sets meta.show_grid, so this returns null there and the
// fidelity fixtures stay byte-identical). `scale` maps world->target px (= zoom
// for the visible 1x canvas, = ss*zoom for the supersampled offscreen) and ox/oy
// are the matching pan offsets in that same target space. Mirrors the screen-space
// math the overlay used previously, so lines land on the same world multiples of
// grid_size that snap-to-grid quantizes to. Returns { xs, ys } or null.
function computeGridLines(meta, scale, ox, oy, targetW, targetH) {
  const g = meta.grid_size;
  if (!meta.show_grid || !g || g <= 0) return null;
  if (g * (meta.zoom || 1) < 4) return null; // skip when too dense (matches the old overlay gate)
  const xs = [], ys = [];
  const worldLeft = (0 - ox) / scale, worldRight = (targetW - ox) / scale;
  const worldTop = (0 - oy) / scale, worldBottom = (targetH - oy) / scale;
  // Index the lines (i * g) rather than accumulating (x += g). The accumulation
  // starts at a different multiple of g for every pan offset, and floating-point
  // addition is not associative, so the SAME grid line came out a few ULPs apart
  // depending on where the walk began — enough to move a 1px line onto different
  // anti-aliasing. Indexing makes line i the same double at every offset, so the
  // grid translates with the content exactly instead of shimmering under a pan.
  for (let i = Math.floor(worldLeft / g); i * g <= worldRight; i++) xs.push(i * g * scale + ox);
  for (let i = Math.floor(worldTop / g); i * g <= worldBottom; i++) ys.push(i * g * scale + oy);
  return { xs, ys };
}

// Curve-shape parameters. These are canvas-level settings (NOT stored per
// strand in the JSON); the reference renderer exports the canvas's values
// into meta.curve_params. Defaults match the braid fixtures.
//
// Like every other paint setting (see applyPaintSettings) this is re-derived
// from `meta` at EVERY render entry point, falling back to the constant below
// when the key is absent. It used to be assigned only when the key WAS present,
// which made a render that omitted it inherit whatever curve the previous
// render had been given — the same document drawn with two different curves
// depending on what was rendered before it.
const CURVE_DEFAULT = { base_fraction: 1.0, dist_multiplier: 2.0, exponent: 2.0 };
let CURVE = CURVE_DEFAULT;

// Centerline sampling step (px) used to build stroked outlines. renderFixture (the
// pixel oracle) always uses 1 (~1px, full accuracy). The interactive drag path sets
// it coarser via DRAG_SAMPLE_STEP so a long curvy strand isn't sampled thousands of
// times per frame; the body is a hair less smooth mid-drag and snaps back to full
// accuracy on pointer-up. Only _dragPaint raises it, and renderFixture resets it to
// 1 on entry, so the harness output is unaffected.
let SAMPLE_STEP = 1;
const DRAG_SAMPLE_STEP = 3;

// ---- per-render geometry memo -------------------------------------------------
// The shadow pass is a nested walk: for every caster i it visits every receiver
// j < i, and for each (i, j) pair it subtracts the geometry of every layer
// between them and of every mask above the caster. The geometry each of those
// steps needs — a receiver's rendered outline, a mask's crossing region, a mask's
// blocker — depends ONLY on the strand plus the render-wide constants (P,
// enableThird, S, SAMPLE_STEP). It does not depend on which pair is being
// processed. Rebuilding it inside the loops therefore made the pass do O(N^2)
// outline builds and O(N^3) subtraction builds, and every one of those builds
// resamples a centerline at ~1px and runs resolveCrossings. On a 60-strand
// document that is multiple seconds of Paper.js path construction on pointer-up
// — the release hang.
//
// So memoize, scoped to ONE render. Opening the cache at the top of a render and
// closing it before the frame is composited gives two guarantees: an entry can
// never outlive the paper project it was built in, and geometry that changed
// between renders can never be served stale.
//
// Masters are held DETACHED (removed from the drawing tree) so they paint
// nothing and are skipped by every bounds/hit walk; each lookup hands back a
// fresh clone re-inserted at the top of the active layer, which is exactly where
// a freshly built path lands. Callers keep their existing ownership contract —
// mutate it, feed it to boolean ops, remove it when done — and the pixels are
// identical to rebuilding it from scratch.
let GEOM_CACHE = null;
// The paper project the masters in GEOM_CACHE belong to. A render that throws
// between geomCacheBegin() and geomCacheEnd() leaves the cache open, and the
// scheduler swallows renderer errors to keep the rAF loop alive — so the next
// paint would otherwise find a populated cache whose masters belong to a project
// that has since been removed, and serve clones of them. Pinning the project
// makes that impossible by construction rather than by every entry point
// remembering to clear first: a cache from another project simply reads as
// closed, and the builders run fresh.
let GEOM_PROJECT = null;

function geomCacheBegin() {
  geomCacheEnd();
  GEOM_CACHE = new Map();
  GEOM_PROJECT = paper.project;
  esCacheBegin();
}

// Is the memo open AND still owned by the project being drawn into?
function geomCacheLive() {
  return GEOM_CACHE !== null && GEOM_PROJECT === paper.project;
}

function geomCacheEnd() {
  const cache = GEOM_CACHE;
  GEOM_CACHE = null;                  // clear first: a render that threw must not
  GEOM_PROJECT = null;                // leave a half-open cache behind
  esCacheEnd();
  if (!cache) return;
  for (const e of cache.values()) {
    // The project these masters belong to may already be gone (a render that
    // threw part-way). Detaching a stale item is not worth failing the next frame.
    try { if (e && e.item) e.item.remove(); } catch { /* project already torn down */ }
  }
}

// The cache entry for `key`, building it on first use. `null` geometry is cached
// too, so a build that legitimately yields nothing is not retried once per pair.
function geomEntry(key, build) {
  let e = GEOM_CACHE.get(key);
  if (e === undefined) {
    const item = build();
    if (item) item.remove();          // hold the master out of the drawing tree
    e = { item, bounds: item ? item.bounds : null };
    GEOM_CACHE.set(key, e);
  }
  return e;
}

// Memoized geometry, handed back as an owned clone inserted where a fresh build
// would sit. Falls through to a plain build when no cache is open (the module's
// other entry points, and the auto-shadow probe, call these builders directly).
function cachedGeom(key, build) {
  if (!geomCacheLive()) return build();
  const e = geomEntry(key, build);
  if (!e.item) return null;
  const c = e.item.clone({ insert: false });
  paper.project.activeLayer.addChild(c);
  return c;
}

// Is a memo currently open? The keys carry no coordinates, so the cache is only
// correct while it is scoped to a single paint; tools/drag_perf_check.mjs asserts
// this is false after every render so a future edit cannot quietly widen the
// scope and freeze the dragged strand at its pointer-down shape. Deliberately the
// LITERAL open flag, not geomCacheLive(): the guard should catch a cache left
// behind even though the project pin would stop it being used.
window.__geomCacheOpen = function () { return GEOM_CACHE !== null; };

// Bounds of the memoized geometry WITHOUT paying for a clone — lets a caller run
// a cheap bounding-box reject before it commits to the real path.
function cachedGeomBounds(key, build) {
  if (!geomCacheLive()) return undefined;  // undefined = "unknown", caller must build
  return geomEntry(key, build).bounds;
}

// Shadow parameters — faithful port of shader_utils.py::draw_strand_shadow. The
// canvas loads NumSteps=2 / MaxBlurRadius=30.0 / ShadowColor=0,0,0,150 from
// user_settings.txt, so the function-signature default of 3 is moot; the LOADED
// value 2 wins. A strand casts onto every lower-ordered strand in two passes:
//   PASS A — SOLID CORE (unclipped, full alpha 150): the union of all surviving
//     (caster body+circles) ∩ (receiver rendered geometry) regions, filled solid.
//   PASS B — FADED BLUR (clipped to the union of receiver bodies): NUM_STEPS=2
//     boundary-stroke passes over (core ∪ caster-circles) with the per-step
//     width/alpha table computed from the formulas below (15px@150, 30px@75),
//     FlatCap / RoundJoin. The blur is what produces the soft fringe beyond the
//     caster body; the caster's own body (drawn after) covers the inner shadow.
// These three are SETTINGS in the desktop app (Settings -> General: Shadow Color,
// Shadow Blur Steps, Shadow Blur Radius). The values below are what the reference
// user_settings.txt loads, and therefore what the Qt pixel oracle renders — so they
// stay the defaults, and a meta that does not carry the keys (every fixture render)
// produces byte-identical output. applyPaintSettings overrides them per render for
// the live editor, where the three General-page controls previously did nothing.
const SHADOW_COLOR_DEFAULT = { r: 0, g: 0, b: 0, a: 150 };
let SHADOW_COLOR = SHADOW_COLOR_DEFAULT;
let MAX_BLUR = 30;
let NUM_STEPS = 2; // loaded reference setting (user_settings.txt NumSteps:2)
// OSS canvas.highlight_color (default opaque red, strand_drawing_canvas.py:175),
// used for the selected-strand halo and — with alpha forced to 128 — the selected
// mask's outline (masked_strand.py:1228-1231).
const HIGHLIGHT_COLOR_DEFAULT = { r: 255, g: 0, b: 0, a: 255 };
let HIGHLIGHT_COLOR = HIGHLIGHT_COLOR_DEFAULT;

// Apply the shadow/highlight settings carried on `meta`, falling back to the oracle
// constants for any key the caller omits. Called at EVERY render entry point so a
// value set by one frame can never leak into the next.
function applyPaintSettings(meta) {
  const m = meta || {};
  SHADOW_COLOR = m.shadow_color && m.shadow_color.a != null ? m.shadow_color : SHADOW_COLOR_DEFAULT;
  MAX_BLUR = typeof m.max_blur_radius === 'number' && m.max_blur_radius > 0 ? m.max_blur_radius : 30;
  // Guard the step count: shadowBlurSteps divides by it and OSS's own spin box is
  // bounded to 1..10 (settings_dialog.py), so a 0 would make every width NaN.
  NUM_STEPS = Number.isFinite(m.num_steps) && m.num_steps >= 1 ? Math.round(m.num_steps) : 2;
  HIGHLIGHT_COLOR = m.highlight_color && m.highlight_color.a != null ? m.highlight_color : HIGHLIGHT_COLOR_DEFAULT;
  ARROW_PARAMS = Object.assign({}, ARROW_DEFAULTS, m.arrow_params || {});
  EXTENSION_PARAMS = Object.assign({}, EXTENSION_DEFAULTS, m.extension_params || {});
  // Absent => true => the strand's own colour, which is what the oracle renders.
  USE_DEFAULT_ARROW_COLOR = m.use_default_arrow_color !== false;
  DEFAULT_ARROW_FILL = m.default_arrow_fill_color && m.default_arrow_fill_color.a != null
    ? m.default_arrow_fill_color : null;
  // Shadow Path preview pairs, [[caster, receiver], ...]. LIVE EDITOR ONLY: the
  // shadow editor sets them while it is open and clears them on close. Absent =>
  // [] => drawVisibleShadowPaths paints nothing, so the Qt oracle — which never
  // sets the key — renders exactly as before.
  VISIBLE_SHADOW_PATHS = Array.isArray(m.visible_shadow_paths) ? m.visible_shadow_paths : [];
}
// Curvature-bias gate (OSS canvas.enable_curvature_bias_control). Module-scoped
// like CURVE/SHADOW_ENABLED because buildProfile is reached through a dozen
// buildCenterline call sites. Set from meta at every render entry point; ABSENT
// => false => bias pinned to 0.5, which is the pre-existing behavior and what
// the Qt oracle renders (reference_render.py never enables it).
let BIAS_ENABLED = false;
let SHADOW_ENABLED = false; // set per-fixture from meta.shadow_enabled
let SHADOW_PAINT = null;    // paper.Color for shadows (solid-core paint)
let SHADOW_OVERRIDES = {};  // meta.shadow_overrides, keyed [caster][receiver] (consumed in the Port phase)
let VISIBLE_SHADOW_PATHS = []; // meta.visible_shadow_paths, [[caster, receiver], ...]

// Faithful port of strand.py::_build_curve_profile. Returns {mode, segments}
// in world coordinates; each segment is a cubic {p0, cp1, cp2, p3}.
// enable_third_control_point is a USER SETTING in OSS (canvas.enable_third_control_point,
// read by strand.py::_build_curve_profile), not a property of the data. Take it from
// meta when the caller supplies it; fall back to inferring it from the strands when
// absent, because that is exactly what the Qt oracle does
// (reference_render.py:117-121 "Enable third control point if any strand uses one").
// So the fidelity path is unchanged and the live editor now honors the toggle.
function resolveEnableThird(strands, meta) {
  if (meta && meta.enable_third_control_point != null) return !!meta.enable_third_control_point;
  return strands.some((s) => s.control_point_center != null);
}

function buildProfile(s, enableThird) {
  const start = s.start, end = s.end;
  const cps = s.control_points || [];
  const control_point1 = cps[0] || start;
  const control_point2 = cps[1] || end;
  const base_fraction = CURVE.base_fraction;
  const dist_multiplier = CURVE.dist_multiplier;
  const exponent = CURVE.exponent;
  // OSS strand.py::_build_curve_profile reads bias_control.triangle_bias/circle_bias,
  // but ONLY while canvas.enable_curvature_bias_control is on; otherwise both stay
  // 0.5. Same gate here, same neutral default.
  const bc = BIAS_ENABLED ? s.bias_control : null;
  const bias_triangle = bc && bc.triangle_bias != null ? bc.triangle_bias : 0.5;
  const bias_circle = bc && bc.circle_bias != null ? bc.circle_bias : 0.5;

  const thirdLocked = enableThird && s.control_point_center_locked && s.control_point_center;

  if (thirdLocked) {
    const p0 = start, p1 = control_point1, p2 = s.control_point_center, p3 = control_point2, p4 = end;
    const in_norm = vnorm(vsub(p2, p1)), out_norm = vnorm(vsub(p3, p2));
    const center_tangent = { x: (in_norm.x + out_norm.x) * 0.5, y: (in_norm.y + out_norm.y) * 0.5 };
    const dist2 = vdist(p2, p1), dist3 = vdist(p3, p2);
    let frac1 = Math.min(0.1 + base_fraction * 0.3, 8.33);
    let frac2 = Math.min(0.05 + base_fraction * 0.15, 3.77);
    frac1 = Math.min(frac1 * dist_multiplier, 8.33);
    frac2 = Math.min(frac2 * dist_multiplier, 8.33);
    if (exponent !== 1.0) { frac1 = Math.pow(frac1, 1 / exponent); frac2 = Math.pow(frac2, 1 / exponent); }
    const cp1 = vadd(p0, vmul(vsub(p1, p0), frac1 * (0.5 + bias_triangle)));
    const cp2 = vsub(p2, vmul(center_tangent, dist2 * frac2 * (0.5 + bias_triangle)));
    const cp3 = vadd(p2, vmul(center_tangent, dist3 * frac2 * (0.5 + bias_circle)));
    const cp4 = vadd(p4, vmul(vsub(p3, p4), frac2 * (0.5 + bias_circle)));
    return { mode: 'multi', segments: [{ p0, cp1, cp2, p3: p2 }, { p0: p2, cp1: cp3, cp2: cp4, p3: p4 }] };
  }

  const cp1_at_start = Math.abs(control_point1.x - start.x) < 1.0 && Math.abs(control_point1.y - start.y) < 1.0;
  const cp2_at_start = Math.abs(control_point2.x - start.x) < 1.0 && Math.abs(control_point2.y - start.y) < 1.0;
  if (cp1_at_start && cp2_at_start) return { mode: 'line', segments: [] };

  const p0 = start, p1 = control_point1;
  const p2 = { x: (control_point1.x + control_point2.x) / 2, y: (control_point1.y + control_point2.y) / 2 };
  const p3 = control_point2, p4 = end;
  const in_norm = vnorm(vsub(p2, p1)), out_norm = vnorm(vsub(p3, p2));
  const center_tangent = { x: (in_norm.x + out_norm.x) * 0.5, y: (in_norm.y + out_norm.y) * 0.5 };
  const dist2 = vdist(p2, p1), dist3 = vdist(p3, p2);
  let frac1 = Math.min(Math.min(0.1 + base_fraction * 0.2, 2.34) * dist_multiplier, 8.33);
  let frac2 = Math.min(Math.min(0.05 + base_fraction * 0.1, 1.17) * dist_multiplier, 8.33);
  if (exponent !== 1.0) { frac1 = Math.pow(frac1, 1 / exponent); frac2 = Math.pow(frac2, 1 / exponent); }
  const cp1 = vadd(p0, vmul(vsub(p1, p0), frac1 * (0.5 + bias_triangle)));
  const cp2 = vsub(p2, vmul(center_tangent, dist2 * frac2 * (0.5 + bias_triangle)));
  const cp3 = vadd(p2, vmul(center_tangent, dist3 * frac2 * (0.5 + bias_circle)));
  const cp4 = vadd(p4, vmul(vsub(p3, p4), frac2 * (0.5 + bias_circle)));
  return { mode: 'multi', segments: [{ p0, cp1, cp2, p3: p2 }, { p0: p2, cp1: cp3, cp2: cp4, p3: p4 }] };
}

// Build the centerline as a paper.Path in pixel space.
function buildCenterline(s, P, enableThird) {
  const prof = buildProfile(s, enableThird);
  const path = new paper.Path();
  if (prof.mode === 'line') {
    path.moveTo(P(s.start));
    path.lineTo(P(s.end));
    return path;
  }
  path.moveTo(P(prof.segments[0].p0));
  for (const sg of prof.segments) {
    path.cubicCurveTo(P(sg.cp1), P(sg.cp2), P(sg.p3));
  }
  return path;
}

// Equivalent of QPainterPathStroker.createStroke(width): the closed outline
// produced by stroking the centerline at the given width with flat caps.
// Implemented by sampling the centerline and offsetting by +/- width/2 along
// the normal, then joining left + reversed-right into a closed path.
// This is the single hottest function in the renderer: every body, every shadow
// caster/receiver and every mask component goes through it, at ~1px sampling.
// Two things make it cheap without moving a pixel:
//   * ONE getLocationAt(off) per sample instead of getPointAt(off) +
//     getNormalAt(off). Both of those are literally `getLocationAt(off).point` /
//     `.normal` in paper.js, so asking twice ran the arc-length -> curve-time
//     solve (getTimeOf, the profiler's #2 cost) twice for the same offset.
//   * plain [x, y] pairs instead of Point arithmetic. `pt.add(nrm.multiply(half))`
//     allocated two paper.Points per side per sample — six per sample in total —
//     purely to be re-read into a Segment straight afterwards. The arithmetic
//     below is the same expression in the same order on the same doubles, so the
//     coordinates are bit-identical.
function strokedOutline(centerline, width) {
  const len = centerline.length;
  if (len === 0 || width <= 0) return null;
  const half = width / 2;
  const N = Math.max(8, Math.ceil(len / SAMPLE_STEP)); // ~1px sampling (coarser while dragging)
  const left = [], right = [];
  for (let i = 0; i <= N; i++) {
    const off = Math.min(len * i / N, len - 1e-4);
    const loc = centerline.getLocationAt(off);
    const pt = loc && loc.point;
    const nrm = loc && loc.normal;
    if (!pt || !nrm) continue;
    left.push([pt.x + nrm.x * half, pt.y + nrm.y * half]);
    right.push([pt.x - nrm.x * half, pt.y - nrm.y * half]);
  }
  right.reverse();
  return new paper.Path({ segments: left.concat(right), closed: true });
}

// Stroked body outline at an arbitrary width (pixel space), with
// self-intersections (from offsetting a tightly curved centerline) resolved
// into a clean boundary. Returns a paper path or null. The masking primitive.
function strokedBodyAtWidth(s, P, enableThird, widthPx, centerline) {
  const cl = centerline || buildCenterline(s, P, enableThird);
  let outline = strokedOutline(cl, widthPx);
  if (!centerline) cl.remove();
  if (!outline) return null;
  const cleaned = outline.resolveCrossings();
  if (cleaned !== outline) { outline.remove(); outline = cleaned; }
  return outline;
}

// The RAW stroked band: this strand's centerline offset by +/- half `widthPx`,
// with its self-overlaps left in place. This is Qt's
// QPainterPathStroker.createStroke() output, and it is what the PAINTED body is
// built from — see windingFillLayer for why the cleaned bodyOutline below must
// not be used there. Memoized per render like bodyOutline (same paint, same
// band, asked for once per body layer).
function bodyBand(s, P, enableThird, widthPx, centerline) {
  return cachedGeom(`band|${s.layer_name}|${widthPx}`, () => {
    const cl = centerline || buildCenterline(s, P, enableThird);
    const outline = strokedOutline(cl, widthPx);
    if (!centerline) cl.remove();
    return outline;
  });
}

// Paint one body layer the way Qt paints it: ONE QPainterPath with
// Qt.WindingFill holding the stroked band plus every cap sub-path (strand.py
// :2515/:2600 set the fill rule, :2604-2680 addPath() the caps), filled in a
// single drawPath. A paper CompoundPath with fillRule 'nonzero' is that path —
// paper's CompoundPath#_draw emits every child into one ctx.beginPath() and
// issues one ctx.fill(fillRule).
//
// It is deliberately NOT built with resolveCrossings()/unite(). Both are
// boolean operations, and OSS itself abandoned QPainterPath.united() here for
// exactly this reason (strand.py:1704-1709: "Components are appended with
// WindingFill instead of combined with QPainterPath.united(). Qt's Boolean
// union can discard the body"). paper.js's resolveCrossings() has the same
// failure on the self-overlapping band a tightly curved centerline produces: it
// silently returns a fraction of the region (measured at ~23% of the band's
// area on mxn_lh_1x1's 1_1 and ~35% on three_strand_braid's 3_3 during a
// control-point drag). When it eats the FILL layer the strand paints as a solid
// stroke-coloured silhouette — the black-band bug; when it eats the STROKE layer
// the outline disappears under the fill.
//
// Every piece here is additive (band, cap circles, half-circles, side rects,
// end quads — no holes), so each sub-path is forced clockwise first: under the
// nonzero rule two overlapping sub-paths of OPPOSITE orientation would cancel to
// a hole, where Qt's stroker and ellipse builders hand it consistently wound
// sub-paths. Same orientation => the composite is exactly their union.
function windingFillLayer(pieces, color) {
  const children = [];
  for (const item of pieces) {
    if (!item) continue;
    // A boolean result (the half-circle caps) can be a CompoundPath; paper's
    // CompoundPath#insertChildren splices those apart for us, so hand it over
    // whole and let it flatten.
    if (item.children && !item.children.length) { item.remove(); continue; }
    if (!item.children && !(item.segments && item.segments.length)) { item.remove(); continue; }
    children.push(item);
  }
  if (!children.length) return null;
  const cp = new paper.CompoundPath({ children, fillRule: 'nonzero' });
  for (const ch of cp.children) ch.setClockwise(true);
  cp.fillColor = color;
  cp.strokeColor = null;
  return cp;
}

// The one primitive every SHADOW footprint and MASK component is built from:
// this strand's centerline stroked at `widthPx` and cleaned into a simple
// boundary. Those consumers feed the result straight into intersect()/subtract()
// and need a non-self-intersecting input; the painted body does not go through
// here (see bodyBand / windingFillLayer above). In a single render the SAME
// (strand, width) outline is asked for repeatedly — the shadow caster core wants
// the body at w+2sw, the shadow receiver geometry wants it again, and a mask
// component often wants it once more. Each build resamples the centerline at
// ~1px and then runs resolveCrossings over a few hundred segments, so the
// duplicates were the bulk of the remaining cost. Memoized per render (see the geometry memo above), which
// hands back an owned clone, so every caller keeps its existing contract.
function bodyOutline(s, P, enableThird, widthPx, centerline) {
  return cachedGeom(`body|${s.layer_name}|${widthPx}`,
    () => strokedBodyAtWidth(s, P, enableThird, widthPx, centerline));
}

// Resolve self-intersections of a stroked outline into a clean boundary.
function cleanOutline(outline) {
  if (!outline) return null;
  const cleaned = outline.resolveCrossings();
  if (cleaned !== outline) outline.remove();
  return cleaned;
}

// ---- end-cap & side-line geometry (PIXEL space) -------------------------------
// Faithful port of the cap drawing in strand.py::draw and attached_strand.py::draw.
// Qt draws the body as TWO filled layers (stroke path at width+2*stroke in stroke
// color, fill path at width in color on top) and ADDS end caps to each layer:
//   outer = half of a circle/ellipse  -> stroke (combined_stroke_path)
//   inner = full circle/ellipse       -> fill   (combined_fill_path)
//   side rectangle                    -> fill   (combined_fill_path)
// With elliptical_end_caps off (the whole current corpus) _partner_cap_dims is
// (None, None), so every cap is a plain CIRCLE: outer R=(w+2sw)/2, inner R=w/2.

const PT_EPS = 0.5; // world-space coincidence tolerance (Qt compares points exactly)
function approxPt(a, b) {
  return !!a && !!b && Math.abs(a.x - b.x) < PT_EPS && Math.abs(a.y - b.y) < PT_EPS;
}
// circle_stroke colors default to a visible (alpha 255) stroke when absent.
function circleStrokeAlpha(c) { return c && c.a != null ? c.a : 255; }
// Effective per-end stroke: OSS start/end_circle_stroke_color are properties
// that fall back to the legacy circle_stroke_color, then opaque black
// (strand.py:507-521 / 543-557). Saved files may carry only the legacy field
// (e.g. an unfolded start stored as circle_stroke_color alpha 0), so every
// alpha gate must resolve through the same fallback chain.
function effStartStroke(s) { return s.start_circle_stroke_color != null ? s.start_circle_stroke_color : s.circle_stroke_color; }
function effEndStroke(s) { return s.end_circle_stroke_color != null ? s.end_circle_stroke_color : s.circle_stroke_color; }

// True when some OTHER AttachedStrand starts at world point `pt` (i.e. a child
// attaches there). Mirrors Qt's `any(child.start == self.<end> for child in
// self.attached_strands)`, reconstructed geometrically from the flat strand list.
function hasAttachedChildAt(pt, strands, self) {
  for (const c of strands) {
    if (c === self || c.type !== 'AttachedStrand') continue;
    if (approxPt(c.start, pt)) return true;
  }
  return false;
}

// Recompute has_circles the way OpenStrand Studio does on load
// (save_load_manager.py "Fourth pass", ~940-994): the stored value is replaced
// by whether a child actually attaches at each end, with manual_circle_visibility
// overrides. An AttachedStrand always keeps its start circle (the attachment
// point). This is the RENDER-TIME truth -- e.g. a lone strand whose JSON says
// has_circles=[false,true] becomes [false,false], so BOTH ends get a flat side
// line instead of a phantom end circle.
function computeHasCircles(s, strands) {
  const mcv = Array.isArray(s.manual_circle_visibility) ? s.manual_circle_visibility : [null, null];
  if (s.type === 'AttachedStrand') {
    // 1.109 (save_load_manager.py "Fourth pass" fix): an explicit layer-menu
    // choice for the START circle survives reload too — only default to true
    // (the attachment point) when there is no manual override.
    const endAtt = hasAttachedChildAt(s.end, strands, s);
    return [mcv[0] != null ? mcv[0] : true, mcv[1] != null ? mcv[1] : endAtt];
  }
  const startAtt = hasAttachedChildAt(s.start, strands, s);
  const endAtt = hasAttachedChildAt(s.end, strands, s);
  return [mcv[0] != null ? mcv[0] : startAtt, mcv[1] != null ? mcv[1] : endAtt];
}

// Pixel-space tangent ANGLE (radians) at a path offset. Direction follows
// increasing arc length: at off=0 it points INTO the body, at off=len it points
// OUT of the end — matching Qt's calculate_cubic_tangent(0.0001 / 0.9999).
function tangentAngle(centerline, off) {
  const len = centerline.length;
  let o = Math.max(0, Math.min(off, len));
  let t = centerline.getTangentAt(o);
  if (!t && len > 0) t = centerline.getTangentAt(Math.max(0, Math.min(o, len - 1e-3)));
  if (!t) {
    const d = vsub(centerline.lastSegment.point, centerline.firstSegment.point);
    return Math.atan2(d.y, d.x);
  }
  return Math.atan2(t.y, t.x);
}

// A rect defined in a local frame (top-left x,y; size w,h), rotated about the
// local origin by `angle` rad, then translated to `center`. Mirrors Qt
// QTransform().translate(center).rotate(deg).map(rect) (point rotated, then moved).
function localRect(center, x, y, w, h, angle) {
  const r = new paper.Path.Rectangle(new paper.Point(x, y), new paper.Size(w, h));
  r.rotate((angle * 180) / Math.PI, new paper.Point(0, 0));
  r.translate(center);
  return r;
}

// Outer cap half at a START end: keeps the half pointing away from the body.
// `angle` is the tangent at the start (points into the body); `td` = total diameter.
function capOuterStart(center, angle, td) {
  const circle = new paper.Path.Circle(center, td / 2);
  const mask = localRect(center, 0, -td, 2 * td, 2 * td, angle);
  const half = circle.subtract(mask);
  circle.remove();
  mask.remove();
  return half;
}
// Outer cap half at an END end: keeps the half pointing out of the end.
function capOuterEnd(center, angle, td) {
  const circle = new paper.Path.Circle(center, td / 2);
  const mask = localRect(center, -2 * td, -td, 2 * td, 2 * td, angle);
  const half = circle.subtract(mask);
  circle.remove();
  mask.remove();
  return half;
}
function capInner(center, wpx) {
  return new paper.Path.Circle(center, wpx / 2);
}
// Side cover rect: Qt addRect(-sw, -w/2, sw, w) rotated to the tangent.
function capSideRect(center, angle, swpx, wpx) {
  return localRect(center, -swpx, -wpx / 2, swpx, wpx, angle);
}
// Attached-strand end fill quad (attached_strand.py end_side_line_path):
// across = w/2 each way, along the tangent = sw/2 each way.
function capEndQuad(center, angle, swpx, wpx) {
  const perp = angle + Math.PI / 2;
  const dx = (wpx / 2) * Math.cos(perp), dy = (wpx / 2) * Math.sin(perp);
  const dtx = (swpx / 2) * Math.cos(angle), dty = (swpx / 2) * Math.sin(angle);
  return new paper.Path({
    segments: [
      new paper.Point(center.x - dx - dtx, center.y - dy - dty),
      new paper.Point(center.x + dx - dtx, center.y + dy - dty),
      new paper.Point(center.x + dx + dtx, center.y + dy + dty),
      new paper.Point(center.x - dx + dtx, center.y - dy + dty),
    ],
    closed: true,
  });
}

// Collect end-cap pieces (pixel-space paper paths) for one strand, split into the
// stroke-color layer and the fill-color layer.
function collectCaps(s, strands, centerline, P, S) {
  const stroke = [], fill = [];
  const w = s.width || 0, sw = s.stroke_width || 0;
  const td = (w + 2 * sw) * S, wpx = w * S, swpx = sw * S;
  const hc = s.has_circles || [false, false];
  const cc = s.closed_connections || [false, false];
  const startA = circleStrokeAlpha(effStartStroke(s));
  const endA = circleStrokeAlpha(effEndStroke(s));
  const len = centerline.length;
  const cStart = P(s.start), cEnd = P(s.end);
  const aStart = tangentAngle(centerline, 0);
  const aEnd = tangentAngle(centerline, len);
  const childStart = hasAttachedChildAt(s.start, strands, s);
  const childEnd = hasAttachedChildAt(s.end, strands, s);

  if (s.type === 'AttachedStrand') {
    // start (its own attachment point)
    if (hc[0] && startA > 0) {
      stroke.push(capOuterStart(cStart, aStart, td));
      fill.push(capInner(cStart, wpx));
      fill.push(capSideRect(cStart, aStart, swpx, wpx));
    } else if (startA === 0 && s.is_setting_staring_circle !== false && hc[0]) {
      // Unfolded start edge: transparent outline, inner fill circle kept
      // (attached_strand.py:1291+). OSS gates this on is_setting_staring_circle,
      // but that flag is never serialized — the start_circle_stroke_color setter
      // derives it as (alpha == 0) on load (strand.py:534-541) — so with
      // startA === 0 it is always true for loaded OSS files; only an explicit
      // false (editor-supplied) suppresses it.
      fill.push(capInner(cStart, wpx));
    }
    // end — half-circle only when a child attaches there (no alpha gate, per Qt)
    if (hc[1] && childEnd) {
      stroke.push(capOuterEnd(cEnd, aEnd, td));
      fill.push(capInner(cEnd, wpx));
      if (endA > 0) fill.push(capSideRect(cEnd, aEnd, swpx, wpx));
    }
    // end fill is added whenever has_circles[1] (rounds the end)
    if (hc[1]) {
      fill.push(capInner(cEnd, wpx));
      fill.push(capEndQuad(cEnd, aEnd, swpx, wpx));
    }
    // closed-knot end cap
    if (hc[1] && cc[1]) {
      if (endA > 0) stroke.push(capOuterEnd(cEnd, aEnd, td));
      fill.push(capInner(cEnd, wpx));
      if (endA > 0) fill.push(capSideRect(cEnd, aEnd, swpx, wpx));
    }
  } else {
    // plain Strand: cap an end only where a child attaches or the end is closed
    if ((hc[0] && startA > 0 && childStart) || (cc[0] && startA > 0)) {
      stroke.push(capOuterStart(cStart, aStart, td));
      fill.push(capInner(cStart, wpx));
      fill.push(capSideRect(cStart, aStart, swpx, wpx));
    }
    if ((hc[1] && endA > 0 && childEnd) || (cc[1] && endA > 0)) {
      stroke.push(capOuterEnd(cEnd, aEnd, td));
      fill.push(capInner(cEnd, wpx));
      fill.push(capSideRect(cEnd, aEnd, swpx, wpx));
    }
  }
  return { stroke, fill };
}

// Side LINES (strand.py ~2657): a flat stroke-colored bar across an end, drawn
// only when that end has no circle. Returns ready-to-paint paper paths.
function collectSideLines(s, centerline, P, S) {
  const out = [];
  const hc = s.has_circles || [false, false];
  const w = s.width || 0, sw = s.stroke_width || 0;
  const half = ((w + 2 * sw) / 2) * S, shift = (sw / 2) * S, swpx = sw * S;
  const len = centerline.length;
  const bar = (c, a) => {
    const perp = a + Math.PI / 2;
    const dx = half * Math.cos(perp), dy = half * Math.sin(perp);
    const line = new paper.Path.Line(
      new paper.Point(c.x - dx, c.y - dy),
      new paper.Point(c.x + dx, c.y + dy),
    );
    line.strokeColor = toColor(s.stroke_color);
    line.strokeWidth = swpx;
    line.strokeCap = 'butt';
    return line;
  };
  // An AttachedStrand's start is its attachment cap: OSS never draws a start
  // side line there, even with the circle hidden (attached_strand.py:600 only
  // ever draws the END line; strand.py:2766 draws both for a plain Strand).
  // A styled end paints its side line as the band along its profile instead
  // (strand.py _draw_side_lines), so the classic bar is skipped there.
  if (s.type !== 'AttachedStrand' && s.start_line_visible && !hc[0] && !esActiveStyle(s, 0)) {
    const a = tangentAngle(centerline, 0), c = P(s.start);
    // start shift is opposite the tangent (angle + pi)
    out.push(bar({ x: c.x + shift * Math.cos(a + Math.PI), y: c.y + shift * Math.sin(a + Math.PI) }, a));
  }
  if (s.end_line_visible && !hc[1] && !esActiveStyle(s, 1)) {
    const a = tangentAngle(centerline, len), c = P(s.end);
    // end shift is along the tangent
    out.push(bar({ x: c.x + shift * Math.cos(a), y: c.y + shift * Math.sin(a) }, a));
  }
  return out;
}

// ---- Stylized free ends (OSS 1.111 "Stylize End Side", end_style.py) ---------
// A free end (an end with no circle) can carry an end style: the shape of its
// edge (straight / angled / rounded / pointed / notched / concave), a tilt, a
// depth, an extend/trim offset along the tangent, and the thickness / colour of
// the side line drawn along it. Everything rendered at a styled end derives
// from ONE profile P(y) in the local frame of the end (origin at the endpoint,
// +x outward along the tangent, y across the width), exactly as in OSS:
//   * the OUTER footprint (stroke colour) is the flat-capped body with
//     everything beyond the profile removed and the region between the
//     endpoint plane and the profile added;
//   * the INNER fill is the fill body cut back to the side line's inner edge
//     (the profile offset inward by the side-line thickness);
//   * the side-line BAND is the strip between that inner edge and the profile,
//     painted in the side-line colour clipped to the body;
//   * shadows use the outer footprint (pushed outward by the blur margin) and
//     masks intersect the same footprint.
// Nothing ahead of the endpoint plane is ever removed from the classic body, so
// a strand that bends back in front of its own end keeps every pixel it has
// today, and an unstyled strand never enters this code at all (esGeometry
// returns null), so the fidelity oracle is byte-identical.
//
// All lengths here are PIXEL space (world * S), so every absolute constant OSS
// expresses in canvas units (the 0.1 edge clearance, the 0.5 cut plane, the 12
// px zone reach ...) is multiplied by S.

const ES_SHAPES = ['straight', 'angled', 'rounded', 'pointed', 'notched', 'concave'];
const ES_TILT_MAX = 60;
const ES_MIN_LINE_WIDTH = 0.5;
// Qt's path clipper mishandles a polygon vertex that lies exactly on an edge of
// the other operand (and paper's boolean ops are no happier); the cut polygons
// keep this far from the body's long edges and its endpoint plane.
const ES_EDGE_CLEARANCE = 0.1;
// The cut plane sits a hair ahead of the endpoint plane, so the body's own flat
// cap (and the mitre spike a tight bend leaves along it) falls cleanly inside
// the cut instead of straddling its edge.
const ES_CUT_PLANE = 0.5;

// end_style.normalize_style: a clean record, or null for the classic look.
function esNormalize(style) {
  if (!style) return null;
  const num = (v, fb) => { const n = v == null ? NaN : Number(v); return Number.isFinite(n) ? n : fb; };
  const shape = ES_SHAPES.includes(style.shape) ? style.shape : 'straight';
  let tilt = Math.max(-ES_TILT_MAX, Math.min(ES_TILT_MAX, num(style.tilt, 0)));
  if (shape === 'straight') tilt = 0;
  const depth = Math.max(0, Math.min(1, num(style.depth, 0.5)));
  const offset = num(style.offset, 0);
  const lineWidth = style.line_width == null ? null : Math.max(ES_MIN_LINE_WIDTH, num(style.line_width, 0));
  const lc = style.line_color;
  const lineColor = lc && typeof lc === 'object'
    ? { r: num(lc.r, 0), g: num(lc.g, 0), b: num(lc.b, 0), a: num(lc.a, 255) } : null;
  if (shape === 'straight' && Math.abs(tilt) < 1e-9 && Math.abs(offset) < 1e-9 && lineWidth == null && !lineColor) return null;
  return { shape, tilt, depth, offset, line_width: lineWidth, line_color: lineColor };
}

// A style renders only on a FREE end: a circle cap always wins and the style
// goes dormant until the end is free again; an attached strand's start is glued
// to its parent (strand.py _end_style_active). Reads the render-time has_circles.
function esActiveStyle(s, side) {
  const styles = s.end_styles;
  if (!Array.isArray(styles) || styles.length !== 2) return null;
  if (side === 0 && s.type === 'AttachedStrand') return null;
  const hc = s.has_circles || [false, false];
  if (hc[side]) return null;
  return esNormalize(styles[side]);
}

function esHasStyledEnd(s) {
  return s.type !== 'MaskedStrand' && (esActiveStyle(s, 0) !== null || esActiveStyle(s, 1) !== null);
}

// -- profile in the local frame of the end ---------------------------------------
function esProfilePoints(shape, half, depth, tiltDeg, baseX, steps = 24) {
  let pts = [];
  const width = 2 * half;
  if (shape === 'rounded' || shape === 'concave') {
    const r = depth * half, sign = shape === 'rounded' ? 1 : -1;
    for (let i = 0; i <= steps; i++) {
      const y = -half + width * i / steps;
      pts.push({ x: sign * r * Math.sqrt(Math.max(0, 1 - (y / half) * (y / half))), y });
    }
  } else if (shape === 'pointed') {
    pts = [{ x: 0, y: -half }, { x: depth * width, y: 0 }, { x: 0, y: half }];
  } else if (shape === 'notched') {
    pts = [{ x: 0, y: -half }, { x: -depth * width, y: 0 }, { x: 0, y: half }];
  } else {
    pts = [{ x: 0, y: -half }, { x: 0, y: half }];
  }
  // QTransform().translate(base_x, 0).rotate(tilt).map(p): rotate, then shift.
  const a = tiltDeg * Math.PI / 180, c = Math.cos(a), sn = Math.sin(a);
  return esFitToBand(pts.map((p) => ({ x: baseX + p.x * c - p.y * sn, y: p.x * sn + p.y * c })), half);
}

// After a tilt the profile no longer reaches y = +-half. Extend its first and
// last segments straight on until they do (a hair beyond, so the corner never
// sits exactly on the body's edge).
function esFitToBand(pts, half) {
  if (pts.length < 2) return pts;
  half = half + ES_EDGE_CLEARANCE_PX;
  const hit = (a, b, targetY) => {
    const dx = b.x - a.x, dy = b.y - a.y;
    if (Math.abs(dy) < 1e-9) return b;
    const t = (targetY - a.y) / dy;
    return { x: a.x + dx * t, y: targetY };
  };
  const ascending = pts[0].y < pts[pts.length - 1].y;
  const first = hit(pts[1], pts[0], ascending ? -half : half);
  const last = hit(pts[pts.length - 2], pts[pts.length - 1], ascending ? half : -half);
  return [first].concat(pts.slice(1, -1), [last]);
}
// esFitToBand runs inside esProfilePoints, before the StyledEnd knows S; the
// clearance in px is set per end (esStyledEnd) right before the profile is built.
let ES_EDGE_CLEARANCE_PX = ES_EDGE_CLEARANCE;

// Where the profile's chord (first -> last point), continued past both ends,
// reaches |y| = ylim (1.5*half by default). The cut continues straight along
// that line through whatever part of a curved body bulges past the width right
// behind its endpoint, instead of turning square.
function esChordExtended(prof, half, ylim) {
  if (ylim == null) ylim = 1.5 * half;
  const a = prof[0], b = prof[prof.length - 1];
  const dx = b.x - a.x, dy = b.y - a.y;
  if (Math.abs(dy) < 1e-9) return [{ x: a.x, y: -ylim }, { x: b.x, y: ylim }];
  const sgn = dy > 0 ? 1 : -1;
  const ta = (-sgn * ylim - a.y) / dy, tb = (sgn * ylim - a.y) / dy;
  return [{ x: a.x + dx * ta, y: a.y + dy * ta }, { x: a.x + dx * tb, y: a.y + dy * tb }];
}

// The polyline restricted to |y| <= ylim (crossing points inserted).
function esClipPolylineY(pts, ylim) {
  const out = [];
  let prev = null;
  for (const p of pts) {
    const inside = Math.abs(p.y) <= ylim;
    if (prev !== null) {
      const prevInside = Math.abs(prev.y) <= ylim;
      if (prevInside !== inside || (!prevInside && !inside && (prev.y > 0) !== (p.y > 0))) {
        const bounds = prev.y < p.y ? [-ylim, ylim] : [ylim, -ylim];
        for (const bound of bounds) {
          const lo = Math.min(prev.y, p.y), hi = Math.max(prev.y, p.y);
          if (lo < bound && bound < hi) {
            const t = (bound - prev.y) / (p.y - prev.y);
            out.push({ x: prev.x + (p.x - prev.x) * t, y: bound });
          }
        }
      }
    }
    if (inside) out.push(p);
    prev = p;
  }
  return out;
}

// Runs of consecutive points ahead of (x > x0) or behind (x < x0) the plane,
// each starting and ending on the plane.
function esRunsByX(pts, x0, ahead) {
  const runs = [];
  let run = [];
  const cross = (a, b) => { const t = (x0 - a.x) / (b.x - a.x); return { x: x0, y: a.y + (b.y - a.y) * t }; };
  let prev = null;
  for (const p of pts) {
    const keep = ahead ? p.x > x0 : p.x < x0;
    if (prev !== null) {
      const prevKeep = ahead ? prev.x > x0 : prev.x < x0;
      if (prevKeep !== keep) {
        const c = cross(prev, p);
        if (keep) run = [c];
        else { run.push(c); runs.push(run); run = []; }
      }
    }
    if (keep) run.push(p);
    prev = p;
  }
  if (run.length >= 2) runs.push(run);
  return runs.filter((r) => r.length >= 2);
}

// Close each run back along the plane x = x0 into a simple polygon (a point list).
function esRunsToPolygons(runs, x0) {
  return runs.map((run) => [{ x: x0, y: run[0].y }].concat(run, [{ x: x0, y: run[run.length - 1].y }]));
}

// The region between the plane x = x0 (just behind the endpoint) and the
// profile, where the profile is ahead of it, within |y| <= yLim: the cap piece
// ADDED to the classic body. Built directly, so no boolean op is needed.
function esAheadPolygons(prof, half, yLim, x0) {
  const [first, last] = esChordExtended(prof, half, yLim + ES_UNIT_PX);
  const pts = esClipPolylineY([first].concat(prof, [last]), yLim);
  return esRunsToPolygons(esRunsByX(pts, x0, true), x0);
}

// The region outward of the profile but behind the plane x = x0: what a cut
// REMOVES from the classic body. Nothing ahead of the endpoint plane is ever
// removed, so a body that bends back in front of its own end keeps every pixel.
function esBehindPolygons(prof, half, yLim, x0) {
  const [first, last] = esChordExtended(prof, half, yLim);
  return esRunsToPolygons(esRunsByX([first].concat(prof, [last]), x0, false), x0);
}

// Local-frame strip between the profile and its inward offset (the side line's
// inner edge), both continued along their chords to |y| = yLim.
function esBandRegion(prof, innerProf, half, yLim) {
  const [first, last] = esChordExtended(prof, half, yLim);
  // The inner edge continues parallel to the profile's own continuation (its
  // own chord can point elsewhere once a steep flank has been offset).
  const p0 = prof[0], pn = prof[prof.length - 1];
  const i0 = innerProf[0], iN = innerProf[innerProf.length - 1];
  const innerFirst = { x: i0.x + (first.x - p0.x), y: i0.y + (first.y - p0.y) };
  const innerLast = { x: iN.x + (last.x - pn.x), y: iN.y + (last.y - pn.y) };
  return [first].concat(prof, [last, innerLast], innerProf.slice().reverse(), [innerFirst]);
}

// Shift a polyline a hair backwards if any of its vertices (or its chord
// continuation) would sit on the endpoint plane x = 0, where the stroked body
// has vertices of its own.
function esClearOfEndpointPlane(pts) {
  const xs = pts.map((p) => p.x);
  if (pts.length >= 2) {
    const a = pts[0], b = pts[pts.length - 1];
    if (Math.abs(b.y - a.y) > 1e-9) {
      const slope = (b.x - a.x) / (b.y - a.y);
      for (const y of [-2 * Math.abs(a.y) - ES_UNIT_PX, 2 * Math.abs(b.y) + ES_UNIT_PX]) xs.push(a.x + slope * (y - a.y));
    }
  }
  const clearance = ES_EDGE_CLEARANCE_PX;
  if (xs.every((x) => Math.abs(x) >= clearance)) return pts;
  const shift = -clearance - Math.max(...xs.filter((x) => Math.abs(x) < clearance));
  return pts.map((p) => ({ x: p.x + shift, y: p.y }));
}

// The profile moved `distance` inward (toward the strand body) along its own
// normals, with mitred vertices: the inner edge of the side line.
function esOffsetProfile(prof, distance) {
  if (distance <= 0 || prof.length < 2) return prof.slice();
  const normals = [];
  for (let i = 0; i < prof.length - 1; i++) {
    const vx = prof[i + 1].x - prof[i].x, vy = prof[i + 1].y - prof[i].y;
    const len = Math.hypot(vx, vy);
    // Walking the profile from y=-half to y=+half, the body is on the left.
    normals.push(len > 1e-9 ? { x: -vy / len, y: vx / len } : null);
  }
  const result = [];
  for (let i = 0; i < prof.length; i++) {
    const p = prof[i];
    const n1 = i > 0 ? normals[i - 1] : null, n2 = i < normals.length ? normals[i] : null;
    if (!n1 && !n2) { result.push({ x: p.x, y: p.y }); continue; }
    let n, factor;
    if (!n1 || !n2) { n = n2 || n1; factor = 1; } else {
      const sx = n1.x + n2.x, sy = n1.y + n2.y, len = Math.hypot(sx, sy);
      if (len < 1e-9) { n = n1; factor = 1; } else {
        n = { x: sx / len, y: sy / len };
        factor = 1 / Math.max(0.25, n.x * n1.x + n.y * n1.y);
      }
    }
    result.push({ x: p.x + n.x * distance * factor, y: p.y + n.y * distance * factor });
  }
  return result;
}

// Absolute constants OSS writes in canvas units, as pixels for the current
// render (set by esGeometry before any end is built).
let ES_UNIT_PX = 1;

// The local-frame pieces of one styled end, mapped to pixel coordinates.
function esStyledEnd(s, side, style, lineVisible, point, angle, S) {
  const swPx = (s.stroke_width || 0) * S;
  const total = ((s.width || 0) + 2 * (s.stroke_width || 0)) * S;
  const half = total / 2;
  const lineWidth = (style.line_width == null ? (s.stroke_width || 0) : style.line_width) * S;
  const bandWidth = lineVisible ? lineWidth : 0;
  const baseX = bandWidth + style.offset * S;
  const cos = Math.cos(angle), sin = Math.sin(angle);
  const map = (p) => new paper.Point(point.x + p.x * cos - p.y * sin, point.y + p.x * sin + p.y * cos);
  const poly = (pts) => new paper.Path({ segments: pts.map(map), closed: true });

  const profile = esClearOfEndpointPlane(esProfilePoints(style.shape, half, style.depth, style.tilt, baseX));
  const innerProfile = bandWidth > 0 ? esClearOfEndpointPlane(esOffsetProfile(profile, bandWidth)) : profile;
  let maxX = -Infinity, minX = Infinity;
  for (const p of profile) { if (p.x > maxX) maxX = p.x; if (p.x < minX) minX = p.x; }
  const cutPlane = ES_CUT_PLANE * S;
  return {
    side, style, half, total, strokeWidth: swPx, bandWidth, point, angle, cos, sin, map,
    // How far the edge's farthest point sits beyond where the classic end
    // (endpoint plane + side line) would put it, in px: decorations anchored on
    // the endpoint (dash extension, small arrow) are shifted by this.
    extentShift: maxX - bandWidth,
    // Polygons removed from the classic body (outward of the profile, behind
    // the endpoint plane) for a body stroked `margin` wider.
    behindCuts: (margin = 0) => esBehindPolygons(profile, half, 1.5 * half + margin, cutPlane).map(poly),
    // The same for the fill, along the side line's inner edge.
    behindFillCuts: () => esBehindPolygons(bandWidth > 0 ? innerProfile : profile, half, 1.5 * half, cutPlane).map(poly),
    // Polygons added ahead of the endpoint plane to the stroke body of
    // half-width `half + margin`.
    aheadPieces: (margin = 0) => esAheadPolygons(profile, half, half + margin, -ES_UNIT_PX).map(poly),
    // Polygons added ahead of the endpoint plane to the fill body.
    aheadFillPieces: () => esAheadPolygons(bandWidth > 0 ? innerProfile : profile, half, half - swPx, -ES_UNIT_PX).map(poly),
    // The side-line band: the strip between the side line's inner edge and the
    // profile, across exactly the strand's width. A plain polygon, not clipped
    // to the body: callers paint it clipped to the (uncut) body.
    band: () => (bandWidth <= 0 ? null : poly(esBandRegion(profile, innerProfile, half, half + ES_EDGE_CLEARANCE_PX))),
    // Local rectangle around the cap, mapped to pixel coords.
    zone: (margin = 0) => {
      const xMin = Math.min(minX, -ES_UNIT_PX) - 2 * margin - 2 * ES_UNIT_PX;
      const xMax = maxX + half + margin + 12 * ES_UNIT_PX;
      const y = 1.5 * half + margin;
      return poly([{ x: xMin, y: -y }, { x: xMax, y: -y }, { x: xMax, y }, { x: xMin, y }]);
    },
  };
}

// Boolean helpers on paper items. Each consumes its operands.
function esSubtractAll(base, cuts) {
  let out = base;
  for (const cut of cuts) {
    if (!out) { cut.remove(); continue; }
    const r = out.subtract(cut);
    out.remove(); cut.remove();
    out = r;
  }
  return out;
}
function esUniteAll(base, pieces) {
  let out = base;
  for (const piece of pieces) {
    if (!out) { out = piece; continue; }
    const r = out.unite(piece);
    out.remove(); piece.remove();
    out = r;
  }
  return out;
}

// Outer footprint / inner fill / side-line bands of a strand whose free end(s)
// carry a style (end_style.EndStyleGeometry), or null when no end is styled.
// Owns nothing that outlives the render: every path it hands out is fresh and
// the caller removes it, like every other builder here.
// Per-render memo of the descriptor below, keyed by layer name: the highlight,
// the body, both extension rays, both small arrows and every footprint width
// ask for the same strand's ends in one frame. It holds plain numbers and
// closures (no paper items), so it is cleared with the geometry memo rather
// than held in it. The centerline is rebuilt only for the ends' frames, which
// depend on nothing but the strand and the render-wide constants.
let ES_CACHE = null;
function esCacheBegin() { ES_CACHE = new Map(); }
function esCacheEnd() { ES_CACHE = null; }

function esGeometry(s, P, enableThird, S, centerline) {
  if (!esHasStyledEnd(s)) return null;
  const live = ES_CACHE !== null && geomCacheLive();
  if (live && ES_CACHE.has(s.layer_name)) return ES_CACHE.get(s.layer_name);
  const g = esBuildGeometry(s, P, enableThird, S, centerline);
  if (live) ES_CACHE.set(s.layer_name, g);
  return g;
}

function esBuildGeometry(s, P, enableThird, S, centerline) {
  const cl = centerline || buildCenterline(s, P, enableThird);
  const len = cl.length;
  ES_UNIT_PX = S;
  ES_EDGE_CLEARANCE_PX = ES_EDGE_CLEARANCE * S;
  const ends = {};
  for (const side of [0, 1]) {
    const style = esActiveStyle(s, side);
    if (!style) continue;
    const visible = side === 0 ? s.start_line_visible !== false : s.end_line_visible !== false;
    // end_frame: the endpoint and the OUTWARD tangent angle (the start tangent
    // points into the body, so it is flipped).
    const point = P(side === 0 ? s.start : s.end);
    const angle = side === 0 ? tangentAngle(cl, 0) + Math.PI : tangentAngle(cl, len);
    ends[side] = esStyledEnd(s, side, style, visible, point, angle, S);
  }
  if (!centerline) cl.remove();
  const width = (s.width || 0) * S;
  const total = ((s.width || 0) + 2 * (s.stroke_width || 0)) * S;
  const list = Object.values(ends);
  const each = (fn) => list.flatMap(fn);
  // Body builders go through the per-render memos (bodyOutline / bodyBand),
  // never the caller's centerline: the descriptor outlives this call.
  const classicClean = (w) => bodyOutline(s, P, enableThird, w);
  const classicRaw = (w) => bodyBand(s, P, enableThird, w);

  const geometry = {
    ends,
    // (classic − cuts) ∪ pieces, for the path consumers. The classic body is the
    // CLEANED outline (paper's boolean ops need a simple input; Qt's clipper
    // takes the raw WindingFill stroker output).
    outer: (margin = 0) => {
      const base = classicClean(total + 2 * margin);
      if (!base) return null;
      let out = esSubtractAll(base, each((e) => e.behindCuts(margin)));
      out = esUniteAll(out, each((e) => e.aheadPieces(margin)));
      if (out) out.fillRule = 'nonzero';
      return out;
    },
    inner: () => {
      const base = classicClean(width);
      if (!base) return null;
      let out = esSubtractAll(base, each((e) => e.behindFillCuts()));
      out = esUniteAll(out, each((e) => e.aheadFillPieces()));
      if (out) out.fillRule = 'nonzero';
      return out;
    },
    // The outer footprint pushed outward by `margin` (shadow and mask helpers).
    // Unstyled ends keep the classic flat cap (the body is simply stroked
    // wider, exactly like the classic shadow and mask helpers); styled ends get
    // the exact offset of their profile.
    dilated: (margin) => {
      if (margin <= 0) return geometry.outer();
      let result = geometry.outer(margin);
      const outer = geometry.outer();
      if (!result || !outer) { outer && outer.remove(); return result; }
      for (const e of list) {
        const z = e.zone(margin);
        const piece = outer.intersect(z);
        z.remove();
        if (piece && piece.area && Math.abs(piece.area) > 0.5) {
          // A hair wider than the body stroke so the union never sees two
          // coincident long edges.
          const ring = strokedRegionOutline(piece, 2 * (margin + 0.3 * S));
          let grown = piece;
          if (ring) { grown = piece.unite(ring); piece.remove(); ring.remove(); }
          const u = result.unite(grown);
          result.remove(); grown.remove();
          result = u;
        } else {
          piece && piece.remove();
        }
      }
      outer.remove();
      if (result) result.fillRule = 'nonzero';
      return result;
    },
    // PAINT bodies: the raw stroker band plus the cap pieces, as one
    // WindingFill path each (no boolean ops — see windingFillLayer), to be
    // painted under the matching keep-clip.
    bodyPieces: (extra) => {
      const band = classicRaw(total);
      return band ? [band].concat(each((e) => e.aheadPieces()), extra || []) : null;
    },
    fillPieces: (extra) => {
      const band = classicRaw(width);
      return band ? [band].concat(each((e) => e.aheadFillPieces()), extra || []) : null;
    },
    // Winding-filled clip: a big rectangle (+1) minus the cut polygons
    // (oriented against the rectangle). Clip paths honour fill rules, so this
    // is exact where a boolean subtraction of the raw band is not.
    keepClip: (bounds, cuts) => {
      const pad = 6 * total + 20 * S;
      const rect = new paper.Path.Rectangle(bounds.expand(2 * pad));
      rect.clockwise = true;
      for (const cut of cuts) cut.clockwise = false;
      return new paper.CompoundPath({ children: [rect].concat(cuts), fillRule: 'nonzero' });
    },
    keepOuterClip: (bounds) => geometry.keepClip(bounds, each((e) => e.behindCuts())),
    keepInnerClip: (bounds) => geometry.keepClip(bounds, each((e) => e.behindFillCuts())),
    band: (side) => (ends[side] ? ends[side].band() : null),
    extentShift: (side) => (ends[side] ? ends[side].extentShift : 0),
    isStyled: (side) => !!ends[side],
  };
  return geometry;
}

// The strand's rendered footprint at world width `widthW`, the way every
// shadow and mask helper asks for it: the classic cleaned outline when no end
// is styled, else the styled footprint that width maps to — the fill area for
// the strand's own width, the outer footprint for width + 2*stroke, and the
// outer footprint pushed outward by half the excess for anything wider
// (masked_strand.py _styled_footprint's inner / margin arguments). Memoized per
// render like bodyOutline. Returns an owned path or null.
function strandFootprintAtWidth(s, P, enableThird, S, widthW) {
  if (!esHasStyledEnd(s)) return bodyOutline(s, P, enableThird, widthW * S);
  return cachedGeom(`esfoot|${s.layer_name}|${widthW}`, () => {
    const g = esGeometry(s, P, enableThird, S);
    if (!g) return bodyOutline(s, P, enableThird, widthW * S);
    const w = s.width || 0, total = w + 2 * (s.stroke_width || 0);
    if (Math.abs(widthW - w) < 1e-6) return g.inner();
    if (widthW <= total + 1e-6) return g.outer();
    return g.dilated(((widthW - total) / 2) * S);
  });
}

// Endpoint shifted to the styled edge's farthest point along the outward
// tangent, in WORLD units: the anchor for the dash extension and the small
// arrow, so they never sit on top of an extended cap or float away from a
// trimmed one (strand.py _end_anchor). Unstyled ends return the endpoint.
function esEndAnchor(s, side, worldPt, outwardAngle, P, enableThird, S, centerline) {
  const g = esGeometry(s, P, enableThird, S, centerline);
  if (!g) return worldPt;
  const shift = g.extentShift(side) / S;
  if (Math.abs(shift) < 1e-9) return worldPt;
  return { x: worldPt.x + Math.cos(outwardAngle) * shift, y: worldPt.y + Math.sin(outwardAngle) * shift };
}

// A box covering the last `distance` px of an UNSTYLED end (plus the room
// outside it), bounded by the end's perpendicular plane so a body that curls
// back past the endpoint is left alone (strand.py _end_slab). Pixel space.
function esEndSlab(s, side, point, outwardAngle, distancePx, S) {
  const full = ((s.width || 0) + 2 * (s.stroke_width || 0)) * S;
  const half = full / 2 + 12 * S;
  const depth = distancePx + full;
  const ox = Math.cos(outwardAngle), oy = Math.sin(outwardAngle);
  const px = -oy, py = ox;
  const near = { x: point.x - ox * distancePx, y: point.y - oy * distancePx };
  return new paper.Path({
    segments: [
      new paper.Point(near.x + px * half, near.y + py * half),
      new paper.Point(near.x - px * half, near.y - py * half),
      new paper.Point(near.x - px * half + ox * depth, near.y - py * half + oy * depth),
      new paper.Point(near.x + px * half + ox * depth, near.y + py * half + oy * depth),
    ],
    closed: true,
  });
}

// ---- shadow geometry (PIXEL space) -----------------------------------------
// Faithful port of shader_utils.py's three geometry builders. All world widths
// and radii are multiplied by S (= ss*zoom) before being handed to Paper. The
// circle gating mirrors build_rendered_geometry / build_shadow_circle_geometry:
// a circle contributes only where computeHasCircles is true AND the matching
// circle-stroke alpha > 0 (a transparent cap is excluded). AttachedStrand caps
// are HALF-circles (same capOuterStart/capOuterEnd construction the body uses);
// plain Strand caps are full circles. The angle is the centerline tangent at
// the relevant end (tangentAngle(cl,0) / (cl,len)).

// build_rendered_geometry(strand): the strand's visible footprint = body stroked
// at (w+2sw) UNION every visible end-circle (radius (w+2sw)/2, NOT +2). This is
// the RECEIVER geometry the caster shadow is intersected with, and also the clip
// region for Pass B. Returns a paper path (caller removes it) or null.
function buildShadowReceiverGeom(s, strands, P, enableThird, S) {
  const w = s.width || 0, sw = s.stroke_width || 0;
  const td = (w + 2 * sw) * S;          // full diameter (px) for the body + cap circles
  const cl = buildCenterline(s, P, enableThird);
  // A stylized free end replaces the flat cap with its own footprint
  // (shader_utils.py build_rendered_geometry, 1.111).
  let path = esHasStyledEnd(s)
    ? strandFootprintAtWidth(s, P, enableThird, S, w + 2 * sw)
    : bodyOutline(s, P, enableThird, td, cl);
  if (!path) { cl.remove(); return null; }
  const hc = s.has_circles || [false, false];
  const startA = circleStrokeAlpha(effStartStroke(s));
  const endA = circleStrokeAlpha(effEndStroke(s));
  const len = cl.length;
  const isAttached = s.type === 'AttachedStrand';
  const addCircle = (centre, angle, which) => {
    let circle;
    if (isAttached) {
      circle = which === 0 ? capOuterStart(centre, angle, td) : capOuterEnd(centre, angle, td);
    } else {
      circle = new paper.Path.Circle(centre, td / 2);
    }
    const u = path.unite(circle);
    path.remove();
    circle.remove();
    path = u;
  };
  if (hc[0] && startA > 0) addCircle(P(s.start), tangentAngle(cl, 0), 0);
  if (hc[1] && endA > 0) addCircle(P(s.end), tangentAngle(cl, len), 1);
  cl.remove();
  return path;
}

// build_shadow_geometry(strand, 0, include_circles=False): the caster CORE =
// body stroked at (w+2sw) with NO blur inflation, no circles. Returns a paper
// path (caller removes it) or null.
function buildShadowCasterCore(s, P, enableThird, S) {
  const w = s.width || 0, sw = s.stroke_width || 0;
  // Stylized free ends: the styled footprint, so the cast shadow follows the
  // end's profile (shader_utils.py build_shadow_geometry, 1.111).
  return strandFootprintAtWidth(s, P, enableThird, S, w + 2 * sw);
}

// Cut the caster CORE at every UNFOLDED end. Faithful port of the transparent-
// circle subtraction in draw_strand_shadow (shader_utils.py:528-556): for each end
// idx that is has_circles[idx] AND has a transparent circle stroke (alpha 0), Qt
// subtracts a FULL circle of radius adj_radius = (w+2sw)/1.5 centred at start
// (idx 0) / end (idx 1) from the square-capped body core, so the unfolded end (an
// unfolded plain strand OR an unfolded AttachedStrand start) casts a rounded, cut-
// back footprint instead of a square end-cap halo. Returns the (possibly new,
// possibly empty) core; the caller removes it. Radius uses the *S convention.
function subtractTransparentEndCaps(core, s, P, S) {
  const hc = s.has_circles || [false, false];
  if (!hc[0] && !hc[1]) return core;
  const w = s.width || 0, sw = s.stroke_width || 0;
  const r = ((w + 2 * sw) / 1.5) * S;
  const startA = circleStrokeAlpha(effStartStroke(s));
  const endA = circleStrokeAlpha(effEndStroke(s));
  let out = core;
  const cut = (centre) => {
    if (!out) return;
    const c = new paper.Path.Circle(centre, r);
    const d = out.subtract(c);
    c.remove();
    out.remove();
    out = d;
  };
  if (hc[0] && startA === 0) cut(P(s.start));
  if (hc[1] && endA === 0) cut(P(s.end));
  return out;
}

// build_shadow_circle_geometry(strand): caster end-circles only, radius
// ((w+2sw)/2 + 2)*S (the +2 IS scaled). The MAX_BLUR vs MAX_BLUR+2 arg distinction
// is moot — the builder always uses (w+2sw)/2+2 for the radius. Qt
// build_shadow_circle_geometry builds each visible end circle via
// _cap_shadow_path(idx, radius, depth_margin=2) (shader_utils.py:1806); with
// _partner_cap_dims == (None,None) — always true while elliptical_end_caps is off
// (the whole corpus) — that returns a FULL circle (strand.py:392-397), for BOTH
// plain and attached strands. So the caster shadow circle is a full circle, not a
// half circle, on the attached starting side too. (The RECEIVER geometry in
// buildShadowReceiverGeom keeps half-circles to match build_rendered_geometry —
// that is a different path and stays as-is.) May return null when no visible
// circle exists.
function buildShadowCasterCircles(s, P, S) {
  const w = s.width || 0, sw = s.stroke_width || 0;
  const radius = ((w + 2 * sw) / 2 + 2) * S;
  const hc = s.has_circles || [false, false];
  const startA = circleStrokeAlpha(effStartStroke(s));
  const endA = circleStrokeAlpha(effEndStroke(s));
  let path = null;
  const addCircle = (centre) => {
    const circle = new paper.Path.Circle(centre, radius);
    if (!path) { path = circle; return; }
    const u = path.unite(circle);
    path.remove();
    circle.remove();
    path = u;
  };
  if (hc[0] && startA > 0) addCircle(P(s.start));
  if (hc[1] && endA > 0) addCircle(P(s.end));
  return path;
}

// Build the per-step width/alpha table from the shader_utils formulas so it
// tracks NUM_STEPS / MAX_BLUR rather than being hard-coded. Each entry:
//   progress = (NUM_STEPS - i) / NUM_STEPS
//   alphaByte = trunc(150 * progress * (1/NUM_STEPS) * 2)   [TRUNCATE, clamp 0..255]
//   width = MAX_BLUR * ((i+1)/NUM_STEPS)   (world px, scaled by S at draw time)
// For NUM_STEPS=2: [{w:15, a:150}, {w:30, a:75}].
function shadowBlurSteps() {
  const base = SHADOW_COLOR.a;
  const steps = [];
  for (let i = 0; i < NUM_STEPS; i++) {
    const progress = (NUM_STEPS - i) / NUM_STEPS;
    const alpha = Math.max(0, Math.min(255, Math.trunc(base * progress * (1 / NUM_STEPS) * 2)));
    const width = MAX_BLUR * ((i + 1) / NUM_STEPS);
    steps.push({ width, alpha });
  }
  return steps;
}

// Cast strand `s` (at list index `i`) onto every already-drawn lower strand
// (j < i). Faithful port of draw_strand_shadow:
//   • caster CORE  = build_shadow_geometry(s, 0, include_circles=False)
//   • caster CIRCLES = build_shadow_circle_geometry(s)  (radius (w+2sw)/2+2)
//   For each receiver o (gated by §3): region = (core ∪ circles) ∩ rendered(o).
//     Accumulate non-empty survivors into `combined` (UNION) and the receiver
//     geometry into `clip` (UNION).
//   PASS A: fill `combined` SOLID at alpha 150, SourceOver, UNCLIPPED.
//   PASS B: total = combined ∪ circles; in a Group clipped to `clip`, run
//     NUM_STEPS boundary-stroke passes over `total` (FlatCap / RoundJoin) with
//     the computed width/alpha table.
// Both passes reuse the same `combined`. Drawn BEFORE the caster's own body so
// the body covers the inner shadow and only the fringe over lower strands shows.
// Per-pair survivor region for caster `s` (rank i) onto receiver `o` (rank j):
// receiver rendered geometry, caster∩receiver, then the renderer's subtractions
// IN ORDER (Qt: subtracted_layers -> mask-blocking -> intermediate). Shared by
// castStrandShadow and the auto_shadow probe so the two can never diverge.
// Returns {region, recv, clipBlocker} — any may be null; the CALLER removes all
// three paths. `rejectBounds` (optional) short-circuits far-away receivers.
function buildPairShadowRegion(s, i, o, j, strands, byLayer, P, enableThird, S, casterFootprint, ov, allowFull, rejectBounds) {
  // A mask receiver uses its crossing FILL region (get_proper_masked_strand_path
  // = get_mask_path); a regular/attached receiver uses its rendered body+circles.
  // Memoized per render: the same receiver is visited once per caster above it,
  // and its geometry is identical every time (see the geometry memo above).
  const recvKey = 'recv|' + o.layer_name;
  const recvBuild = () => (o.type === 'MaskedStrand'
    ? buildMaskPath(o, byLayer, P, enableThird, S)
    : buildShadowReceiverGeom(o, strands, P, enableThird, S));
  // Bounding-box reject BEFORE the clone. The original built the full receiver
  // path and then threw it away when the bounds missed; with the memo the bounds
  // are already known, so a far-apart pair costs nothing at all.
  const recvBounds = cachedGeomBounds(recvKey, recvBuild);
  if (recvBounds !== undefined) {
    if (!recvBounds) return { region: null, recv: null, clipBlocker: null };
    if (rejectBounds && !rejectBounds.intersects(recvBounds)) {
      return { region: null, recv: null, clipBlocker: null };
    }
  }
  const recv = cachedGeom(recvKey, recvBuild);
  if (!recv) return { region: null, recv: null, clipBlocker: null };
  if (rejectBounds && !rejectBounds.intersects(recv.bounds)) {
    recv.remove();
    return { region: null, recv: null, clipBlocker: null };
  }
  let region = casterFootprint.intersect(recv);
  let clipBlocker = null; // this pair's subtracted-layer union (Qt clip_blocker_path)
  if (region && region.area && Math.abs(region.area) > 0.5) {
    // (a) subtracted_layers (UNGATED). Default = masked-caster second-component
    //     branch when no override key is present.
    const subNames = (ov && ov.subtracted_layers) || defaultSubtracted(s, o, byLayer);
    const subAcc = { path: null };
    region = subtractLayers(region, subNames, byLayer, strands, P, enableThird, S, subAcc);
    clipBlocker = subAcc.path; // fed into the Pass B clip (shader_utils.py:985-987)

    // (b) mask-blocking (gated !allowFull): subtract every VISIBLE mask whose
    //     layer rank is strictly ABOVE the caster (k > i) and that is not the
    //     receiver itself. Same blocker geometry covers the visible-component
    //     mask-coverage case for our corpus (single mask above both indices).
    if (!allowFull && region && Math.abs(region.area || 0) > 0.5) {
      for (let k = i + 1; k < strands.length; k++) {
        const m = strands[k];
        if (m.type !== 'MaskedStrand' || m.is_hidden === true) continue;
        if (m.layer_name === o.layer_name) continue; // self-block guard
        // Memoized: the blocker for a given mask is the same for every pair it
        // blocks, and it is one of the most expensive builds in the renderer
        // (two mask regions plus a stroked boundary).
        const blk = cachedGeom('blocker|' + m.layer_name,
          () => buildShadowBlockerPath(m, byLayer, P, enableThird, S));
        if (blk) {
          const r = region.subtract(blk);
          blk.remove();
          region.remove();
          region = r;
        }
        if (!region || Math.abs(region.area || 0) <= 0.5) break;
      }
    }

    // (c) intermediate subtraction (gated !allowFull): subtract every layer
    //     strictly between receiver rank j and caster rank i.
    if (!allowFull && region && Math.abs(region.area || 0) > 0.5) {
      const interNames = [];
      for (let m = j + 1; m < i; m++) interNames.push(strands[m].layer_name);
      region = subtractLayers(region, interNames, byLayer, strands, P, enableThird, S);
    }
  }
  return { region, recv, clipBlocker };
}

// The full arrow's own casting footprint (strand.py get_arrow_shadow_path,
// :1110-1155): the whole centerline stroked at arrow_line_width, plus the head
// triangle whose BASE sits on the endpoint and whose tip extends outward along
// the tangent. Returns null unless the arrow is visible AND opted into casting.
// Gated on arrow_casts_shadow, which every OSS drawing path defaults to false, so
// a fixture that never sets it produces exactly the previous footprint.
function buildArrowShadowPath(s, P, enableThird, S) {
  if (s.full_arrow_visible !== true || s.arrow_casts_shadow !== true) return null;
  const cl = buildCenterline(s, P, enableThird);
  const len = cl.length;
  if (len <= 0) { cl.remove(); return null; }
  let out = strokedOutline(cl, ARROW_PARAMS.line_width * S);
  if (out) {
    const cleaned = out.resolveCrossings();
    if (cleaned !== out) { out.remove(); out = cleaned; }
  }
  if (s.arrow_head_visible !== false) {
    const a = tangentAngle(cl, len);
    const ux = Math.cos(a), uy = Math.sin(a);
    const px = -uy, py = ux;
    const hw = (ARROW_PARAMS.head_width * S) / 2, hl = ARROW_PARAMS.head_length * S;
    const e = P(s.end);
    const head = new paper.Path([
      new paper.Point(e.x + ux * hl, e.y + uy * hl),   // tip
      new paper.Point(e.x + px * hw, e.y + py * hw),   // base left
      new paper.Point(e.x - px * hw, e.y - py * hw),   // base right
    ]);
    head.closed = true;
    if (out) {
      const u = out.unite(head);
      out.remove(); head.remove();
      out = u;
    } else {
      out = head;
    }
  }
  cl.remove();
  return out;
}

// The caster half of castStrandShadow, lifted out verbatim so the Shadow Path
// preview overlay computes its geometry through exactly this code rather than a
// second copy of it. A preview that can disagree with the shadow it previews is
// worse than no preview, and a copy WOULD drift: this block already carries four
// separate Qt quirks (mask casters drop their circles, transparent end caps are
// cut, the arrow unites in, the reject bounds are the CORE's).
// Returns null when the caster has no drawable footprint. The caller owns both
// returned paths and must remove() them.
function buildCasterFootprint(s, byLayer, P, enableThird, S) {
  let core, circles = null;
  if (s.type === 'MaskedStrand') {
    core = buildMaskPath(s, byLayer, P, enableThird, S);
    if (!core) return;
  } else {
    core = buildShadowCasterCore(s, P, enableThird, S);
    if (!core) return;
    // Unfolded (transparent-circle) ends cast NO square end-cap halo: Qt
    // draw_strand_shadow subtracts a full circle of radius (w+2sw)/1.5 from the
    // caster CORE at every end that is has_circles[idx] AND transparent (circle
    // stroke alpha 0) BEFORE the receiver intersection (shader_utils.py:528-556).
    // Cut here — inside the render path only, NOT in buildShadowCasterCore — so
    // the auto_shadow probe (computeShadowPairAreas) keeps OSS's un-cut raw
    // footprint (auto_shadow.py) and the two never desync.
    core = subtractTransparentEndCaps(core, s, P, S);
    if (!core) return;
    // OSS unites the full arrow into the caster when arrow_casts_shadow is on
    // (strand.py:2281). Added AFTER the transparent-end-cap subtraction so the
    // arrow is not clipped by a cut that describes the body's own end.
    const arrow = buildArrowShadowPath(s, P, enableThird, S);
    if (arrow) {
      const u = core.unite(arrow);
      core.remove(); arrow.remove();
      core = u;
    }
    circles = buildShadowCasterCircles(s, P, S);
  }

  // The caster's combined casting footprint (core ∪ circles), used both for the
  // intersection with each receiver and as the boundary stroked in Pass B.
  let casterFootprint = core.clone();
  if (circles) {
    const u = casterFootprint.unite(circles);
    casterFootprint.remove();
    casterFootprint = u;
  }

  // Inflated-bbox quick reject bound: the caster core's bounds grown by MAX_BLUR*S
  // (mirrors shader_utils.py:688-702). A receiver whose bounds don't overlap this
  // can't receive any blur fringe, so the pair is skipped before the boolean ops.
  const rejectBounds = core.bounds.expand(2 * MAX_BLUR * S);
  return { core, circles, casterFootprint, rejectBounds };
}

// OSS's Shadow Path preview (strand_drawing_canvas.py:2794-2822): for each pair
// the shadow editor has toggled on, paint that pair's computed shadow region as a
// translucent blue overlay so the user can see WHERE a shadow actually lands.
// Drawn last, over the finished image, and never persisted — it is an inspection
// aid, not part of the drawing.
//
// The geometry comes from buildPairShadowRegion, the same function the real
// shadow uses. OSS instead has a parallel implementation for the preview
// (shader_utils.py calculate_shadow_for_layer_pair, :1936) which re-derives the
// same pipeline and has already drifted from the renderer in one place — it
// inflates the caster's circle geometry by max_blur_radius+2 where the render
// path uses max_blur_radius. Sharing the one function is the point of a preview:
// a preview that can disagree with the shadow it previews is worse than none.
//
// Visibility is gated exactly as castStrandShadow gates it, so a pair the port
// would not draw previews as nothing — which is also what OSS does (:1986).
function drawVisibleShadowPaths(strands, byLayer, P, enableThird, S) {
  if (!VISIBLE_SHADOW_PATHS.length) return;
  const rank = new Map();
  for (let k = 0; k < strands.length; k++) rank.set(strands[k].layer_name, k);

  for (const pair of VISIBLE_SHADOW_PATHS) {
    if (!Array.isArray(pair) || pair.length < 2) continue;
    const castName = pair[0], recvName = pair[1];
    const i = rank.get(castName), j = rank.get(recvName);
    // Shadow only falls downward, so a receiver at or above the caster has no
    // region to show (OSS returns an empty path for it, :1957).
    if (i == null || j == null || j >= i) continue;
    const sCast = strands[i], oRecv = strands[j];
    if (sCast.is_hidden === true || oRecv.is_hidden === true) continue;

    const ov = (SHADOW_OVERRIDES[castName] || {})[recvName] || null;
    if (ov && ov.visibility != null) {
      if (ov.visibility === false) continue;
    } else if (defaultShadowVisibilityFalse(sCast, oRecv)) {
      continue;
    }

    const fp = buildCasterFootprint(sCast, byLayer, P, enableThird, S);
    if (!fp) continue;
    const pr = buildPairShadowRegion(
      sCast, i, oRecv, j, strands, byLayer, P, enableThird, S,
      fp.casterFootprint, ov, !!(ov && ov.allow_full_shadow), fp.rejectBounds);

    if (pr.region && pr.region.area && Math.abs(pr.region.area) > 0.5) {
      pr.region.fillColor = new paper.Color(0, 120 / 255, 1, 100 / 255);
      pr.region.strokeColor = new paper.Color(0, 120 / 255, 1, 200 / 255);
      // Scale by S like every other stroke here, so the 2px Qt pen stays 2px on
      // screen instead of thinning as the supersample rises.
      pr.region.strokeWidth = 2 * S;
    } else if (pr.region) {
      pr.region.remove();
    }
    if (pr.recv) pr.recv.remove();
    fp.casterFootprint.remove();
    fp.core.remove();
    fp.circles && fp.circles.remove();
  }
}

function castStrandShadow(s, strands, byLayer, P, enableThird, S, maskPairs, i) {
  // Caster footprint. A MaskedStrand caster uses its mask-crossing region as the
  // core and casts NO circles (Qt get_proper_masked_strand_path excludes circles);
  // a body strand uses the stroked body core + visible end circles.
  const fp = buildCasterFootprint(s, byLayer, P, enableThird, S);
  if (!fp) return;
  const { core, circles, casterFootprint, rejectBounds } = fp;

  let combined = null;          // PASS A/B survivor union (caster ∩ receivers)
  let clip = null;              // PASS B clip = ⋃ receiver rendered geometry
  for (let j = 0; j < i; j++) {
    const o = strands[j];
    // A hidden strand paints nothing, so it receives nothing (Qt
    // draw_strand_shadow skips hidden receivers, shader_utils.py:623). Absent/
    // false on every fixture, so the oracle is unchanged.
    if (o.is_hidden === true) continue;
    // A mask CAN receive a shadow from a higher strand (Qt draw_strand_shadow uses
    // other_stroke_path = get_proper_masked_strand_path when the receiver has
    // get_mask_path, shader_utils.py:718-722). A hidden mask draws nothing so it
    // receives nothing; and a mask never receives a shadow from one of its own
    // components (it owns that crossing region).
    if (o.type === 'MaskedStrand') {
      if (o.is_hidden === true) continue;
      const comp = (o.layer_name || '').split('_');
      if (comp.length >= 4 &&
          (s.layer_name === comp[0] + '_' + comp[1] || s.layer_name === comp[2] + '_' + comp[3])) continue;
    }
    if (maskPairs.has(s.layer_name + '|' + o.layer_name)) continue; // same-mask component pair

    // Per-pair shadow override (keyed [caster][receiver]). allow_full_shadow gates
    // mask-blocking + intermediate.
    const ov = (SHADOW_OVERRIDES[s.layer_name] || {})[o.layer_name] || null;
    // Effective visibility: an explicit `visibility` key wins; otherwise the Qt
    // default (get_default_shadow_visibility) — false ONLY for a masked caster onto
    // its FIRST component (so a mask never casts a regular shadow on its source).
    if (ov && ov.visibility != null) {
      if (ov.visibility === false) continue;
    } else if (defaultShadowVisibilityFalse(s, o)) {
      continue;
    }
    const allowFull = !!(ov && ov.allow_full_shadow);

    const { region, recv, clipBlocker } = buildPairShadowRegion(
      s, i, o, j, strands, byLayer, P, enableThird, S, casterFootprint, ov, allowFull, rejectBounds);
    if (!recv) continue;

    if (region && region.area && Math.abs(region.area) > 0.5) {
      // survivor — accumulate into combined (union)
      if (!combined) { combined = region; }
      else { const u = combined.unite(region); combined.remove(); region.remove(); combined = u; }
      // accumulate receiver geometry into the Pass B clip (union)
      if (!clip) { clip = recv; }
      else { const u = clip.unite(recv); clip.remove(); recv.remove(); clip = u; }
      // Qt subtracts this pair's subtracted-layer geometry from the accumulated
      // clip so the faded Pass B stroke can't bleed into it (shader_utils.py:985-987).
      if (clipBlocker) { const c = clip.subtract(clipBlocker); clip.remove(); clip = c; }
    } else {
      region && region.remove();
      recv.remove();
    }
    if (clipBlocker) clipBlocker.remove();
  }

  if (combined) {
    // PASS A — solid core, unclipped, full alpha (SourceOver = paper default).
    const solid = combined.clone();
    solid.fillColor = SHADOW_PAINT;
    solid.strokeColor = null;

    // PASS B — faded blur, clipped to the union of receiver geometries.
    let total = combined.clone();
    if (circles) {
      const u = total.unite(circles);
      total.remove();
      total = u;
    }
    const strokeItems = [];
    for (const st of shadowBlurSteps()) {
      const item = total.clone();
      item.fillColor = null;
      item.strokeColor = new paper.Color(SHADOW_COLOR.r / 255, SHADOW_COLOR.g / 255, SHADOW_COLOR.b / 255, st.alpha / 255);
      item.strokeWidth = st.width * S;
      item.strokeCap = 'butt';   // Qt FlatCap
      item.strokeJoin = 'round'; // Qt RoundJoin
      strokeItems.push(item);
    }
    total.remove();
    // A clipped Group: first child is the clip mask, the rest are clipped to it.
    new paper.Group({ children: [clip, ...strokeItems], clipped: true });
    combined.remove();
  } else if (clip) {
    clip.remove();
  }

  casterFootprint.remove();
  core.remove();
  circles && circles.remove();
}

// Selection highlight — faithful port of strand.py::_draw_unified_highlight /
// attached_strand.py::_draw_unified_highlight. Drawn UNDER the body (drawStrand
// paints the body fill+stroke over it, exactly as OSS draws the highlight at
// strand.py:2483 then the body at :2485+), so only the outer ~5px halo, the
// protruding flat-end side-line bars, and the C-shape rings remain visible while
// the black stroke stays on top. Gated on s.is_selected (absent in oracle
// fixtures, so it never affects a pixel-diff that doesn't opt in).
function drawHighlight(s, strands, P, enableThird, S) {
  if (!s.is_selected || s.type === 'MaskedStrand') return;
  const w = s.width || 0, sw = s.stroke_width || 0;
  const td = (w + 2 * sw) * S;       // total diameter (px)
  const cr = td / 2;                 // circle radius (px)
  const hcA = s.highlight_color;
  const red = toColor(hcA && hcA.a != null ? hcA : HIGHLIGHT_COLOR);
  const hc = s.has_circles || [false, false];
  const cc = s.closed_connections || [false, false];
  const startA = circleStrokeAlpha(effStartStroke(s));
  const endA = circleStrokeAlpha(effEndStroke(s));
  const isAttached = s.type === 'AttachedStrand';
  const childStart = hasAttachedChildAt(s.start, strands, s);
  const childEnd = hasAttachedChildAt(s.end, strands, s);

  const cl = buildCenterline(s, P, enableThird);
  const len = cl.length;
  const items = [];

  // (1) body band: centerline stroked at total+10 (solid; the body covers its
  // inner half, leaving the 5px outer halo). An unfolded (transparent-stroke)
  // edge pulls the band in along the curve — OSS resamples 100 points between
  // t_start/t_end (attached_strand.py:564-583: 5.5 start / 3.5 end;
  // strand.py:2090-2095: 5.0 both) whenever either edge is unfolded and the
  // path is longer than 10.
  let band = cl.clone();
  // Stylized free ends (1.111, strand.py highlight_footprint_path): the styled
  // footprint already carries the cap and the band, so the halo is a 10px ring
  // along its boundary (Qt strokes the footprint outline 10 wide); an unstyled
  // end with a transparent circle stroke is trimmed by an end slab instead of
  // the resampled band below.
  const styledGeom = esGeometry(s, P, enableThird, S, cl);
  // The same outer footprint the shadow caster / receiver ask for (memoized).
  const styledFootprint = styledGeom ? strandFootprintAtWidth(s, P, enableThird, S, w + 2 * sw) : null;
  if (styledFootprint) {
    band.remove();
    let fp = styledFootprint;
    for (const side of [0, 1]) {
      const alpha = side === 0 ? startA : endA;
      if (alpha !== 0 || styledGeom.isStyled(side)) continue;
      const trim = (side === 0 ? (isAttached ? 5.5 : 5.0) : (isAttached ? 3.5 : 5.0)) * S;
      const angle = side === 0 ? tangentAngle(cl, 0) + Math.PI : tangentAngle(cl, len);
      const slab = esEndSlab(s, side, P(side === 0 ? s.start : s.end), angle, trim, S);
      const cut = fp.subtract(slab);
      fp.remove(); slab.remove();
      fp = cut;
    }
    band = fp;
    band.fillColor = red;
    band.strokeColor = red;
    band.strokeWidth = 10 * S;
    band.strokeCap = 'butt';
    band.strokeJoin = 'miter';
    items.push(band);
  } else if ((startA === 0 || endA === 0) && len > 10 * S) {
    const tS = startA === 0 ? (isAttached ? 5.5 : 5.0) * S : 0;
    const tE = endA === 0 ? (isAttached ? 3.5 : 5.0) * S : 0;
    const pts = [];
    for (let i = 0; i <= 100; i++) {
      const off = tS + (len - tE - tS) * (i / 100);
      pts.push(cl.getPointAt(Math.max(0, Math.min(len, off))));
    }
    band.remove();
    band = new paper.Path({ segments: pts });
  }
  if (!styledFootprint) {
    band.strokeColor = red;
    band.strokeWidth = td + 10 * S;
    band.strokeCap = 'butt';
    band.strokeJoin = 'round';
    band.fillColor = null;
    items.push(band);
  }

  // Which ends carry a circle (-> C-shape ring) vs a flat side line. Mirrors the
  // cap/side-line gating in collectCaps / collectSideLines so the highlight always
  // matches the junction the body actually draws.
  const startCircle = isAttached
    ? (hc[0] && startA > 0)
    : ((hc[0] && startA > 0 && childStart) || (cc[0] && startA > 0));
  const endCircle = isAttached
    ? (hc[1] && endA > 0 && (childEnd || cc[1]))
    : ((hc[1] && endA > 0 && childEnd) || (cc[1] && endA > 0));

  // (2) C-shape rings: highlight_circle(cr+5) - mask(half-plane toward body) -
  // outer_circle(cr). Same boolean construction as Qt.
  const cShape = (center, angle) => {
    const outer = new paper.Path.Circle(center, cr + 5 * S);
    const inner = new paper.Path.Circle(center, cr);
    const ring = outer.subtract(inner); outer.remove(); inner.remove();
    const mask = localRect(center, 0, -td, 2 * td, 2 * td, angle); // +x_local = toward body
    const c = ring.subtract(mask); ring.remove(); mask.remove();
    c.fillColor = red; c.strokeColor = null;
    items.push(c);
  };
  if (startCircle) cShape(P(s.start), tangentAngle(cl, 0));            // tangent into body
  if (endCircle) cShape(P(s.end), tangentAngle(cl, len) + Math.PI);   // angle_end - pi

  // (3) side lines: a flat red bar across each circle-less, visible end.
  const hhw = cr + 5 * S;            // highlight half width
  const barW = (sw + 10) * S;
  const bar = (center, a, shiftSign) => {
    const cx = center.x + (sw * S / 2) * Math.cos(a) * shiftSign;
    const cy = center.y + (sw * S / 2) * Math.sin(a) * shiftSign;
    const perp = a + Math.PI / 2;
    const dx = hhw * Math.cos(perp), dy = hhw * Math.sin(perp);
    const line = new paper.Path.Line(new paper.Point(cx - dx, cy - dy), new paper.Point(cx + dx, cy + dy));
    line.strokeColor = red; line.strokeWidth = barW; line.strokeCap = 'butt';
    items.push(line);
  };
  // A styled end's band lies inside the styled footprint (strand.py:2367-2385
  // gate the bars on `not self._end_style_active(side)`).
  const styled0 = !!(styledGeom && styledGeom.isStyled(0)), styled1 = !!(styledGeom && styledGeom.isStyled(1));
  if (s.start_line_visible !== false && !hc[0] && startA > 0 && !styled0) bar(P(s.start), tangentAngle(cl, 0), -1);  // shift opposite tangent
  if (s.end_line_visible !== false && !hc[1] && endA > 0 && !styled1) bar(P(s.end), tangentAngle(cl, len), 1);       // shift along tangent

  cl.remove();
  if (items.length) new paper.Group(items);
}

// ---- Arrows (OSS 1.109 §7: strand.py start/end arrows + full strand arrow) --
// Canvas-level arrow dimensions (Qt settings dialog; the oracle renders with
// these defaults). The editor may override via meta.arrow_params.
// Dashed extension lines (Settings -> Layer Panel). Canvas-level like the arrow
// dimensions; extension_dash_width falls back to the strand's own stroke_width
// when unset (strand.py:2783).
const EXTENSION_DEFAULTS = { length: 100, dash_count: 10, dash_width: null, dash_gap_length: null };
let EXTENSION_PARAMS = EXTENSION_DEFAULTS;

const ARROW_DEFAULTS = {
  head_length: 20, head_width: 10, gap_length: 10,
  line_length: 20, line_width: 10, head_stroke_width: 4,
};
let ARROW_PARAMS = ARROW_DEFAULTS;

// ---- Dashed extension lines (strand.py:2779-2815) -------------------------
// A straight dashed ray running OUT of each end along that end's tangent, gated
// per-strand on start/end_extension_visible. Faithful details:
//   * colour  = stroke_color with its alpha REPLACED by the fill colour's alpha
//     (side_color, :2776-2777) — not the stroke's own alpha;
//   * width   = extension_dash_width, defaulting to this strand's stroke_width;
//   * dashes  = ext_len / (2 * dash_count) on and the same off. Qt expresses a
//     CustomDashLine pattern in units of PEN WIDTH, so its pattern_len =
//     dash_seg / dash_width becomes dash_seg once multiplied back out — which is
//     what a canvas dash array wants directly;
//   * offset  = extension_dash_gap_length NEGATED (:2788), applied to BOTH
//     endpoints, so the ray slides along its own direction rather than growing.
//     Absent, it defaults to dash_seg.
// The rays are straight lines, not curve continuations: OSS takes the unit
// tangent once and walks it (:2798-2815).
// Absent flags => nothing drawn, so the fidelity oracle is unaffected.
function drawExtensions(s, P, enableThird, S) {
  const wantStart = s.start_extension_visible === true;
  const wantEnd = s.end_extension_visible === true;
  if (!wantStart && !wantEnd) return;

  const ep = EXTENSION_PARAMS;
  const extLen = ep.length;
  const dashCount = ep.dash_count;
  const dashWidth = ep.dash_width != null ? ep.dash_width : (s.stroke_width || 0);
  const dashSeg = dashCount > 0 ? extLen / (2 * dashCount) : extLen;
  const dashGap = -(ep.dash_gap_length != null ? ep.dash_gap_length : dashSeg);
  if (dashWidth <= 0) return;

  const col = toColor(s.stroke_color);
  col.alpha = ((s.color && s.color.a != null ? s.color.a : 255)) / 255;

  const cl = buildCenterline(s, P, enableThird);
  const len = cl.length;
  if (len <= 0) { cl.remove(); return; }

  const ray = (worldPt, angle, sign) => {
    // sign +1 walks along the tangent (the END ray), -1 against it (the START).
    const ux = Math.cos(angle) * sign, uy = Math.sin(angle) * sign;
    const a = P(worldPt);
    const b = P({ x: worldPt.x + ux * extLen, y: worldPt.y + uy * extLen });
    // OSS shifts BOTH endpoints by the same vector, expressed against the RAW
    // tangent: +unit*dash_gap at the start (:2803-2804), -unit*dash_gap at the end
    // (:2812-2813). `ux` already carries `sign`, so folding the two cases together
    // leaves -ux*dash_gap, which slides the ray along its own direction (dash_gap
    // is itself negated, so a positive gap setting pushes the ray outward).
    const ox = -ux * dashGap * S, oy = -uy * dashGap * S;
    const line = new paper.Path.Line(
      new paper.Point(a.x + ox, a.y + oy),
      new paper.Point(b.x + ox, b.y + oy),
    );
    line.strokeColor = col;
    line.strokeWidth = dashWidth * S;
    line.strokeCap = 'butt';
    line.dashArray = [dashSeg * S, dashSeg * S];
  };

  // A stylized free end anchors its ray on the styled edge's farthest point
  // (strand.py _end_anchor), never on top of an extended cap.
  const aS = tangentAngle(cl, 0), aE = tangentAngle(cl, len);
  if (wantStart) ray(esEndAnchor(s, 0, s.start, aS + Math.PI, P, enableThird, S, cl), aS, -1);
  if (wantEnd) ray(esEndAnchor(s, 1, s.end, aE, P, enableThird, S, cl), aE, 1);
  cl.remove();
}

// ---- Arrow patterns (strand.py apply_arrow_texture_brush / draw_arrow_shaft_with_pattern)
//
// Qt paints these with QBrush(QPixmap) — a tiled bitmap brush. Paper.js has no
// pattern fill, so the same tile is reproduced as GEOMETRY: the tile's strokes and
// dots are emitted across the shape's bounding box and clipped to the shape. The
// tile is a fixed pixel grid in Qt, and OSS never calls setBrushTransform, so the
// brush rides the painter transform and the tile scales with zoom — hence * S.
//
// PORT-FOR-COMPLETENESS / UNMEASURED: no fixture in the corpus sets arrow_texture
// or arrow_shaft_style (both default to the plain value), so the Qt pixel oracle
// never exercises these paths and cannot confirm them. Same standing as
// drawMaskShadow above.
function tiledInside(shape, tilePx, emit) {
  // `shape` is consumed: it becomes the clip mask of the returned group.
  const b = shape.bounds;
  if (!b || b.width <= 0 || b.height <= 0 || tilePx <= 0) { shape.remove(); return null; }
  const items = [];
  const x0 = Math.floor(b.left / tilePx) * tilePx;
  const y0 = Math.floor(b.top / tilePx) * tilePx;
  // Guard against a pathological tile/bounds ratio producing millions of items.
  const cols = Math.ceil((b.right - x0) / tilePx), rows = Math.ceil((b.bottom - y0) / tilePx);
  if (cols * rows > 20000) { shape.remove(); return null; }
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) emit(x0 + c * tilePx, y0 + r * tilePx, items);
  }
  if (!items.length) { shape.remove(); return null; }
  const g = new paper.Group([shape, ...items]);
  g.clipped = true;
  return g;
}

// Head fill texture. Qt's tile is 10x10 with the ARROW FILL COLOUR as the pen
// (strand.py:1002-1041), drawn over the already-filled triangle.
function applyArrowTexture(shape, texture, fillColor, S) {
  const tile = 10 * S;
  if (texture === 'stripes') {
    // pen(fill, 2), vertical lines at i = 0,3,6,9
    return tiledInside(shape, tile, (tx, ty, out) => {
      for (let i = 0; i < 10; i += 3) {
        const ln = new paper.Path.Line(
          new paper.Point(tx + i * S, ty), new paper.Point(tx + i * S, ty + tile));
        ln.strokeColor = fillColor; ln.strokeWidth = 2 * S; ln.strokeCap = 'butt';
        out.push(ln);
      }
    });
  }
  if (texture === 'dots') {
    // NoPen, brush(fill), drawEllipse(x-1, y-1, 2, 2) for x,y in 2,6 -> r=1 dots
    return tiledInside(shape, tile, (tx, ty, out) => {
      for (let x = 2; x < 10; x += 4) {
        for (let y = 2; y < 10; y += 4) {
          const d = new paper.Path.Circle(new paper.Point(tx + x * S, ty + y * S), 1 * S);
          d.fillColor = fillColor; d.strokeColor = null;
          out.push(d);
        }
      }
    });
  }
  if (texture === 'crosshatch') {
    // pen(fill, 1), lines at i = 0,3,6,9 in BOTH axes
    return tiledInside(shape, tile, (tx, ty, out) => {
      for (let i = 0; i < 10; i += 3) {
        const v = new paper.Path.Line(
          new paper.Point(tx + i * S, ty), new paper.Point(tx + i * S, ty + tile));
        const h = new paper.Path.Line(
          new paper.Point(tx, ty + i * S), new paper.Point(tx + tile, ty + i * S));
        for (const ln of [v, h]) { ln.strokeColor = fillColor; ln.strokeWidth = 1 * S; ln.strokeCap = 'butt'; }
        out.push(v, h);
      }
    });
  }
  shape.remove();
  return null;   // 'none' -> the solid fill already drawn is the whole story
}

// Shaft overlay. OSS always strokes the shaft SOLID first, then paints the
// pattern inside the stroke outline (strand.py:871-882). The overlays are
// translucent white/black diagonals, so they read as shading on any shaft colour.
function applyArrowShaftPattern(shaftPath, style, lineW, S) {
  if (style !== 'tiles' && style !== 'stripes' && style !== 'dots') return;
  const outline = strokedOutline(shaftPath, lineW);
  if (!outline) return;

  if (style === 'tiles') {
    // 12px tile, two diagonals, white @80/255, pen 3 (strand.py:896-912).
    const tile = 12 * S;
    const col = toColor({ r: 255, g: 255, b: 255, a: 80 });
    tiledInside(outline, tile, (tx, ty, out) => {
      for (const [x1, y1, x2, y2] of [[0, tile, tile, 0], [-tile / 2, tile, tile / 2, 0]]) {
        const ln = new paper.Path.Line(
          new paper.Point(tx + x1, ty + y1), new paper.Point(tx + x2, ty + y2));
        ln.strokeColor = col; ln.strokeWidth = 3 * S; ln.strokeCap = 'butt';
        out.push(ln);
      }
    });
    return;
  }

  if (style === 'stripes') {
    // Slash density derived from the shaft width (strand.py:928-931): stripe
    // width = clamp(lineW * 0.22, 2, 6), spacing = max(stripe * 1.6, 5),
    // tile = spacing * 2 so the period tiles exactly. Bright and dark pens
    // alternate. lineW here is already in PIXELS, so undo S for the ratio.
    const wWorld = lineW / S;
    const stripeW = Math.max(2, Math.min(6, Math.trunc(wWorld * 0.22)));
    const spacing = Math.max(Math.trunc(stripeW * 1.6), 5);
    const tile = spacing * 2 * S;
    const bright = toColor({ r: 255, g: 255, b: 255, a: 80 });
    const dark = toColor({ r: 0, g: 0, b: 0, a: 80 });
    tiledInside(outline, tile, (tx, ty, out) => {
      const half = tile / 2;
      const mk = (off, col) => {
        const ln = new paper.Path.Line(
          new paper.Point(tx + off, ty + tile), new paper.Point(tx + off + tile, ty));
        ln.strokeColor = col; ln.strokeWidth = stripeW * S; ln.strokeCap = 'butt';
        out.push(ln);
      };
      mk(0, bright);
      mk(half, dark);
    });
    return;
  }

  // dots: a light stipple over the shaft.
  const tile = 8 * S;
  const col = toColor({ r: 255, g: 255, b: 255, a: 90 });
  tiledInside(outline, tile, (tx, ty, out) => {
    const d = new paper.Path.Circle(new paper.Point(tx + tile / 2, ty + tile / 2), Math.max(1, 1.5 * S));
    d.fillColor = col; d.strokeColor = null;
    out.push(d);
  });
}

// Arrow-head FILL colour, with OSS's inverted default rule (strand.py:2310-2313,
// 1098-1106; attached_strand.py:765-771). The setting is labelled "Use Default
// Arrow Color", but the branch is `if NOT use_default_arrow_color: use
// canvas.default_arrow_fill_color`. So leaving the box UNticked is what makes the
// configured default colour apply; ticking it hands the head back to the strand's
// own colour. Reproduced as-is — the label is upstream's to fix.
let USE_DEFAULT_ARROW_COLOR = true;
let DEFAULT_ARROW_FILL = null;
function defaultArrowFill(s) {
  if (!USE_DEFAULT_ARROW_COLOR && DEFAULT_ARROW_FILL) return DEFAULT_ARROW_FILL;
  return s.color;
}

// Draw a strand's arrows AFTER its body (start/end arrows, then the full
// arrow on top) — faithful to strand.py:2818-3000:
//   * start/end arrow: gap -> shaft segment -> head, along the tangent at the
//     end, pointing AWAY from the body. Shaft pen = stroke_color at
//     arrow_line_width (FlatCap); head = triangle (tip extends head_length
//     past the shaft) filled with the STRAND color, bordered with
//     stroke_color at head_stroke_width (MiterJoin/FlatCap).
//   * full arrow: the whole strand path stroked at arrow_line_width
//     (FlatCap/RoundJoin) in arrow_color (fallback stroke_color), plus a head
//     whose BASE sits ON the end point and whose tip extends outward; head
//     fill = arrow_color (fallback strand color), border = stroke_color.
//     arrow_transparency (0-100 %) REPLACES the alpha (Qt setAlphaF) on the
//     full arrow's shaft + head fill only — never on borders or on start/end
//     arrows.
// Deferred (defaults 'solid'/'none' draw identically): shaft patterns
// (stripes/tiles/dots), head textures, arrow_casts_shadow, and the
// hidden-strand full arrow (the editor drops hidden strands pre-render).
function drawArrows(s, P, enableThird, S) {
  const hasAny = s.start_arrow_visible === true || s.end_arrow_visible === true ||
    s.full_arrow_visible === true;
  if (!hasAny) return;
  const ap = ARROW_PARAMS;
  const texture = s.arrow_texture || 'none';
  const shaftStyle = s.arrow_shaft_style || 'solid';
  const headL = ap.head_length * S, headW = ap.head_width * S;
  const gapL = ap.gap_length * S, lineL = ap.line_length * S, lineW = ap.line_width * S;
  const borderW = ap.head_stroke_width * S;
  const cl = buildCenterline(s, P, enableThird);
  const len = cl.length;
  if (len <= 0) { cl.remove(); return; }

  const drawHead = (base, dir, fillColor) => {
    const perp = { x: -dir.y, y: dir.x };
    const tip = new paper.Point(base.x + dir.x * headL, base.y + dir.y * headL);
    const left = new paper.Point(base.x + perp.x * headW / 2, base.y + perp.y * headW / 2);
    const right = new paper.Point(base.x - perp.x * headW / 2, base.y - perp.y * headW / 2);
    const poly = new paper.Path([tip, left, right]);
    poly.closed = true;
    poly.fillColor = fillColor;
    poly.strokeColor = null;
    // Texture rides ON TOP of the solid fill (OSS sets the textured brush and
    // fills the same triangle), and UNDER the border, which is stroked last.
    if (texture !== 'none') applyArrowTexture(poly.clone(), texture, fillColor, S);
    const border = poly.clone();
    border.fillColor = null;
    border.strokeColor = toColor(s.stroke_color);
    border.strokeWidth = borderW;
    border.strokeJoin = 'miter';
    border.strokeCap = 'butt';
  };

  // tangentAngle points INTO the body at off=0 and OUT of it at off=len, so
  // the start arrow flips the direction (OSS arrow_dir = -unit at the start).
  const endArrow = (worldPt, angle, flip) => {
    const dir = { x: Math.cos(angle) * flip, y: Math.sin(angle) * flip };
    const p0 = P(worldPt);
    const s0 = new paper.Point(p0.x + dir.x * gapL, p0.y + dir.y * gapL);
    const s1 = new paper.Point(s0.x + dir.x * lineL, s0.y + dir.y * lineL);
    const shaft = new paper.Path.Line(s0, s1);
    shaft.strokeColor = toColor(s.stroke_color);
    shaft.strokeWidth = lineW;
    shaft.strokeCap = 'butt';
    drawHead(s1, dir, toColor(defaultArrowFill(s)));
  };

  // The small arrows anchor on a stylized end's farthest edge point too
  // (strand.py _end_anchor); the full arrow's head stays on the endpoint.
  if (s.start_arrow_visible === true) {
    const a = tangentAngle(cl, 0);
    endArrow(esEndAnchor(s, 0, s.start, a + Math.PI, P, enableThird, S, cl), a, -1);
  }
  if (s.end_arrow_visible === true) {
    const a = tangentAngle(cl, len);
    endArrow(esEndAnchor(s, 1, s.end, a, P, enableThird, S, cl), a, 1);
  }

  if (s.full_arrow_visible === true) {
    const alpha = Math.max(0, Math.min(100, s.arrow_transparency != null ? s.arrow_transparency : 100)) / 100;
    const shaftColor = toColor(s.arrow_color ? s.arrow_color : s.stroke_color);
    shaftColor.alpha = alpha;
    const shaft = cl.clone();
    shaft.fillColor = null;
    shaft.strokeColor = shaftColor;
    shaft.strokeWidth = lineW;
    shaft.strokeCap = 'butt';
    shaft.strokeJoin = 'round';
    // The pattern overlay goes on after the solid shaft, clipped to its outline.
    applyArrowShaftPattern(cl, shaftStyle, lineW, S);
    if (s.arrow_head_visible !== false) {
      const a = tangentAngle(cl, len);
      const dir = { x: Math.cos(a), y: Math.sin(a) };
      const fill = toColor(s.arrow_color ? s.arrow_color : defaultArrowFill(s));
      fill.alpha = alpha;
      drawHead(P(s.end), dir, fill);
    }
  }
  cl.remove();
}

function drawStrand(s, strands, P, enableThird, S) {
  drawHighlight(s, strands, P, enableThird, S);   // under the body
  const centerline = buildCenterline(s, P, enableThird);
  const w = s.width || 0, sw = s.stroke_width || 0;
  // Qt strokes the body TWICE — once at width+2*stroke for the stroke layer and
  // once at width for the fill layer — and adds each layer's caps to that layer's
  // own WindingFill path (strand.py:2510-2600).
  const band = bodyBand(s, P, enableThird, (w + 2 * sw) * S, centerline);
  const inner = bodyBand(s, P, enableThird, w * S, centerline);
  if (!band || !inner) {
    band && band.remove();
    inner && inner.remove();
    centerline.remove();
    return;
  }

  const caps = collectCaps(s, strands, centerline, P, S);
  const sideLines = collectSideLines(s, centerline, P, S);

  // Stylized free ends (OSS 1.111 strand.py draw + _paint_body_paths): the
  // bodies are the uncut extended bands plus the cap pieces, painted with the
  // painter clipped to everything but the cut polygons; the side line of a
  // styled end is its band, clipped to the uncut body.
  const geometry = esGeometry(s, P, enableThird, S, centerline);
  centerline.remove();
  if (geometry) {
    band.remove();
    inner.remove();
    const strokePath = windingFillLayer(geometry.bodyPieces(caps.stroke), toColor(s.stroke_color));
    const fillPath = windingFillLayer(geometry.fillPieces(caps.fill), toColor(s.color));
    const bounds = (strokePath || fillPath).bounds;
    const layers = [];
    if (strokePath) layers.push(new paper.Group({ children: [geometry.keepOuterClip(bounds), strokePath], clipped: true }));
    if (fillPath) layers.push(new paper.Group({ children: [geometry.keepInnerClip(bounds), fillPath], clipped: true }));
    layers.push(...sideLines);
    for (const side of [0, 1]) {
      if (!geometry.isStyled(side)) continue;
      const visible = side === 0 ? s.start_line_visible !== false : s.end_line_visible !== false;
      if (!visible) continue;
      const bandPath = geometry.band(side);
      if (!bandPath) continue;
      const style = geometry.ends[side].style;
      bandPath.fillColor = toColor(style.line_color || s.stroke_color);
      bandPath.strokeColor = null;
      // The band is a plain strip; the (uncut) body clips it.
      const clip = windingFillLayer(geometry.bodyPieces(), 'black');
      if (!clip) { bandPath.remove(); continue; }
      layers.push(new paper.Group({ children: [clip, bandPath], clipped: true }));
    }
    new paper.Group(layers.filter(Boolean));
  } else {
    const strokePath = windingFillLayer([band, ...caps.stroke], toColor(s.stroke_color));
    const fillPath = windingFillLayer([inner, ...caps.fill], toColor(s.color));

    // Paint stroke layer, then fill layer, then side bars (top), in order.
    new paper.Group([strokePath, fillPath, ...sideLines].filter(Boolean));
  }

  // Extension rays sit above the body and BELOW the arrows, matching OSS's
  // in-draw order (:2779 extensions, then :2818 arrow heads).
  drawExtensions(s, P, enableThird, S);

  // Arrows go over this strand's body (start/end arrows, then the full arrow
  // on top) but under any later strand, exactly like OSS's in-draw ordering.
  drawArrows(s, P, enableThird, S);
}

// A deletion rectangle (over-under gap) in pixel space. Corner-based
// ([x,y] arrays) or axis-aligned {x,y,width,height}; world coords via P.
function deletionPath(rect, P, ss) {
  if (rect.top_left && rect.bottom_right) {
    const tl = rect.top_left, br = rect.bottom_right;
    const tr = rect.top_right || br, bl = rect.bottom_left || tl;
    const A = (a) => P({ x: a[0], y: a[1] });
    const path = new paper.Path([A(tl), A(tr), A(br), A(bl)]);
    path.closed = true;
    return path;
  }
  if (rect.x != null && rect.width != null) {
    return new paper.Path.Rectangle(P({ x: rect.x, y: rect.y }), new paper.Size(rect.width * ss, rect.height * ss));
  }
  return null;
}

// A mask-component region for `s` at world width `widthW`: the centerline
// stroked at that width, unioned with the strand's visible attached start circle
// (radius widthW/2). Mirrors masked_strand.py get_*_path_for_strand for the
// circular case (elliptical caps are not exercised by the corpus).
function maskComponentPath(s, P, enableThird, S, widthW) {
  // A component with a stylized free end contributes its styled footprint at
  // this width (masked_strand.py _styled_footprint), so the mask follows a
  // trimmed, angled or extended end.
  let path = strandFootprintAtWidth(s, P, enableThird, S, widthW);
  if (!path) return null;
  if (
    s.type === 'AttachedStrand' &&
    (s.has_circles || [])[0] &&
    circleStrokeAlpha(effStartStroke(s)) > 0
  ) {
    const circle = new paper.Path.Circle(P(s.start), (widthW * S) / 2);
    const u = path.unite(circle);
    path.remove();
    circle.remove();
    path = u;
  }
  return path;
}

function subtractDeletions(region, ms, P, S) {
  if (!region) return region;
  for (const rect of ms.deletion_rectangles || []) {
    const rp = deletionPath(rect, P, S);
    if (rp) {
      const r2 = region.subtract(rp);
      rp.remove();
      region.remove();
      region = r2;
    }
  }
  return region;
}

// ---- shadow-override support helpers (Item-2 port) --------------------------

// Intersection of a mask's two component bodies (stroked at the given widths)
// minus deletion rects, EXCLUDING end circles. Shared core for Qt's two mask
// geometries (these match drawMasked's fillRegion / strokeRegion exactly):
//   'fill'   = get_mask_path()        = first@fw        ∩ second@(sw+2ssw+4)
//   'stroke' = get_mask_path_stroke() = first@(fw+2fsw) ∩ second@(sw+2ssw)
function maskRegion(ms, byLayer, P, enableThird, S, mode) {
  const parts = (ms.layer_name || '').split('_');
  if (parts.length < 4) return null;
  const first = byLayer[parts[0] + '_' + parts[1]];
  const second = byLayer[parts[2] + '_' + parts[3]];
  if (!first || !second) return null;
  const fw = first.width || 0, fsw = first.stroke_width || 0;
  const sw = second.width || 0, ssw = second.stroke_width || 0;
  const wA = mode === 'fill' ? fw : fw + 2 * fsw;
  const wB = mode === 'fill' ? sw + 2 * ssw + 4 : sw + 2 * ssw;
  // Memoized per render and keyed by (component, width): a mask's fill and stroke
  // regions ask for the same two component outlines at four widths, and a strand
  // that is a component of several masks is stroked once per mask. The intersect
  // and the deletion-rectangle subtraction below stay per call, so the region
  // handed back is always a fresh, caller-owned path.
  const a = cachedGeom(`mcomp|${first.layer_name}|${wA}`,
    () => maskComponentPath(first, P, enableThird, S, wA));
  const b = cachedGeom(`mcomp|${second.layer_name}|${wB}`,
    () => maskComponentPath(second, P, enableThird, S, wB));
  if (!a || !b) { a && a.remove(); b && b.remove(); return null; }
  let region = a.intersect(b);
  a.remove();
  b.remove();
  region = subtractDeletions(region, ms, P, S);
  if (region && region.area && Math.abs(region.area) > 0.5) return region;
  region && region.remove();
  return null;
}

// Qt get_proper_masked_strand_path -> get_mask_path() (the FILL region). Used as
// the mask-as-caster footprint and the mask-as-subtractor so both agree with
// drawMasked's fillRegion. Returns a paper path (caller removes) or null.
function buildMaskPath(ms, byLayer, P, enableThird, S) {
  return maskRegion(ms, byLayer, P, enableThird, S, 'fill');
}

// Qt get_mask_path_stroke() (the STROKE region) — the wider crossing footprint.
function buildMaskStrokePath(ms, byLayer, P, enableThird, S) {
  return maskRegion(ms, byLayer, P, enableThird, S, 'stroke');
}

// Qt _get_mask_visual_path = get_mask_path() UNION get_mask_path_stroke(). This
// is the blocker BASE (the full visible mask footprint), not the fill region alone.
function buildMaskVisualPath(ms, byLayer, P, enableThird, S) {
  const fill = buildMaskPath(ms, byLayer, P, enableThird, S);
  const stroke = buildMaskStrokePath(ms, byLayer, P, enableThird, S);
  if (!fill) return stroke;
  if (!stroke) return fill;
  const u = fill.unite(stroke);
  fill.remove();
  stroke.remove();
  return u;
}

// Stroke a CLOSED region's boundary by the full pen width `widthPx` with the given
// join/cap, converted to a filled outline. Qt's QPainterPathStroker.setWidth(w)
// strokes w/2 each side; pass the FULL width here (so for the blocker, MAX_BLUR*S).
// Reuses the strokedOutline sampling machinery on each sub-path's boundary, offset
// by +/- half-width, joined into a closed ring. This is a round/round-equivalent
// approximation on the mask region's boundary (the miter/flat detail is a minor
// fringe effect on the small blocker region — see ITEM2_SPEC §EDIT 3 note).
function strokedRegionOutline(region, widthPx) {
  if (!region || widthPx <= 0) return null;
  const half = widthPx / 2;
  // A region from a boolean op may be a CompoundPath (multiple sub-paths). Stroke
  // each closed boundary and union the resulting bands.
  const subs = region.children && region.children.length ? region.children : [region];
  let out = null;
  for (const sub of subs) {
    const len = sub.length;
    if (!len) continue;
    const N = Math.max(8, Math.ceil(len / SAMPLE_STEP));
    const left = [], right = [];
    for (let i = 0; i <= N; i++) {
      const off = Math.min(len * i / N, len - 1e-4);
      // One location lookup + plain arithmetic, same as strokedOutline above.
      const loc = sub.getLocationAt(off);
      const pt = loc && loc.point;
      const nrm = loc && loc.normal;
      if (!pt || !nrm) continue;
      left.push([pt.x + nrm.x * half, pt.y + nrm.y * half]);
      right.push([pt.x - nrm.x * half, pt.y - nrm.y * half]);
    }
    if (left.length < 2) continue;
    right.reverse();
    let band = new paper.Path({ segments: left.concat(right), closed: true });
    const cleaned = band.resolveCrossings();
    if (cleaned !== band) { band.remove(); band = cleaned; }
    if (!out) { out = band; }
    else { const u = out.unite(band); out.remove(); band.remove(); out = u; }
  }
  return out;
}

// Port of get_shadow_blocker_path (shader_utils.py:1876) + _get_mask_visual_path:
// base = mask VISUAL path (fill ∪ stroke regions); blocker = base UNION
// stroke(base boundary, width=MAX_BLUR*S). Subtracted from a caster->receiver
// shadow for a VISIBLE mask layered ABOVE the caster. Returns a path or null.
function buildShadowBlockerPath(ms, byLayer, P, enableThird, S) {
  const base = buildMaskVisualPath(ms, byLayer, P, enableThird, S);
  if (!base) return null;
  const stroked = strokedRegionOutline(base, MAX_BLUR * S);
  if (!stroked) return base; // degrade to base-only blocker
  const u = base.unite(stroked);
  base.remove();
  stroked.remove();
  return u;
}

// Subtract the rendered geometry of each named layer from `region`, IN ORDER.
// Masks use their mask path; hidden strands are skipped. Port of Qt
// _subtract_named_layer_paths. Returns the (possibly empty/null) region; the
// caller owns it. Breaks early once the region empties.
function subtractLayers(region, names, byLayer, strands, P, enableThird, S, blockerAcc) {
  if (!region || !names || !names.length) return region;
  for (const name of names) {
    const t = byLayer[name];
    if (!t || t.is_hidden === true) continue;
    // Same geometry the receiver pass builds, so it shares the same memo entry.
    // This is the O(N^3) leg of the old cost: every (caster, receiver) pair
    // subtracted every layer between them, rebuilding each one from scratch.
    const geom = cachedGeom('recv|' + name, () => (t.type === 'MaskedStrand'
      ? buildMaskPath(t, byLayer, P, enableThird, S)
      : buildShadowReceiverGeom(t, strands, P, enableThird, S)));
    if (!geom) continue;
    // Accumulate the union of subtracted geometry for the caller's clip blocker
    // (Qt _subtract_named_layer_paths returns this alongside the trimmed region).
    if (blockerAcc) {
      if (!blockerAcc.path) { blockerAcc.path = geom.clone(); }
      else { const u = blockerAcc.path.unite(geom); blockerAcc.path.remove(); blockerAcc.path = u; }
    }
    const r = region.subtract(geom);
    geom.remove();
    region.remove();
    region = r;
    if (!region || Math.abs(region.area || 0) <= 0.5) break;
  }
  return region;
}

// Qt get_default_shadow_visibility: a masked caster does NOT cast a regular
// shadow onto its own FIRST component by default (returns true otherwise). The
// SECOND component still receives (with the first component subtracted — see
// defaultSubtracted). Only consulted when no explicit `visibility` override.
function defaultShadowVisibilityFalse(s, o) {
  if (s.type !== 'MaskedStrand') return false;
  const parts = (s.layer_name || '').split('_');
  if (parts.length < 4) return false;
  const firstName = parts[0] + '_' + parts[1];
  return o.layer_name === firstName;
}

// Qt get_default_subtracted_layers: a masked caster's SECOND-component receiver
// defaults to subtracting the FIRST component's geometry. Returns [] otherwise.
function defaultSubtracted(s, o, byLayer) {
  if (s.type !== 'MaskedStrand') return [];
  const parts = (s.layer_name || '').split('_');
  if (parts.length < 4) return [];
  const firstName = parts[0] + '_' + parts[1];
  const secondName = parts[2] + '_' + parts[3];
  return o.layer_name === secondName ? [firstName] : [];
}

// Faithful port of draw_mask_strand_shadow (shader_utils.py:179). PORT-FOR-
// COMPLETENESS / UNMEASURED — no mask fixture in the corpus exercises this at the
// pixel level (the two masks in overhand_knot are themselves casters/receivers in
// the regular shadow loop, gated out by maskPairs). first = top, second = bottom.
// The call site passes canvas.max_blur_radius = 30 (NOT the 29.99 signature
// default), so widths are 15/30 and alphas 150/75 — the same table as the regular
// faded loop. No separate unclipped solid-core pass for masks (unlike strands);
// only the clipped faded strokes plus a clipped inner-core fill.
function drawMaskShadow(ms, first, second, fw, fsw, sw, ssw, P, enableThird, S) {
  const firstPath = strandFootprintAtWidth(first, P, enableThird, S, fw + 2 * fsw);
  const secondPath = strandFootprintAtWidth(second, P, enableThird, S, sw + 2 * ssw);
  if (!firstPath || !secondPath) {
    firstPath && firstPath.remove();
    secondPath && secondPath.remove();
    return;
  }
  // shading_path = (second_path ∩ first_path) minus deletion rects.
  let shading = secondPath.intersect(firstPath);
  shading = subtractDeletions(shading, ms, P, S);

  const items = [];
  if (shading && shading.area && Math.abs(shading.area) > 0.5) {
    for (const st of shadowBlurSteps()) {
      const item = shading.clone();
      item.fillColor = null;
      item.strokeColor = new paper.Color(SHADOW_COLOR.r / 255, SHADOW_COLOR.g / 255, SHADOW_COLOR.b / 255, st.alpha / 255);
      item.strokeWidth = st.width * S;
      item.strokeCap = 'butt';   // Qt FlatCap
      item.strokeJoin = 'round'; // Qt RoundJoin
      items.push(item);
    }
  }
  // inner-core = stroke(first centerline, fw+2fsw) ∩ second_path, filled SOLID at
  // full alpha 150. (Same stroke width as firstPath here, so == firstPath ∩ second.)
  const innerStroke = strandFootprintAtWidth(first, P, enableThird, S, fw + 2 * fsw);
  if (innerStroke) {
    let core = innerStroke.intersect(secondPath);
    core = subtractDeletions(core, ms, P, S);
    if (core && core.area && Math.abs(core.area) > 0.5) {
      core.fillColor = SHADOW_PAINT;
      core.strokeColor = null;
      items.push(core);
    } else {
      core && core.remove();
    }
    innerStroke.remove();
  }
  // All shadow items clipped to second_path (the receiving strand's body).
  if (items.length) {
    new paper.Group({ children: [secondPath.clone(), ...items], clipped: true });
  }
  shading && shading.remove();
  firstPath.remove();
  secondPath.remove();
}

// Faithful port of masked_strand.py. The crossing of the top strand (`first`)
// over the bottom (`second`) is painted as TWO regions filled directly:
//   stroke-color layer = stroked(first, w+2sw) ∩ stroked(second, w+2sw)
//   fill-color  layer  = stroked(first, w)     ∩ stroked(second, w+2sw+4)
// each unioned with the components' visible start circles, minus deletions.
function drawMasked(ms, byLayer, P, enableThird, S, shadowOnly) {
  // A hidden mask draws nothing (Qt MaskedStrand.draw early-returns on is_hidden,
  // masked_strand.py:465 — only a dashed edit-mode outline, absent in the offscreen
  // reference). So neither its masked body nor its own crossing shadow is painted.
  if (ms.is_hidden === true) return;
  const parts = (ms.layer_name || '').split('_');
  if (parts.length < 4) return;
  const first = byLayer[parts[0] + '_' + parts[1]];
  const second = byLayer[parts[2] + '_' + parts[3]];
  if (!first || !second) return;
  const fw = first.width || 0, fsw = first.stroke_width || 0;
  const sw = second.width || 0, ssw = second.stroke_width || 0;

  // Crossing shadow (only when shadows are on). Faithful port of
  // draw_mask_strand_shadow (PORT-FOR-COMPLETENESS — no mask fixture exercises
  // this at the pixel level, so it is UNMEASURED). first = top, second = bottom:
  //   first_path  = first body @ (fw+2fsw)   (NO blur inflation)
  //   second_path = second body @ (sw+2ssw)
  //   shading_path = (second_path ∩ first_path) minus deletion rects
  //   clipped to second_path, run NUM_STEPS faded boundary strokes over
  //     shading_path (15/30 widths, 150/75 alphas, FlatCap/RoundJoin); then
  //   inner-core = stroke(first center, fw+2fsw) ∩ second_path filled SOLID at
  //     alpha 150 (no separate unclipped solid-core pass for masks).
  // hide_shadow also suppresses the mask's own crossing shadow (OSS
  // masked_strand.py:516,665 gate draw_mask_strand_shadow on it).
  if (SHADOW_ENABLED && ms.hide_shadow !== true) {
    drawMaskShadow(ms, first, second, fw, fsw, sw, ssw, P, enableThird, S);
  }

  // shadow_only mask: it has cast its shadows (regular cast in the main loop +
  // the crossing shadow above) but paints no visible body (OSS masked_strand.py
  // skips all body rendering and returns early when self.shadow_only).
  if (shadowOnly) return;

  // stroke-color region: first@(w+2sw) ∩ second@(w+2sw)
  // Component outlines come from the per-render memo: a strand that is a
  // component of several masks is stroked once per width instead of once per
  // mask, and the fill-region widths below are exactly the two the selection
  // highlight's buildMaskPath asks for, so it reuses them for free.
  const comp = (t, wpx) => cachedGeom(`mcomp|${t.layer_name}|${wpx}`,
    () => maskComponentPath(t, P, enableThird, S, wpx));
  const fStroke = comp(first, fw + 2 * fsw);
  const sStroke = comp(second, sw + 2 * ssw);
  let strokeRegion = fStroke && sStroke ? fStroke.intersect(sStroke) : null;
  fStroke && fStroke.remove();
  sStroke && sStroke.remove();
  strokeRegion = subtractDeletions(strokeRegion, ms, P, S);

  // fill-color region: first@w ∩ second@(w+2sw+4)
  const fFill = comp(first, fw);
  const sExt = comp(second, sw + 2 * ssw + 4);
  let fillRegion = fFill && sExt ? fFill.intersect(sExt) : null;
  fFill && fFill.remove();
  sExt && sExt.remove();
  fillRegion = subtractDeletions(fillRegion, ms, P, S);

  if (strokeRegion) { strokeRegion.fillColor = toColor(first.stroke_color); strokeRegion.strokeColor = null; }
  if (fillRegion) { fillRegion.fillColor = toColor(first.color); fillRegion.strokeColor = null; }
  // Paint order: stroke layer under fill layer.
  const layers = [strokeRegion, fillRegion].filter(Boolean);
  if (layers.length) new paper.Group(layers);

  // Selection highlight (OSS MaskedStrand). Clicking a masked layer reddens it on
  // the canvas: stroke the mask intersection silhouette — get_mask_path() = the FILL
  // region (buildMaskPath) — ON TOP of the body with a semi-transparent red outline.
  // Faithful to draw_highlight (masked_strand.py:1187-1215): width 6px, RoundCap/
  // RoundJoin, NoBrush (fill null), color = highlight_color with alpha forced to 128
  // (rgba(255,0,0,128)). That is the default-zoom click highlight routed via
  // draw_highlighted_masked_strand; the 2px variant at masked_strand.py:763-775 is
  // only the zoomed/panned _draw_direct fallback. NOTE the intentional asymmetry vs
  // drawStrand — regular strands draw the halo UNDER the body, but a mask strokes its
  // outline OVER the body (OSS draws the mask body then draw_highlight last). Gated on
  // ms.is_selected so oracle fixtures (which never set it) are unaffected. buildMaskPath
  // returns null when the components don't intersect (area<=0.5), so guard before use;
  // the returned path is LEFT on the canvas to be painted (not removed).
  if (ms.is_selected) {
    const hl = buildMaskPath(ms, byLayer, P, enableThird, S);
    if (hl) {
      hl.fillColor = null;
      hl.strokeColor = toColor({ r: HIGHLIGHT_COLOR.r, g: HIGHLIGHT_COLOR.g, b: HIGHLIGHT_COLOR.b, a: 128 });
      hl.strokeWidth = 6 * S;
      hl.strokeCap = 'round';
      hl.strokeJoin = 'round';
    }
  }
}

// Widget background + grid, in VIEWPORT space (no pan transform). Mirrors the
// order and the coordinate space OSS paints them in: _paintEventInner fills the
// widget and calls draw_grid inside the painter transform but derives the lines
// from the VISIBLE rect, so both track the current offset rather than the content.
// strokeWidth ss => 1px after the ss downscale. LIVE EDITOR ONLY: computeGridLines
// returns null when meta.show_grid is unset (the oracle never sets it).
function paintBackdrop(meta, W, H, ss, S, ox, oy) {
  // canvas_bg 'transparent' (PNG export only): paint NO backdrop, so the frame
  // keeps the clear offscreen it started on, the way OSS save_canvas_as_image
  // fills its QImage with Qt.transparent before painting (main_window.py).
  if (meta.canvas_bg !== 'transparent') {
    const bg = new paper.Path.Rectangle(new paper.Point(0, 0), new paper.Size(W * ss, H * ss));
    bg.fillColor = meta.canvas_bg || 'white'; // themed live editor (OSS dark #2C2C2C); oracle leaves it white
  }
  const grid = computeGridLines(meta, S, ox * ss, oy * ss, W * ss, H * ss);
  if (!grid) return;
  const gridColor = meta.grid_color || toColor({ r: 0, g: 0, b: 0, a: 20 }); // OSS #C8C8C8/#B4B4B4; legacy faint fallback
  // Line width in OUTPUT px (before the ss downscale). Absent => 1px, the live
  // editor's grid. The PNG export passes OSS's pen width under its painter scale.
  const gridWidth = (meta.grid_line_width || 1) * ss;
  for (const x of grid.xs) {
    const ln = new paper.Path.Line(new paper.Point(x, 0), new paper.Point(x, H * ss));
    ln.strokeColor = gridColor; ln.strokeWidth = gridWidth;
  }
  for (const y of grid.ys) {
    const ln = new paper.Path.Line(new paper.Point(0, y), new paper.Point(W * ss, y));
    ln.strokeColor = gridColor; ln.strokeWidth = gridWidth;
  }
}

// Copy the ss-supersampled offscreen `hi` down into the visible canvas. Shared by
// renderFixture and renderPanFrame so a pan frame is composited by exactly the
// same code as the render it stands in for.
function compositeTo(vis, hi, W, H, ss, meta) {
  vis.width = W;
  vis.height = H;
  vis.style.width = W + 'px';
  vis.style.height = H + 'px';
  const ctx = vis.getContext('2d');
  if (ss === 1) {
    ctx.drawImage(hi, 0, 0);
    return;
  }
  if (meta.fast_downscale) {
    // LIVE EDITOR ONLY (gated on meta.fast_downscale, which the offline oracle /
    // fidelity harness never sets). Downscale the ss× supersampled offscreen with
    // the browser's native high-quality filter — a GPU blit — instead of the exact
    // JS box-average below (a W*ss × H*ss triple loop, ~200ms even for a single
    // strand on a 1400×680 canvas). Still fully supersampled, so resting quality is
    // ~indistinguishable; only the offline path keeps the exact Qt-matching box
    // average for byte-identity.
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(hi, 0, 0, W * ss, H * ss, 0, 0, W, H);
    return;
  }
  // Match the Qt reference, which downsamples the ss× image with
  // QImage.scaled(..., Qt.SmoothTransformation). For an exact integer ss downscale
  // that is an ss×ss box average in sRGB space. Reproduce it exactly here instead
  // of relying on the browser's imageSmoothing filter (a wider, engine-specific
  // kernel that leaves a ~1px seam on high-contrast curved edges versus Qt's
  // average). The composited image is fully opaque (white background), so a
  // straight per-channel average needs no alpha handling.
  const src = hi.getContext('2d').getImageData(0, 0, W * ss, H * ss).data;
  const out = ctx.createImageData(W, H);
  const od = out.data;
  const rowSpan = W * ss;
  const inv = 1 / (ss * ss);
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      let r = 0, g = 0, b = 0, a = 0;
      for (let dy = 0; dy < ss; dy++) {
        let si = ((y * ss + dy) * rowSpan + x * ss) * 4;
        for (let dx = 0; dx < ss; dx++) {
          r += src[si]; g += src[si + 1]; b += src[si + 2]; a += src[si + 3];
          si += 4;
        }
      }
      const oi = (y * W + x) * 4;
      od[oi] = r * inv;
      od[oi + 1] = g * inv;
      od[oi + 2] = b * inv;
      od[oi + 3] = a * inv;
    }
  }
  ctx.putImageData(out, 0, 0);
}

// Render `strands` (flat array) using `meta` into the canvas #c.
// `target` (optional, LIVE EDITOR ONLY) composites the frame into that canvas
// instead of #c and retains nothing: the Stylize End Side dialog paints its
// preview picture and shape icons through the very same code the canvas uses
// (end_style_dialog.py _paint_preview / _shape_icon), without disturbing the
// scene the last on-screen render left behind. The offline oracle never passes it.
window.renderFixture = function (strands, meta, target) {
  CURVE = meta.curve_params || CURVE_DEFAULT;
  SAMPLE_STEP = 1; // full-accuracy sampling for the oracle / pointer-up render
  const W = meta.image_width, H = meta.image_height;
  // Match the reference, which renders at `supersample`x then downscales.
  // Paper draws into an offscreen W*ss x H*ss canvas; we then downscale into
  // the visible 1x canvas with high-quality smoothing and screenshot that.
  // (Playwright's canvas screenshot captures the backing store, not the CSS
  // box, so an in-page downscale is the reliable way to supersample.)
  const ss = meta.supersample || 2;
  // Zoom is additive: when absent it is 1 and S === ss, so every length below is
  // identical to the pre-zoom renderer (fixtures stay pixel-identical). `S` is
  // the full content scale (supersample * zoom) applied to positions AND widths;
  // the content offset stays at `ss` so panning isn't scaled by zoom.
  const zoom = meta.zoom || 1;
  const S = ss * zoom;

  const ox = meta.x_offset, oy = meta.y_offset;

  // A render replaces whatever scene was retained (see PAN_SCENE): each one owns a
  // paper project and an offscreen canvas, and exactly one is ever live. A
  // preview render into `target` leaves the retained scene alone.
  if (!target) dropScene();

  const hi = document.createElement('canvas');
  // Opt out of paper.js's automatic devicePixelRatio scaling: this renderer does
  // its own supersampling via the W*ss offscreen canvas + manual downscale, so
  // paper must treat 1 canvas px as 1 unit. Without this, a browser at DPR != 1
  // (display zoom/scaling) double-scales and the drawing lands at the wrong size.
  // Harness-safe: the Playwright reference runs at DPR=1, where pixelRatio is 1
  // either way.
  hi.setAttribute('hidpi', 'off');
  hi.width = W * ss;
  hi.height = H * ss;
  paper.setup(hi);

  // BACKDROP layer — VIEWPORT space, no pan transform. Qt fills the widget itself
  // and derives the grid from the VISIBLE rect (draw_grid,
  // strand_drawing_canvas.py), so neither rides the pan; both are rebuilt for the
  // current offset. Painted first so it composites under the bodies.
  const backdrop = paper.project.activeLayer;
  paintBackdrop(meta, W, H, ss, S, ox, oy);

  // CONTENT layer — the strands, with the pan carried by this layer's MATRIX
  // rather than rebuilt into the geometry. This is OSS's arrangement:
  // _paintEventInner sets up the painter with
  // `painter.translate(self.pan_offset_x, self.pan_offset_y)` and then builds every
  // path in plain canvas coordinates, so a pan moves one transform and invalidates
  // no geometry. renderPanFrame is what cashes that in.
  //
  // The layer is ANCHORED at this render's offset: geometry is built at the offset
  // below (so the matrix starts out identity) and the matrix later carries the
  // DELTA from it. Anchoring rather than building at a bare pt*S is deliberate.
  // paper.js's boolean ops (resolveCrossings/unite) use ABSOLUTE epsilons, so their
  // output is sensitive to coordinate magnitude — this renderer has a known
  // coordinate-dependent degeneracy where a body comes out as a solid black band,
  // and building at raw world*S walks three_strand_braid straight into it. Keeping
  // the build coordinates exactly where they have always been makes every full
  // render bit-identical to before this change, and costs the pan nothing: what a
  // reused scene requires is that the geometry not depend on the CURRENT pan, and
  // an anchor fixed for the scene's lifetime satisfies that just as well as zero.
  const content = new paper.Layer();
  content.applyMatrix = false;   // keep it a transform; don't bake it into children
  content.activate();

  // world -> content space, anchored at this scene's offset. Unchanged from the
  // pre-refactor P: at the anchor the layer matrix is identity, so the coordinates
  // that reach the rasterizer are the same doubles as before.
  const P = (pt) => new paper.Point(pt.x * S + ox * ss, pt.y * S + oy * ss);
  const enableThird = resolveEnableThird(strands, meta);
  BIAS_ENABLED = !!(meta && meta.enable_curvature_bias_control);
  applyPaintSettings(meta);
  // Memoize per-strand shadow geometry for the duration of THIS render (see the
  // geometry memo near the top). Scoped to the paper project set up above and
  // closed before the frame is composited.
  geomCacheBegin();

  const byLayer = {};
  for (const s of strands) byLayer[s.layer_name] = s;

  // Honor the canonical layer_order from the Qt reference so the j<i z-order
  // semantics match OSS. Guard with every()+rank.has so a partial/missing order
  // falls back to the incoming array order. Sort a slice() copy so the caller's
  // array is not mutated; byLayer is keyed by layer_name and stays valid.
  if (Array.isArray(meta.layer_order) && meta.layer_order.length) {
    const rank = new Map(meta.layer_order.map((name, idx) => [name, idx]));
    if (strands.every((s) => rank.has(s.layer_name))) {
      strands = strands.slice().sort((a, b) => rank.get(a.layer_name) - rank.get(b.layer_name));
    }
  }

  // Replace each strand's stored has_circles with the render-time value OSS
  // computes on load (from actual attachments + manual overrides). Drives both
  // the end caps and the flat-end side lines.
  for (const s of strands) {
    if (s.type === 'MaskedStrand') continue;
    s.has_circles = computeHasCircles(s, strands);
  }

  const shadowEnabled = !!meta.shadow_enabled;
  SHADOW_ENABLED = shadowEnabled;
  SHADOW_PAINT = toColor(SHADOW_COLOR);
  // Stash the per-pair override dict module-scoped so castStrandShadow can read
  // it in the Port phase without threading a new param. Inert until that phase.
  SHADOW_OVERRIDES = meta.shadow_overrides || {};

  // Pairs that are the two components of a mask don't shadow each other (the
  // mask owns that crossing).
  const maskPairs = new Set();
  for (const s of strands) {
    if (s.type !== 'MaskedStrand') continue;
    const p = (s.layer_name || '').split('_');
    if (p.length >= 4) {
      maskPairs.add(p[0] + '_' + p[1] + '|' + p[2] + '_' + p[3]);
      maskPairs.add(p[2] + '_' + p[3] + '|' + p[0] + '_' + p[1]);
    }
  }

  // Draw in list order (≈ Qt paint loop): for each strand, first cast its
  // faithful two-pass shadow onto already-drawn lower strands (SOLID CORE +
  // clipped FADED BLUR, see castStrandShadow), then paint its body. Drawing the
  // body after the cast means it covers its own inner shadow, leaving only the
  // fringe over lower strands. Masked strands repaint the top strand over the
  // bottom (and own their own crossing shadow).
  for (let i = 0; i < strands.length; i++) {
    const s = strands[i];
    // Hidden strands do not cast a shadow (Qt draw_strand_shadow early-returns on
    // is_hidden, shader_utils.py:457) and paint no body (gated below); they stay
    // in the array only so masks/has_circles can still resolve them.
    // hide_shadow (OSS 1.109 per-layer "Hide Shadow", shader_utils.py:466): the
    // strand casts nothing but still receives and paints its body normally.
    const casts = shadowEnabled && s.is_hidden !== true && s.hide_shadow !== true;
    if (s.type === 'MaskedStrand') {
      // A mask FIRST casts its crossing shadow onto lower NON-mask strands (the
      // receiver loop skips MaskedStrand receivers and the mask's own components),
      // THEN draws its body (which owns its own-component crossing shadow).
      if (casts) castStrandShadow(s, strands, byLayer, P, enableThird, S, maskPairs, i);
      // shadow_only mask (OSS masked_strand.py:561-568): still owns its crossing
      // shadow (drawn inside drawMasked) but paints NO body fill/stroke.
      drawMasked(s, byLayer, P, enableThird, S, s.shadow_only === true);
      continue;
    }

    if (casts) castStrandShadow(s, strands, byLayer, P, enableThird, S, maskPairs, i);
    // Hidden strand: no body (Qt strand.py:2279 / :3019 early-return on
    // is_hidden). It stays in the array so masks can still resolve it as a
    // component and has_circles still sees it, exactly like canvas.strands.
    if (s.is_hidden === true) continue;
    // OSS shadow_only: the strand has already cast its shadow above; suppress its
    // own body/extension paint. Absent/false => normal full body (oracle-safe).
    // (Per-pair visibility/full/subtract overrides are handled inside
    // castStrandShadow via SHADOW_OVERRIDES — supersedes the group branch's
    // isShadowPairVisible gate.)
    if (s.shadow_only) continue;
    drawStrand(s, strands, P, enableThird, S);
  }

  // After every body, so the preview reads over the finished drawing.
  drawVisibleShadowPaths(strands, byLayer, P, enableThird, S);

  // Drop the memo (and its detached masters) before the frame is composited, so
  // no entry can outlive this render's paper project.
  geomCacheEnd();

  paper.view.update();
  if (target) {
    compositeTo(target, hi, W, H, ss, meta);
    // A preview owns nothing past this frame: free its project and hand the
    // active slot back to the retained on-screen scene (if any).
    const previewProject = paper.project;
    try { previewProject.remove(); } catch { /* already gone */ }
    if (PAN_SCENE) { try { PAN_SCENE.project.activate(); } catch { /* torn down */ } }
    return;
  }
  compositeTo(document.getElementById('c'), hi, W, H, ss, meta);

  // RETAIN this render's project as the live scene. renderFixture used to remove
  // it here, because a fresh project per render otherwise piles up in
  // paper.projects and every later frame gets slower. That invariant is kept by
  // dropScene() at the top of this function: exactly one project is ever retained,
  // and the next render frees it. What retention buys is that a pan gesture never
  // has to build anything — the resting render already left the scene it needs.
  PAN_SCENE = { project: paper.project, hi, content, backdrop, key: meta.scene_key, W, H, ss, S, zoom, ox, oy };

  return { drawn: strands.length, width: W, height: H, supersample: ss };
};

// ---- interactive drag fast-path (EDITOR ONLY; the headless harness never calls
// these — it only uses renderFixture/extractStrands) ---------------------------
// Dragging an endpoint re-renders every frame, and re-stroking ALL strands through
// Paper each frame is ~O(n) heavy boolean ops (hundreds of ms for busy scenes — see
// tools/bench_drag.mjs). The original OpenStrand Studio avoids this by drawing ONLY
// the moving strand over a cached "background" of everything else (move_mode.py's
// optimized paint handler, painting at native resolution with shadows effectively
// dropped). We mirror that: bake the static strands once into DRAG_BG, then per
// move draw only the moving strands on top — at supersample 1 (so no box-average
// downscale) and with shadows off. Full quality + shadows return via a normal
// renderFixture on pointer-up.
// bands: ordered z-segments separating the static scene around the moving set.
// Each entry is either { kind:'band', canvas } (a pre-baked maximal run of
// consecutive static strands) or { kind:'move' } (a placeholder where the moving
// strands are stroked live each frame). Walking `bands` in order and blitting /
// stroking reproduces the document's true z-order, so a static strand above the
// moving one still occludes it (mirrors move_mode.py's original_strands_order
// redraw, but with the static runs cached so per-frame cost stays O(moving)).
let DRAG_BG = null; // { bands, W, H, ox, oy, zoom, topo, under }
// Scratch bitmap the moving strands are stroked into each frame, reused across
// frames and across gestures (see renderDragFrame), together with the paper
// Project bound to it. paper.setup() is not cheap: it measures the canvas via
// getBoundingClientRect (a forced style+layout flush), installs the whole
// pointer/touch listener set and writes several vendor-prefixed style
// properties. Doing that once per gesture instead of once per pointer move
// takes a guaranteed reflow out of every drag frame.
let DRAG_MV = null;
let DRAG_MV_PROJECT = null;

// Gesture-invariant topology shared by every frame of a drag. has_circles is the
// attachment structure (which endpoints carry caps / flat-end side lines); it is
// position-INDEPENDENT and so identical on every frame of an endpoint/CP drag
// (welded children move rigidly with their parent endpoint, so the attachment a
// child registers at its parent's endpoint never changes within the gesture).
// byLayer / enableThird are likewise topology, not position. Computing them ONCE
// at bake — instead of re-running the O(N^2) computeHasCircles pass every frame —
// is the per-frame win. Returns { hasCircles: Map<layer_name,[bool,bool]>,
// byLayer, enableThird }; has_circles is stored in the Map, NOT mutated onto s,
// so the bake/frame callers apply it only to the strands they actually draw.
function computeDragTopology(strands, meta) {
  const enableThird = resolveEnableThird(strands, meta);
  BIAS_ENABLED = !!(meta && meta.enable_curvature_bias_control);
  applyPaintSettings(meta);
  const byLayer = {};
  for (const s of strands) byLayer[s.layer_name] = s;
  const hasCircles = new Map();
  for (const s of strands) {
    if (s.type === 'MaskedStrand') continue;
    hasCircles.set(s.layer_name, computeHasCircles(s, strands));
  }
  return { hasCircles, byLayer, enableThird };
}

// Paint the strands for which shouldDraw(layer_name) is true into targetCanvas at
// native (supersample-1) scale, no shadows. Shared by the bake and per-frame paths.
// `topo` (from computeDragTopology) carries the gesture-invariant has_circles /
// byLayer / enableThird so the per-frame path skips the O(N^2) topology pass; when
// absent (defensive fallback) the per-frame topology is recomputed here so the
// function stays self-contained. Leaves the Paper project active for the caller to
// read / composite, then remove.
function _dragPaint(targetCanvas, strands, meta, shouldDraw, whiteBg, topo, persistent) {
  CURVE = meta.curve_params || CURVE_DEFAULT;
  SAMPLE_STEP = DRAG_SAMPLE_STEP; // coarse sampling keeps per-frame stroking cheap

  const W = meta.image_width, H = meta.image_height;
  const S = meta.zoom || 1; // supersample fixed at 1 on the drag path
  targetCanvas.setAttribute('hidpi', 'off');
  // Assigning canvas.width/height reallocates the backing store and clears it —
  // several megabytes of churn per drag frame on a full-window canvas. Only pay
  // it when the size actually changed; paper's view.update() clears the canvas
  // before it draws, so a same-size reuse still starts from a blank surface.
  const resized = targetCanvas.width !== W || targetCanvas.height !== H;
  if (resized) {
    targetCanvas.width = W;
    targetCanvas.height = H;
  }
  if (persistent && DRAG_MV_PROJECT && !resized) {
    // Reuse this gesture's project: activate it (every `new paper.Path` targets
    // the globally active project, so this must precede all drawing) and empty
    // last frame's contents. Removing the children marks the view dirty, so the
    // view.update() at the end still repaints.
    DRAG_MV_PROJECT.activate();
    DRAG_MV_PROJECT.activeLayer.removeChildren();
  } else {
    if (persistent && DRAG_MV_PROJECT) { DRAG_MV_PROJECT.remove(); DRAG_MV_PROJECT = null; }
    paper.setup(targetCanvas);
    if (persistent) DRAG_MV_PROJECT = paper.project;
  }
  if (whiteBg) {
    const bg = new paper.Path.Rectangle(new paper.Point(0, 0), new paper.Size(W, H));
    bg.fillColor = meta.canvas_bg || 'white'; // themed backdrop under drag bands (live editor); oracle unused
  }
  const ox = meta.x_offset, oy = meta.y_offset;
  // Matches renderFixture's P at ss=1: P(pt) = pt*S + offset.
  const P = (pt) => new paper.Point(pt.x * S + ox, pt.y * S + oy);
  if (!topo) topo = computeDragTopology(strands, meta); // defensive self-contained fallback
  const { hasCircles, enableThird } = topo;
  // byLayer is a GEOMETRY lookup, not topology, so it must be rebuilt from THIS
  // frame's array. Taking it from the bake (as hasCircles/enableThird correctly do)
  // froze every mask at its pointer-down shape: drawMasked resolves a mask's two
  // components through byLayer, and the store hands the renderer freshly cloned
  // strand objects each frame, so a mask whose component was being dragged kept
  // rendering the intersection computed from pre-drag positions until pointer-up.
  const byLayer = {};
  for (const s of strands) byLayer[s.layer_name] = s;
  BIAS_ENABLED = !!(meta && meta.enable_curvature_bias_control);
  applyPaintSettings(meta);
  SHADOW_ENABLED = false; // no shadows while dragging (restored by renderFixture on release)
  // Memoize component outlines for this paint — but only when something can
  // actually ask for the same outline twice, which on the drag path means a mask
  // (its fill and stroke regions share component outlines, and a selected mask's
  // highlight asks for the fill region again). A band of plain strands is all
  // cold misses, and on a miss the memo costs an extra detach + clone per
  // outline for nothing: measured ~10% on the pointer-down bake of a mask-free
  // document. With no mask in the drawn set the builders fall through to exactly
  // the un-memoized path.
  let memo = false;
  for (let i = 0; i < strands.length; i++) {
    const s = strands[i];
    if (s.type === 'MaskedStrand' && s.is_hidden !== true && shouldDraw(s.layer_name)) { memo = true; break; }
  }
  if (memo) geomCacheBegin();
  for (let i = 0; i < strands.length; i++) {
    const s = strands[i];
    if (!shouldDraw(s.layer_name)) continue;
    if (s.is_hidden === true) continue; // same paint gate as renderFixture
    if (s.type === 'MaskedStrand') { drawMasked(s, byLayer, P, enableThird, S); continue; }
    // Apply the cached topology to the strand we are about to draw (the Map holds
    // every non-masked strand's value, computed once per gesture at bake).
    const hc = hasCircles.get(s.layer_name);
    if (hc) s.has_circles = hc;
    drawStrand(s, strands, P, enableThird, S);
  }
  geomCacheEnd();   // no-op when the memo was never opened; masters die with this paint's project
  paper.view.update();
}

// Bake the STATIC strands into per-band offscreen bitmaps, split by the moving
// set so true z-order is preserved during the gesture. Call once at the start of
// a drag. The strands array is already z-ordered (doc order); we walk it and let
// any moving-set layer act as a SEPARATOR. Each maximal run of consecutive static
// strands becomes its own band bitmap; the moving set's z-slot becomes a 'move'
// placeholder stroked live each frame. In the common case (moving set contiguous)
// this yields BELOW band, move, ABOVE band. Computes the gesture-invariant
// topology ONCE here and stashes it (with the bands) on DRAG_BG so every
// renderDragFrame reuses it instead of recomputing.
window.renderDragBackground = function (strands, meta) {
  const W = meta.image_width, H = meta.image_height;
  const moving = new Set((meta.drag && meta.drag.moving) || []);
  const topo = computeDragTopology(strands, meta);
  // Partition strands into ordered segments: maximal runs of static strands
  // alternating with the moving-set slots. A MaskedStrand whose components move is
  // already in the moving set (movingStrandSet), so testing layer membership is
  // enough to keep masks that straddle a boundary out of a static band.
  const bands = [];
  let run = null; // current static layer-name run, or null
  let inMove = false; // last separator slot already recorded as 'move'?
  for (let i = 0; i < strands.length; i++) {
    const name = strands[i].layer_name;
    if (moving.has(name)) {
      if (run) { bands.push({ kind: 'band', names: run }); run = null; }
      // Collapse a contiguous cluster of moving strands into a single 'move' slot.
      if (!inMove) { bands.push({ kind: 'move' }); inMove = true; }
    } else {
      if (!run) run = new Set();
      run.add(name);
      inMove = false;
    }
  }
  if (run) bands.push({ kind: 'band', names: run });
  // "Draw only affected strand when dragging" (OSS Settings -> General; move_mode.py
  // :668-671 "do NOT draw any strands in the background cache"). Every static band
  // is dropped, leaving the 'move' slot as the only thing renderDragFrame
  // composites over the backdrop, so a drag shows the moved strand alone. Absent
  // from meta => false => every band is baked, which is the existing behaviour.
  const onlyAffected = !!(meta && meta.draw_only_affected_strand);
  // Bake each static run into its own TRANSPARENT bitmap. The white backdrop is
  // painted once on the visible canvas in renderDragFrame (not baked into any
  // band) so the bands composite cleanly in any order regardless of which one is
  // first — including the case where the moving set is at the very bottom and no
  // BELOW band exists.
  for (const b of bands) {
    if (b.kind !== 'band') continue;
    if (onlyAffected) { b.canvas = null; delete b.names; continue; }
    const c = document.createElement('canvas');
    _dragPaint(c, strands, meta, (name) => b.names.has(name), false, topo);
    paper.project.remove();
    b.canvas = c;
    delete b.names; // names only needed during bake
  }
  DRAG_BG = {
    bands, W, H, ox: meta.x_offset, oy: meta.y_offset, zoom: meta.zoom || 1, topo,
    under: null,   // backdrop + grid bitmap, built lazily on the first frame
  };
  return { baked: true, staticCount: strands.length - moving.size, bands: bands.length };
};

// Per-move frame: composite the pre-baked static bands and the live moving
// strokes in TRUE z-order, so a static strand above the moving one still occludes
// it. Falls back to a full renderFixture if no matching bake exists (e.g. the view
// changed mid-gesture). Reuses DRAG_BG.topo (baked once at gesture start) so the
// per-frame cost is O(moving) + k band blits, not O(all strands).
// The backdrop and grid for the current gesture, painted once and cached on
// DRAG_BG. Deliberately reproduces the old per-frame code EXACTLY, including one
// stroke() per grid line: the grid colour can be translucent, so every crossing
// is composited twice and comes out darker. Folding the lines into a single path
// would composite each crossing once and visibly lighten them — the same picture
// only if you never look at an intersection.
function dragUnderlay(meta, W, H) {
  if (DRAG_BG.under) return DRAG_BG.under;
  const c = document.createElement('canvas');
  c.width = W;
  c.height = H;
  const ctx = c.getContext('2d');
  ctx.fillStyle = meta.canvas_bg || 'white'; // themed backdrop (live editor); oracle leaves it white
  ctx.fillRect(0, 0, W, H);
  // ss is fixed at 1 on the drag path, so scale == zoom and the offsets are the
  // raw meta pan. LIVE EDITOR ONLY (computeGridLines null-guards on show_grid).
  const grid = computeGridLines(meta, meta.zoom || 1, meta.x_offset, meta.y_offset, W, H);
  if (grid) {
    ctx.save();
    ctx.strokeStyle = meta.grid_color || 'rgba(0,0,0,0.08)'; // OSS grid color; legacy faint fallback
    ctx.lineWidth = 1;
    for (const x of grid.xs) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke(); }
    for (const y of grid.ys) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke(); }
    ctx.restore();
  }
  DRAG_BG.under = c;
  return c;
}

window.renderDragFrame = function (strands, meta) {
  const W = meta.image_width, H = meta.image_height;
  if (!DRAG_BG || DRAG_BG.W !== W || DRAG_BG.H !== H ||
      DRAG_BG.ox !== meta.x_offset || DRAG_BG.oy !== meta.y_offset ||
      DRAG_BG.zoom !== (meta.zoom || 1)) {
    return window.renderFixture(strands, meta);
  }
  const moving = new Set((meta.drag && meta.drag.moving) || []);
  // Stroke the moving strands once into a transparent offscreen bitmap; it gets
  // blitted at every 'move' slot in the band order (normally exactly one slot).
  // The bitmap is reused across frames: a fresh <canvas> per pointermove meant a
  // multi-megabyte allocation (and eventual GC) on every frame of every drag.
  // _dragPaint resizes it only when the size changes and paper clears it before
  // drawing, so each frame still starts from a fully transparent surface.
  if (!DRAG_MV) DRAG_MV = document.createElement('canvas');
  const mv = DRAG_MV;
  _dragPaint(mv, strands, meta, (name) => moving.has(name), false, DRAG_BG.topo, true);
  // The project stays alive for the rest of the gesture; endDrag() removes it.
  const vis = document.getElementById('c');
  // Same story for the visible canvas: writing .width reallocates and clears it.
  // Only touch it on a real size change; the underlay blit below repaints every pixel.
  if (vis.width !== W) vis.width = W;
  if (vis.height !== H) vis.height = H;
  const wpx = W + 'px', hpx = H + 'px';
  if (vis.style.width !== wpx) vis.style.width = wpx;
  if (vis.style.height !== hpx) vis.style.height = hpx;
  const ctx = vis.getContext('2d');
  // Backdrop + grid are identical on every frame of a gesture (the bake key
  // covers size, pan and zoom), so they are baked ONCE into DRAG_BG.under and
  // blitted here. They used to be repainted per frame: a full-canvas clear, a
  // full-canvas fill, and one beginPath/stroke per grid line — on a 1400x900
  // canvas with a 28px grid that is ~80 separate rasterizer submissions every
  // pointer move, all producing the same pixels.
  ctx.drawImage(dragUnderlay(meta, W, H), 0, 0);
  // Composite bands bottom-to-top in document z-order, dropping in the moving
  // strokes at their z-slot. Per-frame work = k band blits + the one mv blit.
  for (const b of DRAG_BG.bands) {
    if (b.kind === 'move') ctx.drawImage(mv, 0, 0);
    else if (b.canvas) ctx.drawImage(b.canvas, 0, 0);  // null when draw_only_affected_strand suppressed the bake
  }
  return { drawn: moving.size, mode: 'dragframe', bands: DRAG_BG.bands.length };
};

// Drop the cached background at the end of a gesture (or before any full render).
window.endDrag = function () {
  DRAG_BG = null;
  if (DRAG_MV_PROJECT) { DRAG_MV_PROJECT.remove(); DRAG_MV_PROJECT = null; }
};

// ---- pan: OSS's painter transform, not a rebuild ------------------------------
// OSS does no work at all to pan. strand_drawing_canvas.mouseMoveEvent (4430) sets
// pan_offset_x/y and calls update(); _paintEventInner then does a FULL repaint with
// `painter.translate(self.pan_offset_x, self.pan_offset_y)` in front of it. That is
// affordable there because a Qt repaint is cheap — every strand body is
// QPainterPathStroker.createStroke() plus drawPath() with WindingFill, i.e. native
// C++ with no boolean algebra anywhere.
//
// Ours is not cheap: ~95% of a render is paper.js resolveCrossings/unite/intersect
// (measured 364ms + 294ms of a 702ms render on three_strand_braid). So we take the
// half of OSS's design that matters — the pan is a TRANSFORM, not an input to the
// geometry — and keep the geometry across frames. renderFixture leaves its content
// layer anchored at the offset it was built for; renderPanFrame serves any later
// offset by putting the delta on that layer's matrix and re-rasterizing. There is
// no snapshot to retake, no margin to run out of, and no full-quality repaint owed
// on pointer-up.
//
// WHAT A PAN FRAME IS, EXACTLY. It is the anchor render TRANSLATED by the delta —
// tools/pan_fidelity.mjs asserts that per fixture and per delta, including that the
// residual is uniquely minimal at the claimed delta. It is NOT bit-identical to a
// fresh renderFixture at the panned offset, and cannot be: renderFixture is not
// offset-invariant (paper.js boolean ops use absolute epsilons, and at some offsets
// they hit the renderer's known body degeneracy). Between the two, the pan frame is
// the stable side — one build serves the whole gesture instead of every frame
// rolling the dice at a new offset.
//
// The delta the caller sends is still rounded to whole pixels, but that is OSS
// parity (Qt hands it integer QPoint deltas, strand_drawing_canvas.py:4430), not
// something this path needs: a fractional delta is served here just as exactly.
//
// The retained scene lives in PAN_SCENE, tagged with the caller's `scene_key`:
// every renderFixture input EXCEPT the pan offset. A key mismatch means the scene
// is for a different document/view, and the caller must render instead.
let PAN_SCENE = null; // { project, hi, content, backdrop, key, W, H, ss, S, zoom, ox, oy }

function dropScene() {
  if (!PAN_SCENE) return;
  const sc = PAN_SCENE;
  PAN_SCENE = null;   // clear first: a remove() that throws must not leave it live
  try { sc.project.remove(); } catch { /* project already torn down */ }
}

// One pan frame. Returns null when the retained scene cannot serve this meta — the
// caller must then do a full render, which retains a scene the next frame can use.
window.renderPanFrame = function (meta) {
  const sc = PAN_SCENE;
  if (!sc) return null;
  const W = meta.image_width, H = meta.image_height;
  const ss = meta.supersample || 2;
  // The key covers everything but the offset; W/H/ss/zoom are re-checked because
  // they size the offscreen and scale the content, and a caller that forgot to fold
  // them into its key would otherwise get a silently wrong frame.
  if (sc.key == null || sc.key !== meta.scene_key) return null;
  if (sc.W !== W || sc.H !== H || sc.ss !== ss || sc.zoom !== (meta.zoom || 1)) return null;

  sc.project.activate();   // every paper construction below targets the active project
  // The pan itself: one matrix, exactly OSS's painter.translate(pan_offset). The
  // scene's geometry sits at the offset it was built at (sc.ox/sc.oy), so what the
  // matrix carries is the delta from there.
  sc.content.matrix = new paper.Matrix(
    1, 0, 0, 1, (meta.x_offset - sc.ox) * ss, (meta.y_offset - sc.oy) * ss);
  // Background + grid are viewport-space (see paintBackdrop), so they are the one
  // thing a pan does rebuild. It is a handful of straight lines — no geometry.
  sc.backdrop.activate();
  sc.backdrop.removeChildren();
  paintBackdrop(meta, W, H, ss, sc.S, meta.x_offset, meta.y_offset);

  sc.project.view.update();
  compositeTo(document.getElementById('c'), sc.hi, W, H, ss, meta);
  return { mode: 'panframe' };
};

// Free the retained scene. Nothing requires this for correctness — the scene is
// keyed, so a stale one can never be served — but a caller that knows no pan is
// coming can hand back the project and its offscreen canvas early.
window.endPan = function () { dropScene(); };

// ---- auto_shadow geometry probe (OSS auto_shadow.py, 1.109) ---------------
// For each requested {casting, receiving} pair, compute the RAW caster∩receiver
// overlap area and the SURVIVAL ratio after the renderer's own per-pair
// subtractions — via the same buildPairShadowRegion castStrandShadow uses, so
// the probe can never diverge from what actually renders. Pure computation:
// paper is set up on a throwaway offscreen canvas and nothing is kept (the next
// renderFixture call does its own paper.setup). Areas are returned in WORLD
// units² — call with meta.supersample = 1 and no zoom (S = 1) or they scale.
// The pair's own `visibility` override is intentionally NOT applied: the caller
// wipes auto entries first and skips user-authored pairs, matching
// recompute_auto_shadow_overrides.
window.computeShadowPairAreas = function (strands, meta, pairs) {
  CURVE = meta.curve_params || CURVE_DEFAULT;
  SAMPLE_STEP = 1;
  const ss = meta.supersample || 1;
  const zoom = meta.zoom || 1;
  const S = ss * zoom;
  const hi = document.createElement('canvas');
  hi.setAttribute('hidpi', 'off');
  hi.width = 8; hi.height = 8;
  // The probe runs on its own throwaway project, which must be handed back on
  // the way out and the caller's left active again. It is called from inside a
  // store commit — once per mask-affecting edit — so leaving the project behind
  // grew paper.projects without bound, and left a project that is NOT the
  // retained scene active for whatever drew next.
  const callerProject = paper.project;
  paper.setup(hi);
  const probeProject = paper.project;
  try {
    const ox = meta.x_offset || 0, oy = meta.y_offset || 0;
    const P = (pt) => new paper.Point(pt.x * S + ox * ss, pt.y * S + oy * ss);
    const enableThird = resolveEnableThird(strands, meta);
    BIAS_ENABLED = !!(meta && meta.enable_curvature_bias_control);
    applyPaintSettings(meta);

    const byLayer = {};
    for (const s of strands) byLayer[s.layer_name] = s;
    if (Array.isArray(meta.layer_order) && meta.layer_order.length) {
      const rank = new Map(meta.layer_order.map((name, idx) => [name, idx]));
      if (strands.every((s) => rank.has(s.layer_name))) {
        strands = strands.slice().sort((a, b) => rank.get(a.layer_name) - rank.get(b.layer_name));
      }
    }
    for (const s of strands) {
      if (s.type === 'MaskedStrand') continue;
      s.has_circles = computeHasCircles(s, strands);
    }
    SHADOW_OVERRIDES = meta.shadow_overrides || {};

    const unit = S * S; // px² per world-unit²
    const idxOf = (name) => strands.findIndex((s) => s.layer_name === name);
    const out = [];
    for (const pr of pairs) {
      const i = idxOf(pr.casting), j = idxOf(pr.receiving);
      const res = { casting: pr.casting, receiving: pr.receiving, rawArea: 0, ratio: 0 };
      out.push(res);
      if (i < 0 || j < 0 || j >= i) continue;
      const s = strands[i], o = strands[j];
      if (s.type === 'MaskedStrand') continue; // candidates are body strands

      const core = buildShadowCasterCore(s, P, enableThird, S);
      if (!core) continue;
      // Probe uses the RAW (un-cut) caster footprint — no transparentEndCap cut —
      // matching OSS auto_shadow.compute_auto_hidden_pairs (auto_shadow.py:190-197),
      // which calls build_shadow_geometry directly (the cut lives only in
      // draw_strand_shadow, i.e. the render path in castStrandShadow).
      const circles = buildShadowCasterCircles(s, P, S);
      let footprint = core.clone();
      if (circles) { const u = footprint.unite(circles); footprint.remove(); footprint = u; }

      // RAW overlap: caster footprint ∩ receiver rendered geometry, before any
      // gating/subtraction (auto_shadow.py "raw" / shader_utils.py:1950-1969).
      const recvRaw = o.type === 'MaskedStrand'
        ? buildMaskPath(o, byLayer, P, enableThird, S)
        : buildShadowReceiverGeom(o, strands, P, enableThird, S);
      if (recvRaw) {
        const raw = footprint.intersect(recvRaw);
        res.rawArea = Math.abs(raw.area || 0) / unit;
        raw.remove(); recvRaw.remove();
    }

      if (res.rawArea > 0) {
        const ov = (SHADOW_OVERRIDES[s.layer_name] || {})[o.layer_name] || null;
        const allowFull = !!(ov && ov.allow_full_shadow);
        const r = buildPairShadowRegion(
          s, i, o, j, strands, byLayer, P, enableThird, S, footprint, ov, allowFull, null);
        const survArea = r.region ? Math.abs(r.region.area || 0) / unit : 0;
        r.region && r.region.remove();
        r.recv && r.recv.remove();
        r.clipBlocker && r.clipBlocker.remove();
        res.ratio = survArea / res.rawArea;
      }

      footprint.remove(); core.remove(); circles && circles.remove();
    }
    return out;
  } finally {
    probeProject.remove();
    // activate() on a project torn down by a concurrent render would throw, and
    // the probe's answer must not be lost to bookkeeping.
    try { if (callerProject && callerProject !== probeProject) callerProject.activate(); } catch { /* gone */ }
  }
};

// The FILL region of one mask (Qt get_mask_path(), exactly the region drawMasked
// paints) handed back for the "Draw Names" label: OSS draw_strand_label centres a
// mask's label on mask_path.boundingRect() and clips the text to that path
// (strand_drawing_canvas.py draw_strand_label). Pure computation on a throwaway
// project, like computeShadowPairAreas above, and nothing is kept. Geometry is
// in WORLD units (identity P, S = 1) so the caller applies its own view
// transform. Returns { pathData, bounds: {x, y, width, height} } or null when
// the mask has no region (missing component, fully erased).
window.maskLabelClip = function (maskName, strands, meta) {
  CURVE = meta.curve_params || CURVE_DEFAULT;
  SAMPLE_STEP = 1;
  const hi = document.createElement('canvas');
  hi.setAttribute('hidpi', 'off');
  hi.width = 8; hi.height = 8;
  const callerProject = paper.project;
  paper.setup(hi);
  const probeProject = paper.project;
  try {
    const P = (pt) => new paper.Point(pt.x, pt.y);
    const enableThird = resolveEnableThird(strands, meta);
    BIAS_ENABLED = !!(meta && meta.enable_curvature_bias_control);
    applyPaintSettings(meta);
    const byLayer = {};
    for (const s of strands) byLayer[s.layer_name] = s;
    const ms = byLayer[maskName];
    if (!ms || ms.type !== 'MaskedStrand') return null;
    for (const s of strands) {
      if (s.type === 'MaskedStrand') continue;
      s.has_circles = computeHasCircles(s, strands);
    }
    const region = buildMaskPath(ms, byLayer, P, enableThird, 1);
    if (!region) return null;
    const b = region.bounds;
    const out = { pathData: region.pathData, bounds: { x: b.x, y: b.y, width: b.width, height: b.height } };
    region.remove();
    return out;
  } finally {
    probeProject.remove();
    try { if (callerProject && callerProject !== probeProject) callerProject.activate(); } catch { /* gone */ }
  }
};

// The SELECTION footprint of one mask (Qt MaskedStrand.get_selection_path():
// get_mask_path_stroke() UNITED with get_mask_path(), masked_strand.py:281-287 —
// the stroke layer plus the fill layer, minus the deletion rectangles) as SVG
// path data in WORLD units. It is what OSS hovers, highlights and hit-tests a
// mask against, and the editor's overlay / hitTest use it for exactly that.
// Same throwaway-project pattern as maskLabelClip; nothing is kept. Returns
// { pathData, bounds } or null when the mask has no region.
window.maskSelectionPath = function (maskName, strands, meta) {
  CURVE = meta.curve_params || CURVE_DEFAULT;
  SAMPLE_STEP = 1;
  const hi = document.createElement('canvas');
  hi.setAttribute('hidpi', 'off');
  hi.width = 8; hi.height = 8;
  const callerProject = paper.project;
  paper.setup(hi);
  const probeProject = paper.project;
  try {
    const P = (pt) => new paper.Point(pt.x, pt.y);
    const enableThird = resolveEnableThird(strands, meta);
    BIAS_ENABLED = !!(meta && meta.enable_curvature_bias_control);
    applyPaintSettings(meta);
    const byLayer = {};
    for (const s of strands) byLayer[s.layer_name] = s;
    const ms = byLayer[maskName];
    if (!ms || ms.type !== 'MaskedStrand') return null;
    for (const s of strands) {
      if (s.type === 'MaskedStrand') continue;
      s.has_circles = computeHasCircles(s, strands);
    }
    const region = buildMaskVisualPath(ms, byLayer, P, enableThird, 1);
    if (!region) return null;
    const b = region.bounds;
    const out = { pathData: region.pathData, bounds: { x: b.x, y: b.y, width: b.width, height: b.height } };
    region.remove();
    return out;
  } finally {
    probeProject.remove();
    try { if (callerProject && callerProject !== probeProject) callerProject.activate(); } catch { /* gone */ }
  }
};

// Extract the flat strands array from a fixture file (handles the
// OpenStrandStudioHistory wrapper). Mirrors js_render.mjs / reference_render.py.
window.extractStrands = function (data, step) {
  if (data && data.type === 'OpenStrandStudioHistory') {
    const target = step != null ? step : data.current_step;
    const state = (data.states || []).find((s) => s.step === target);
    return state ? state.data.strands : [];
  }
  return data.strands || [];
};
