"""Render a 2x2 lh cw ks sequence to standalone SVGs + a stats JSON, no Qt needed.

    python3 continuation/render_svg.py --out continuation/docs/2x2-seven-twists 1 1 -1 -1 -1 -1 -1


Same technique as the stitch-sheet renderer, generalised to any depth:
paint order is level 0 strands -> level 0 masks -> level 1 arms -> level 1
masks -> ... with strand-list order kept inside each layer (the list order is
the weave's draw order). A mask paints its first (over) strand clipped to a
band along its second (under) strand.
"""
import argparse, contextlib, io, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))
import mxn_continuation_next as NX

HORIZ_HEX = ['#FFFFFF', '#55AA00']
VERT_HEX = ['#3D3A8C', '#7B71D6']


def _hexrgb(h):
    return f"rgb({int(h[1:3],16)},{int(h[3:5],16)},{int(h[5:7],16)})"


def strand_level(s):
    """0 for _1/_2/_3, else the continuation level of the suffix."""
    if s.get("type") == "MaskedStrand":
        members = (s.get("first_selected_strand", ""), s.get("second_selected_strand", ""))
        return max(strand_level({"layer_name": mm, "type": "AttachedStrand"})
                   for mm in members)
    suffix = int(s["layer_name"].rsplit("_", 1)[1])
    return 0 if suffix <= 3 else (suffix - 2) // 2


def build_sequence(ks):
    buf = io.StringIO()
    stages = []
    with contextlib.redirect_stdout(buf):
        _starting, strands, info1 = NX.build_level_one(
            2, 2, ks[0], "lh", "cw", verbose=False)
        prev_v2r = info1["virtual_to_real"]
        res = NX.align_continuation_level(strands, 2, 2, ks[0], "cw", "lh", 1, info1)
        stages.append(("L1", [json.loads(json.dumps(s)) for s in strands]))
        stats = [stat_row(res, 1, ks[0])]
        seeds = [(tuple(res["horizontal"].get("pair_extensions") or ()),
                  tuple(res["vertical"].get("pair_extensions") or ()))]
        level1_for_k = {ks[0]: seeds[0]}
        for level in range(2, len(ks) + 1):
            k_level = ks[level - 1]
            if k_level not in level1_for_k:
                _starting, s1, info_k = NX.build_level_one(
                    2, 2, k_level, "lh", "cw", verbose=False)
                r1 = NX.align_continuation_level(
                    s1, 2, 2, k_level, "cw", "lh", 1, info_k, verbose=False)
                level1_for_k[k_level] = (
                    tuple(r1["horizontal"].get("pair_extensions") or ()),
                    tuple(r1["vertical"].get("pair_extensions") or ()))
            k_seed = level1_for_k[k_level]
            level_seeds = ([k_seed] if all(k_seed) else []) + list(reversed(seeds))
            strands, info = NX.add_continuation_level(
                strands, 2, 2, k_level, "cw", "lh", level,
                k_prev=ks[level - 2], prev_virtual_to_real=prev_v2r, verbose=False)
            prev_v2r = info["virtual_to_real"]
            res = NX.align_continuation_level(strands, 2, 2, k_level, "cw", "lh",
                                              level, info,
                                              seed_extensions=level_seeds,
                                              verbose=False)
            seeds.append((tuple(res["horizontal"].get("pair_extensions") or ()),
                          tuple(res["vertical"].get("pair_extensions") or ())))
            stages.append((f"L{level}", [json.loads(json.dumps(s)) for s in strands]))
            stats.append(stat_row(res, level, k_level))
    return stages, stats


