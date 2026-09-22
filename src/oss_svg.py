"""Qt-free SVG port of OpenStrandStudio's strand, attached-strand and mask drawing.

The documentation renderers (``continuation/render_svg.py`` and the
stitch-sheet skill's ``render_strands.py``) cannot run Qt, so they draw the
strand JSON themselves. This module is the one place that geometry lives, and
it follows OpenStrandStudio line for line:

* ``save_load_manager.load_strands_from_data`` - ``has_circles`` is recomputed
  from the real attachments on load (an attached strand always keeps its start
  circle; any other end has a circle only when a child is attached there).
* ``Strand.draw`` / ``AttachedStrand.draw`` - the body is a flat-capped stroke
  of ``width + 2*stroke_width`` in the stroke colour and a flat-capped stroke of
  ``width`` in the fill colour. A junction end adds the outward half of the
  outer circle to the stroke layer, the inner circle plus a ``stroke_width``
  deep rectangle to the fill layer. A free end gets a ``stroke_width`` side
  line just past the flat cap. An attached strand never draws a start side
  line, and always adds its inner end circle when ``has_circles[1]`` is set.
* ``MaskedStrand.draw`` - the stroke layer is the intersection of both
  components stroked at ``width + 2*stroke_width``, painted in the first
  strand's stroke colour; the fill layer is the first strand at ``width``
  intersected with the second at ``width + 2*stroke_width + 4``, painted in
  the first strand's colour. An attached component contributes its start
  circle to both. Deletion rectangles are cut out of both layers.
* ``mxn_continuation_render.render_canvas_image`` - strands are painted in the
  loaded layer order (the ``index`` slots), shadows off.

Elliptical end caps, stylized ends, arrows, extensions and shadows are not
used by MxN patterns and are not drawn.
"""
import math

__all__ = ["layer_order", "effective_circles", "draw_strands", "strand_bounds"]


def _pt(p):
    return (float(p["x"]), float(p["y"]))


def _same(a, b):
    return abs(a[0] - b[0]) < 1e-6 and abs(a[1] - b[1]) < 1e-6


def _rgba(c):
    return (int(c.get("r", 0)), int(c.get("g", 0)), int(c.get("b", 0)), int(c.get("a", 255)))


def _alpha(s, key):
    c = s.get(key)
    return 255 if c is None else int(c.get("a", 255))


def _fmt(v):
    return f"{v:.3f}".rstrip("0").rstrip(".")


# --------------------------------------------------------------------------
# Loader: layer order and has_circles as OpenStrandStudio sees them
# --------------------------------------------------------------------------

def layer_order(strands):
    """The strands in the order OpenStrandStudio paints them after loading.

    ``load_strands_from_data`` drops every strand into slot ``strand["index"]``
    (plain strands, then attached strands once their parent exists, then
    masks), so the ``index`` field - not the list position - is the layer
    order, and a repeated index keeps only the last strand written there.
    Without indices the list order is used, as exported by MxN.
    """
    if any(not isinstance(s.get("index"), int) or s["index"] < 0 for s in strands):
        return list(strands)
    slots = [None] * len(strands)
    known = set()

    def put(s):
        idx = s["index"]
        if idx >= len(slots):
            slots.extend([None] * (idx - len(slots) + 1))
        slots[idx] = s
        known.add(s["layer_name"])

    for s in strands:
        if s.get("type") == "Strand":
            put(s)
    pending = [s for s in strands if s.get("type") == "AttachedStrand"]
    while pending:
        rest = [s for s in pending if s.get("attached_to") not in known]
        for s in pending:
            if s.get("attached_to") in known:
                put(s)
        if len(rest) == len(pending):
            break
        pending = rest
    for s in strands:
        if (s.get("type") == "MaskedStrand"
                and s.get("first_selected_strand") in known
                and s.get("second_selected_strand") in known):
            put(s)
    return [s for s in slots if s is not None]


def effective_circles(strands):
    """Map layer_name -> [start, end] circle flags after OpenStrandStudio's load.

    Mirrors the "validate has_circles" pass of ``load_strands_from_data``,
    including ``manual_circle_visibility`` overrides.
    """
    children = {}
    for s in strands:
        if s.get("type") == "AttachedStrand" and s.get("attached_to"):
            children.setdefault(s["attached_to"], []).append(s)
    out = {}
    for s in strands:
        if s.get("type") == "MaskedStrand":
            out[s["layer_name"]] = list(s.get("has_circles", [False, False]))
            continue
        start, end = _pt(s["start"]), _pt(s["end"])
        at_start = at_end = False
        for child in children.get(s["layer_name"], []):
            side = child.get("attachment_side", 0)
            cs = _pt(child["start"])
            if s.get("type") == "AttachedStrand":
                if _same(cs, end) and side == 1:
                    at_end = True
            elif _same(cs, start) and side == 0:
                at_start = True
            elif _same(cs, end) and side == 1:
                at_end = True
        manual = s.get("manual_circle_visibility") or [None, None]
        if s.get("type") == "AttachedStrand":
            flags = [True if manual[0] is None else bool(manual[0]),
                     at_end if manual[1] is None else bool(manual[1])]
        else:
            flags = [at_start if manual[0] is None else bool(manual[0]),
                     at_end if manual[1] is None else bool(manual[1])]
        out[s["layer_name"]] = flags
    return out


