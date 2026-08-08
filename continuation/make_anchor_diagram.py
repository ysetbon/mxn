"""Draw where extension 0 sits: the purple points.

Renders the source ring of a level, marking

  purple  each arm's OWN outermost crossing with the other band -- the point the
          arm is retracted to, and therefore where the next level's stub is
          welded. This is extension 0.
  red     the arm's end BEFORE retraction, so the gap between red and purple is
          the anchor distance the search no longer has to spend.

Writes an SVG next to this script. Run:

    python3 continuation/make_anchor_diagram.py --m 2 --n 2 --k 1
"""
import argparse
import contextlib
import io
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))

import mxn_continuation_next as NX
from ui_utils import _get_active_strands

BAND_A = "#E0913F"
BAND_B = "#3FA5A0"
PURPLE = "#9B8BD6"
RED = "#EE6352"
INK = "#8A97A0"


def build(m, n, k, hand, direction):
    """Level 1, aligned -- the ring a second level would be welded onto."""
    engine = NX.get_engine(hand)
    with contextlib.redirect_stdout(io.StringIO()):
        strands = _get_active_strands(
            json.loads(engine.generate_json(m, n, k, direction)))
        real_to_virtual, virtual_to_real = NX._identity_relabel(hand, m, n)
        NX.align_continuation_level(
            strands, m, n, k, direction, hand, 1,
            {"level": 1, "k": k, "real_to_virtual": real_to_virtual,
             "virtual_to_real": virtual_to_real, "new_masks": []}, verbose=False)
    return {s["layer_name"]: s for s in strands
            if s.get("type") == "AttachedStrand"
            and s["layer_name"].endswith(("_4", "_5"))}


def svg(ring, anchors, out_path, caption):
    xs, ys = [], []
    for arm in ring.values():
        xs += [arm["start"]["x"], arm["end"]["x"]]
        ys += [arm["start"]["y"], arm["end"]["y"]]
    pad = 70
    x0, x1, y0, y1 = min(xs) - pad, max(xs) + pad, min(ys) - pad, max(ys) + pad
    w, h = x1 - x0, y1 - y0

    band_a, _band_b, _fan = NX._split_direction_families(ring, list(ring))
    band_a = set(band_a)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0:.1f} {y0:.1f} '
        f'{w:.1f} {h:.1f}" width="720" role="img" aria-label="{caption}">',
        f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{w:.1f}" height="{h:.1f}" '
        f'fill="none"/>',
    ]
    for name, arm in ring.items():
        colour = BAND_A if name in band_a else BAND_B
        parts.append(
            f'<line x1="{arm["start"]["x"]:.2f}" y1="{arm["start"]["y"]:.2f}" '
            f'x2="{arm["end"]["x"]:.2f}" y2="{arm["end"]["y"]:.2f}" '
            f'stroke="{colour}" stroke-width="11" stroke-linecap="round" '
            f'opacity="0.85"/>')

    for name, arm in ring.items():
        distance = anchors.get(name)
        if distance is None:
            continue
        dx = arm["end"]["x"] - arm["start"]["x"]
        dy = arm["end"]["y"] - arm["start"]["y"]
        length = math.hypot(dx, dy) or 1.0
        px = arm["end"]["x"] - dx / length * distance
        py = arm["end"]["y"] - dy / length * distance
        parts.append(
            f'<line x1="{px:.2f}" y1="{py:.2f}" x2="{arm["end"]["x"]:.2f}" '
            f'y2="{arm["end"]["y"]:.2f}" stroke="{INK}" stroke-width="2" '
            f'stroke-dasharray="5 4"/>')
        parts.append(f'<circle cx="{arm["end"]["x"]:.2f}" '
                     f'cy="{arm["end"]["y"]:.2f}" r="7" fill="{RED}"/>')
        parts.append(f'<circle cx="{px:.2f}" cy="{py:.2f}" r="9" fill="{PURPLE}" '
                     f'stroke="#5B4E96" stroke-width="2"/>')

    parts.append(
        f'<text x="{x0 + 14:.1f}" y="{y0 + 30:.1f}" fill="{INK}" '
        f'font-family="ui-monospace,monospace" font-size="19">{caption}</text>')
    parts.append("</svg>")
    with open(out_path, "w") as fh:
        fh.write("\n".join(parts))
    return out_path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--m", type=int, default=2)
    ap.add_argument("--n", type=int, default=2)
    ap.add_argument("--k", type=int, default=1)
    ap.add_argument("--hand", default="lh", choices=("lh", "rh"))
    ap.add_argument("--direction", default="cw", choices=("cw", "ccw"))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    ring = build(args.m, args.n, args.k, args.hand, args.direction)
    anchors = NX.crossing_anchors(ring)
    distances = sorted(round(v, 1) for v in anchors.values())
    caption = (f"{args.m}x{args.n} {args.hand} k={args.k} - purple = extension 0 "
               f"(each arm's outermost crossing)")
    out = args.out or os.path.join(HERE, f"anchor-{args.m}x{args.n}-k{args.k}.svg")
    svg(ring, anchors, out, caption)

    print(caption)
    print(f"  {len(ring)} arms, anchor distances {distances}")
    print(f"  flat fallback would have been {NX.RETRACT} for every arm")
    print(f"  wrote {out}")


if __name__ == "__main__":
    main()