def stat_row(res, level, k):
    sh, sv = res["search"]["horizontal"], res["search"]["vertical"]
    tags = []
    if sh.get("seeded") or sv.get("seeded"):
        tags.append("seeded")
    if sh.get("rescued") or sv.get("rescued"):
        tags.append("regrouped")
    if sh.get("mirrored") or sv.get("mirrored"):
        tags.append("bands mirrored")
    if not tags:
        tags.append("k-based groups")
    return {"level": level, "k": k,
            "gap": [round(res["horizontal"].get("average_gap", 0), 2),
                    round(res["vertical"].get("average_gap", 0), 2)],
            "ext": [list(res["horizontal"].get("pair_extensions") or ()),
                    list(res["vertical"].get("pair_extensions") or ())],
            "tags": tags}


def color_for(s, vert_sets):
    num = s["set_number"]
    if num in vert_sets:
        return _hexrgb(VERT_HEX[sorted(vert_sets).index(num) % len(VERT_HEX)])
    horiz = sorted({1, 2, 3, 4} - vert_sets)
    return _hexrgb(HORIZ_HEX[horiz.index(num) % len(HORIZ_HEX)])


def vertical_sets(strands):
    out = set()
    for s in strands:
        if s.get("type") == "MaskedStrand" or not s["layer_name"].endswith("_2"):
            continue
        if abs(s["end"]["y"] - s["start"]["y"]) > abs(s["end"]["x"] - s["start"]["x"]):
            out.add(s["set_number"])
    return out


def bounds(strands, pad=80):
    xs, ys = [], []
    for s in strands:
        if s.get("type") == "MaskedStrand":
            continue
        for p in (s["start"], s["end"]):
            xs.append(p["x"]); ys.append(p["y"])
    return min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad


def render(strands, view, label, max_level, idp):
    vert = vertical_sets(strands)
    by_name = {s["layer_name"]: s for s in strands}
    x0, y0, x1, y1 = view
    w, h = x1 - x0, y1 - y0
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" '
           f'viewBox="{x0:.1f} {y0:.1f} {w:.1f} {h:.1f}" width="100%" '
           f'style="height:auto;display:block">']

    def band_path(s, width):
        """Closed flat-cap band matching QPainterPathStroker.FlatCap."""
        ax, ay = s["start"]["x"], s["start"]["y"]
        bx, by = s["end"]["x"], s["end"]["y"]
        dx, dy = bx - ax, by - ay
        length = (dx * dx + dy * dy) ** 0.5 or 1.0
        nx, ny = -dy / length * width / 2, dx / length * width / 2
        return (f'M {ax+nx:.2f},{ay+ny:.2f} L {bx+nx:.2f},{by+ny:.2f} '
                f'L {bx-nx:.2f},{by-ny:.2f} L {ax-nx:.2f},{ay-ny:.2f} Z')

    def shape_parts(s, width, color, clip_id=None, mask_geometry=False):
        """Return one unified SVG paint layer for a strand body and its caps.

        Mask geometry follows OpenStrandStudio: only an AttachedStrand's
        visible start cap participates in the path intersection. Regular
        strand painting keeps the endpoint flags from the JSON.
        """
        ax, ay = s["start"]["x"], s["start"]["y"]
        bx, by = s["end"]["x"], s["end"]["y"]
        clip = f' clip-path="url(#{clip_id})"' if clip_id else ""
        parts = [f"<g{clip}>"]
        if mask_geometry:
            circle_indexes = (0,) if (s.get("type") == "AttachedStrand"
                                      and s.get("has_circles", [False])[0]) else ()
        else:
            circle_indexes = tuple(i for i, visible in
                                   enumerate(s.get("has_circles", [False, False]))
                                   if visible)
        for i in circle_indexes:
            cx, cy = (ax, ay) if i == 0 else (bx, by)
            parts.append(f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{width/2:.2f}" fill="{color}"/>')
        parts.append(f'<path d="{band_path(s, width)}" fill="{color}"/>')

        parts.append("</g>")
        return "".join(parts)

    out.append("<defs>")
    for s in strands:
        if s.get("type") != "MaskedStrand" or strand_level(s) > max_level:
            continue
        second = by_name.get(s["second_selected_strand"])
        if second is None:
            continue
        outer_width = second["width"] + 2 * second["stroke_width"]
        for suffix, clip_width in (("stroke", outer_width), ("fill", outer_width + 4)):
            clip_id = f'{idp}m_{s["layer_name"]}_{suffix}'
            out.append(f'<clipPath id="{clip_id}" clipPathUnits="userSpaceOnUse">')
            # A clip path is the union of its children. Use the same flat body
            # plus visible AttachedStrand start cap as MaskedStrand.get_*_path.
            ax, ay = second["start"]["x"], second["start"]["y"]
            bx, by = second["end"]["x"], second["end"]["y"]
            out.append(f'<path d="{band_path(second, clip_width)}" fill="white"/>')

            if (second.get("type") == "AttachedStrand"
                    and second.get("has_circles", [False])[0]):
                out.append(f'<circle cx="{ax:.2f}" cy="{ay:.2f}" r="{clip_width/2:.2f}" fill="white"/>')
            out.append("</clipPath>")
    out.append("</defs>")

    for lvl in range(0, max_level + 1):
        # OpenStrandStudio completes a level's ordinary strands, then paints
        # its MaskedStrand intersections on top before the next level begins.
        for s in strands:
            if s.get("type") == "MaskedStrand" or strand_level(s) != lvl:
                continue
            col = color_for(s, vert)
            out.append(shape_parts(s, s["width"] + 2 * s["stroke_width"], "black"))
            out.append(shape_parts(s, s["width"], col))
        for s in strands:
            if s.get("type") != "MaskedStrand" or strand_level(s) != lvl:
                continue
            first = by_name.get(s["first_selected_strand"])
            if first is None:
                continue
            col = color_for(first, vert)
            out.append(shape_parts(
                first,
                first["width"] + 2 * first["stroke_width"],
                "black",
                f'{idp}m_{s["layer_name"]}_stroke',
                mask_geometry=True,
            ))
            out.append(shape_parts(
                first,
                first["width"],
                col,
                f'{idp}m_{s["layer_name"]}_fill',
                mask_geometry=True,
            ))
    # label the newest ring's arms
    da, db = 2 * max_level + 2, 2 * max_level + 3
    for s in strands:
        if s.get("type") == "MaskedStrand":
            continue
        if not s["layer_name"].endswith((f"_{da}", f"_{db}")):
            continue
        ax, ay = s["start"]["x"], s["start"]["y"]
        bx, by = s["end"]["x"], s["end"]["y"]
        dx, dy = bx - ax, by - ay
        n = (dx*dx + dy*dy) ** 0.5 or 1.0
        fs = w / 30.0
        lx, ly = bx + dx/n*(fs*1.4), by + dy/n*(fs*1.4)
        out.append(f'<text x="{lx:.1f}" y="{ly:.1f}" font-family="ui-monospace,monospace" '
                   f'font-size="{fs:.1f}" font-weight="700" text-anchor="middle" '
                   f'dominant-baseline="central" fill="#111" stroke="#fff" '
                   f'stroke-width="{fs*0.28:.1f}" paint-order="stroke">{s["layer_name"]}</text>')
    out.append("</svg>")
    return "".join(out)


ap = argparse.ArgumentParser()
ap.add_argument("--out", default=".", help="directory for the SVGs and stats")
ap.add_argument("ks", type=int, nargs="+", help="one k per level, e.g. 1 1 -1")
args = ap.parse_args()
OUT = args.out
os.makedirs(OUT, exist_ok=True)
stages, stats = build_sequence(args.ks)
view = bounds(stages[-1][1])   # one shared viewport so the frames read as a progression
for i, (label, strands) in enumerate(stages, start=1):
    svg = render(strands, view, label, max_level=i, idp=f"f{i}_")
    path = f"{OUT}/frame_{label}.svg"
    with open(path, "w") as fh:
        fh.write(svg)
    print(path, len(svg), "bytes")
with open(f"{OUT}/seq_stats.json", "w") as fh:
    json.dump(stats, fh, indent=1)
print("stats written")