# --------------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------------

class _Geo:
    """Centre-line geometry of one strand (a cubic Bezier, usually straight)."""

    def __init__(self, s):
        self.a = _pt(s["start"])
        self.b = _pt(s["end"])
        cps = s.get("control_points") or []
        if len(cps) >= 2 and cps[0] and cps[1]:
            self.c1, self.c2 = _pt(cps[0]), _pt(cps[1])
        else:
            self.c1, self.c2 = self.a, self.b
        self.straight = self._collinear()

    def _collinear(self):
        ax, ay = self.a
        dx, dy = self.b[0] - ax, self.b[1] - ay
        n = math.hypot(dx, dy)
        if n == 0:
            return True
        for px, py in (self.c1, self.c2):
            if abs((px - ax) * dy - (py - ay) * dx) / n > 1e-6:
                return False
            t = ((px - ax) * dx + (py - ay) * dy) / (n * n)
            if t < -1e-9 or t > 1 + 1e-9:
                return False
        return True

    def point(self, t):
        u = 1 - t
        return tuple(u ** 3 * p0 + 3 * u * u * t * p1 + 3 * u * t * t * p2 + t ** 3 * p3
                     for p0, p1, p2, p3 in zip(self.a, self.c1, self.c2, self.b))

    def tangent(self, t):
        u = 1 - t
        return tuple(3 * u * u * (p1 - p0) + 6 * u * t * (p2 - p1) + 3 * t * t * (p3 - p2)
                     for p0, p1, p2, p3 in zip(self.a, self.c1, self.c2, self.b))

    def angle(self, t):
        """Tangent angle with Strand.calculate_cubic_tangent's fallbacks."""
        tx, ty = self.tangent(t)
        if abs(tx) + abs(ty) == 0:
            tx, ty = self.b[0] - self.a[0], self.b[1] - self.a[1]
        if abs(tx) + abs(ty) == 0:
            return 0.0
        return math.atan2(ty, tx)

    def samples(self):
        if self.straight:
            return [self.a, self.b]
        return [self.point(i / 64) for i in range(65)]

    def band(self, width):
        """Closed flat-cap stroke outline (QPainterPathStroker, FlatCap)."""
        pts = self.samples()
        h = width / 2
        left, right = [], []
        for i, (x, y) in enumerate(pts):
            if self.straight:
                ang = math.atan2(self.b[1] - self.a[1], self.b[0] - self.a[0])
            else:
                ang = self.angle(min(max(i / (len(pts) - 1), 1e-4), 1 - 1e-4))
            nx, ny = -math.sin(ang) * h, math.cos(ang) * h
            left.append((x + nx, y + ny))
            right.append((x - nx, y - ny))
        ring = left + right[::-1]
        return "M " + " L ".join(f"{_fmt(x)},{_fmt(y)}" for x, y in ring) + " Z"


def _circle(c, r):
    x, y = c
    return (f"M {_fmt(x - r)},{_fmt(y)} A {_fmt(r)},{_fmt(r)} 0 1 0 {_fmt(x + r)},{_fmt(y)} "
            f"A {_fmt(r)},{_fmt(r)} 0 1 0 {_fmt(x - r)},{_fmt(y)} Z")


def _half_disc(c, r, outward):
    """The half of a circle on the `outward` side of its diameter (cap outer half)."""
    x, y = c
    px, py = -math.sin(outward), math.cos(outward)
    p1 = (x + px * r, y + py * r)
    p2 = (x - px * r, y - py * r)
    # From p1 = c + r*perp the arc through c + r*(cos, sin)(outward) runs
    # towards decreasing angles: SVG sweep-flag 0.
    return (f"M {_fmt(p1[0])},{_fmt(p1[1])} A {_fmt(r)},{_fmt(r)} 0 0 0 "
            f"{_fmt(p2[0])},{_fmt(p2[1])} Z")


def _rect(c, angle, x0, y0, w, h):
    """Rectangle given in a frame translated to `c` and rotated by `angle`."""
    ca, sa = math.cos(angle), math.sin(angle)
    pts = [(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h)]
    out = [(c[0] + x * ca - y * sa, c[1] + x * sa + y * ca) for x, y in pts]
    return "M " + " L ".join(f"{_fmt(x)},{_fmt(y)}" for x, y in out) + " Z"


def _line_band(p, q, width):
    """A FlatCap pen line of `width` from p to q, as a filled outline."""
    dx, dy = q[0] - p[0], q[1] - p[1]
    n = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / n * width / 2, dx / n * width / 2
    pts = [(p[0] + nx, p[1] + ny), (q[0] + nx, q[1] + ny),
           (q[0] - nx, q[1] - ny), (p[0] - nx, p[1] - ny)]
    return "M " + " L ".join(f"{_fmt(x)},{_fmt(y)}" for x, y in pts) + " Z"


# --------------------------------------------------------------------------
# Strand / AttachedStrand
# --------------------------------------------------------------------------

def _strand_layers(s, circles, children_at):
    """(stroke_paths, fill_paths, side_line_paths) exactly as Strand/AttachedStrand.draw."""
    g = _Geo(s)
    W, S = float(s["width"]), float(s["stroke_width"])
    T = W + 2 * S
    attached = s.get("type") == "AttachedStrand"
    closed = s.get("closed_connections") or [False, False]
    start_a = _alpha(s, "start_circle_stroke_color")
    end_a = _alpha(s, "end_circle_stroke_color")
    stroke = [g.band(T)]
    fill = [g.band(W)]

    ang0 = g.angle(0.0001)
    ang1 = g.angle(0.9999)

    def start_cap():
        stroke.append(_half_disc(g.a, T / 2, ang0 + math.pi))
        fill.append(_circle(g.a, W / 2))
        fill.append(_rect(g.a, ang0, -S, -W / 2, S, W))

    def end_cap():
        stroke.append(_half_disc(g.b, T / 2, ang1))
        fill.append(_circle(g.b, W / 2))
        fill.append(_rect(g.b, ang1, -S, -W / 2, S, W))

    if attached:
        if circles[0] and start_a > 0:
            start_cap()
        if circles[1] and children_at[1]:
            stroke.append(_half_disc(g.b, T / 2, ang1))
            fill.append(_circle(g.b, W / 2))
            if end_a > 0:
                fill.append(_rect(g.b, ang1, -S, -W / 2, S, W))
        if circles[1]:
            # AttachedStrand.draw always adds the inner end fill + a half-stroke
            # deep cover when has_circles[1] is set.
            fill.append(_circle(g.b, W / 2))
            fill.append(_rect(g.b, ang1, -S / 2, -W / 2, S, W))
        if circles[1] and closed[1]:
            if end_a > 0:
                stroke.append(_half_disc(g.b, T / 2, ang1))
            fill.append(_circle(g.b, W / 2))
            if end_a > 0:
                fill.append(_rect(g.b, ang1, -S, -W / 2, S, W))
    else:
        if circles[0] and start_a > 0 and children_at[0]:
            start_cap()
        if circles[1] and end_a > 0 and children_at[1]:
            end_cap()
        if closed[0] and start_a > 0:
            start_cap()
        if closed[1] and end_a > 0:
            end_cap()

    # Side lines (Strand.update_side_line / _draw_side_lines)
    lines = []
    shift = S / 2
    half = T / 2
    for side in (0, 1):
        if side == 0:
            if attached or not s.get("start_line_visible", True) or circles[0]:
                continue
            ang, p, out_ang = ang0, g.a, ang0 + math.pi
        else:
            if not s.get("end_line_visible", True) or circles[1]:
                continue
            ang, p, out_ang = ang1, g.b, ang1
        cx = p[0] + shift * math.cos(out_ang)
        cy = p[1] + shift * math.sin(out_ang)
        dx = half * math.cos(ang + math.pi / 2)
        dy = half * math.sin(ang + math.pi / 2)
        lines.append(_line_band((cx - dx, cy - dy), (cx + dx, cy + dy), S))
    return stroke, fill, lines


# --------------------------------------------------------------------------
# MaskedStrand
# --------------------------------------------------------------------------

def _mask_component(s, circles, width):
    """MaskedStrand.get_*path_for_strand: flat band + attached start circle."""
    parts = [_Geo(s).band(width)]
    if (s.get("type") == "AttachedStrand" and circles[0]
            and _alpha(s, "start_circle_stroke_color") > 0):
        parts.append(_circle(_pt(s["start"]), width / 2))
    return parts


def _deletion_paths(mask):
    out = []
    for rect in mask.get("deletion_rectangles") or []:
        if "top_left" in rect and "bottom_right" in rect:
            tl = rect["top_left"]
            tr = rect.get("top_right", rect["bottom_right"])
            br = rect["bottom_right"]
            bl = rect.get("bottom_left", rect["top_left"])
            pts = [tl, tr, br, bl]
            out.append("M " + " L ".join(f"{_fmt(p[0])},{_fmt(p[1])}" for p in pts) + " Z")
        elif all(k in rect for k in ("x", "y", "width", "height")):
            x, y, w, h = (float(rect[k]) for k in ("x", "y", "width", "height"))
            out.append(f"M {_fmt(x)},{_fmt(y)} L {_fmt(x + w)},{_fmt(y)} "
                       f"L {_fmt(x + w)},{_fmt(y + h)} L {_fmt(x)},{_fmt(y + h)} Z")
    return out


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------

def _paint(paths, rgba, attrs=""):
    """Fill a union of paths with one colour (Qt WindingFill + one drawPath)."""
    r, g, b, a = rgba
    if a <= 0 or not paths:
        return ""
    # One element per component: the group paints their union once, so a
    # translucent colour does not double up where components overlap.
    op = f' opacity="{_fmt(a / 255)}"' if a < 255 else ""
    inner = "".join(f'<path d="{d}"/>' for d in paths)
    return f'<g fill="rgb({r},{g},{b})"{op}{attrs}>{inner}</g>'


def strand_bounds(strands):
    """(min_x, min_y, max_x, max_y) of every non-mask endpoint."""
    xs, ys = [], []
    for s in strands:
        if s.get("type") == "MaskedStrand":
            continue
        for p in (s["start"], s["end"]):
            xs.append(float(p["x"]))
            ys.append(float(p["y"]))
    return min(xs), min(ys), max(xs), max(ys)


def draw_strands(strands, color_of=None, stroke_of=None, include=None, idp=""):
    """Return (defs, body) SVG fragments drawing `strands` like OpenStrandStudio.

    color_of(strand)  -> (r, g, b, a) fill colour, default the JSON colour.
    stroke_of(strand) -> (r, g, b, a) stroke colour, default the JSON stroke.
    include(strand)   -> False to skip a layer (e.g. later continuation levels).
    idp               -> id prefix, so several drawings can share one page.

    Layers are painted in OpenStrandStudio's layer order (see `layer_order`),
    a mask with its first strand's colours.
    """
    color_of = color_of or (lambda s: _rgba(s["color"]))
    stroke_of = stroke_of or (lambda s: _rgba(s.get("stroke_color") or {"a": 255}))
    circles = effective_circles(strands)
    by_name = {s["layer_name"]: s for s in strands}
    children = {}
    for s in strands:
        if s.get("type") == "AttachedStrand" and s.get("attached_to"):
            children.setdefault(s["attached_to"], []).append(_pt(s["start"]))

    defs, body = [], []
    for s in layer_order(strands):
        if include is not None and not include(s):
            continue
        if s.get("is_hidden"):
            continue
        name = s["layer_name"]
        if s.get("type") == "MaskedStrand":
            first = by_name.get(s.get("first_selected_strand"))
            second = by_name.get(s.get("second_selected_strand"))
            if first is None or second is None:
                continue
            c1, c2 = circles[first["layer_name"]], circles[second["layer_name"]]
            W1, S1 = float(first["width"]), float(first["stroke_width"])
            W2, S2 = float(second["width"]), float(second["stroke_width"])
            cuts = _deletion_paths(s)
            for suffix, clip_width, paths, rgba in (
                    ("s", W2 + 2 * S2, _mask_component(first, c1, W1 + 2 * S1), stroke_of(first)),
                    ("f", W2 + 2 * S2 + 4, _mask_component(first, c1, W1), color_of(first))):
                cid = f"{idp}m_{name}_{suffix}"
                clip = "".join(f'<path d="{d}"/>'
                               for d in _mask_component(second, c2, clip_width))
                if cuts:
                    defs.append(
                        f'<mask id="{cid}" maskUnits="userSpaceOnUse" x="-1e6" y="-1e6" '
                        f'width="2e6" height="2e6"><g fill="white">{clip}</g>'
                        f'<path d="{" ".join(cuts)}" fill="black"/></mask>')
                    body.append(_paint(paths, rgba, f' mask="url(#{cid})"'))
                else:
                    defs.append(f'<clipPath id="{cid}" clipPathUnits="userSpaceOnUse">'
                                f'{clip}</clipPath>')
                    body.append(_paint(paths, rgba, f' clip-path="url(#{cid})"'))
            continue
        starts = children.get(name, [])
        a, b = _pt(s["start"]), _pt(s["end"])
        children_at = (any(_same(p, a) for p in starts), any(_same(p, b) for p in starts))
        stroke, fill, lines = _strand_layers(s, circles[name], children_at)
        body.append(_paint(stroke, stroke_of(s)))
        body.append(_paint(fill, color_of(s)))
        body.append(_paint(lines, stroke_of(s)))
    return "".join(defs), "".join(body)
