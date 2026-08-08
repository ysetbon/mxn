"""Build and audit a `ks = [x, y, z, ...]` sequence, optionally rendering frames.

One process per case, so several sizes can run in parallel shells. Imports the
live algorithm from `src/`, never the snapshot in `algorithm/`.

    python3 continuation/make_diagrams.py --m 2 --n 2 --ks 1 1 -1
    python3 continuation/make_diagrams.py --m 3 --n 3 --ks 1 1 -1 --render --out /tmp/seq

Every level is checked on the three things that actually decide whether it is a
weave -- see ALGORITHM.md, "Why crossings and not gaps".
"""
import argparse
import contextlib
import io
import json
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(HERE), "src")
sys.path.insert(0, SRC)

import mxn_continuation_next as NX
from ui_utils import _get_active_strands


def audit(strands, level):
    """(across, within, masks, stray, broken) for the ring this level produced.

    `broken` counts arms whose crossings do not alternate over/under. A mask
    forces its `first_selected_strand` over; an unmasked crossing goes to
    whichever arm is drawn later. Masks landing on real crossings is necessary
    but not sufficient — the unmasked half depends on the arms' draw order, and
    a stale order breaks the weave without moving a single mask.
    """
    _, _, dst_a, dst_b = NX.level_suffixes(level)
    arms = [s for s in strands if s.get("type") == "AttachedStrand"
            and s["layer_name"].endswith((f"_{dst_a}", f"_{dst_b}"))]
    if len(arms) < 4:
        return 0, 0, 0, 0, 0
    by_name = {s["layer_name"]: s for s in arms}
    band_a, _band_b, _fan = NX._split_direction_families(by_name, list(by_name))
    band_a = set(band_a)

    masks = [s for s in strands if s.get("type") == "MaskedStrand"
             and NX._is_level_mask(s.get("layer_name", ""), dst_a, dst_b)]
    masked_over = {frozenset((s.get("first_selected_strand"),
                              s.get("second_selected_strand"))):
                   s.get("first_selected_strand") for s in masks}
    draw_index = {s["layer_name"]: i for i, s in enumerate(strands)}

    across = within = 0
    crossing_pairs = set()
    along = {a["layer_name"]: [] for a in arms}
    for i, a in enumerate(arms):
        for b in arms[i + 1:]:
            if NX._segment_crossing(a, b) is None:
                continue
            an, bn = a["layer_name"], b["layer_name"]
            crossing_pairs.add(frozenset((an, bn)))
            if (an in band_a) == (bn in band_a):
                within += 1
            else:
                across += 1
            over = masked_over.get(frozenset((an, bn)))
            if over is None:
                over = an if draw_index[an] > draw_index[bn] else bn
            along[an].append((NX._segment_crossing(a, b), over == an))
            along[bn].append((NX._segment_crossing(b, a), over == bn))

    broken = 0
    for seq in along.values():
        seq.sort()
        if any(seq[i][1] == seq[i + 1][1] for i in range(len(seq) - 1)):
            broken += 1

    stray = sum(1 for s in masks
                if frozenset((s.get("first_selected_strand"),
                              s.get("second_selected_strand"))) not in crossing_pairs)
    return across, within, len(masks), stray, broken


def describe(result, strands, level, k, expected):
    across, within, n_masks, stray, broken = audit(strands, level)

    def state(axis):
        r = result[axis]
        return "ok" if r.get("success") else ("fb" if r.get("is_fallback") else "FAIL")

    search = result["search"]
    applied = []
    if search["horizontal"].get("seeded") or search["vertical"].get("seeded"):
        applied.append("seeded")
    if search["horizontal"].get("rescued") or search["vertical"].get("rescued"):
        applied.append("regrouped")
    if search["horizontal"].get("mirrored") or search["vertical"].get("mirrored"):
        applied.append("bands mirrored")
    if search.get("masks_relaid"):
        applied.append("masks re-laid")

    healthy = across == expected and not within and not stray and not broken
    print(f"  L{level} k={k:<3d}{state('horizontal')}/{state('vertical'):<4s} "
          f"gap {result['horizontal'].get('average_gap', 0):7.2f}/"
          f"{result['vertical'].get('average_gap', 0):<7.2f} "
          f"ext {tuple(result['horizontal'].get('pair_extensions') or ())}"
          f"{tuple(result['vertical'].get('pair_extensions') or ())}")
    print(f"        across {across:>3d}/{expected}  within {within:>2d}  "
          f"masks {n_masks:>2d}  stray {stray:>2d}  broken {broken:>2d}   "
          f"{', '.join(applied) or 'k-based groups'}   "
          f"{'WEAVE' if healthy else '<<< NOT A WEAVE'}")
    sys.stdout.flush()
    return {"level": level, "k": k, "expected": expected,
            "state": f"{state('horizontal')}/{state('vertical')}",
            "gap": [result["horizontal"].get("average_gap", 0),
                    result["vertical"].get("average_gap", 0)],
            "ext": [list(result["horizontal"].get("pair_extensions") or ()),
                    list(result["vertical"].get("pair_extensions") or ())],
            "across": across, "within": within, "masks": n_masks, "stray": stray,
            "broken": broken, "applied": applied, "healthy": healthy}


def run(m, n, ks, hand, direction, render, out_dir):
    engine = NX.get_engine(hand)
    expected = (m * 2) * (n * 2)
    started = time.time()
    rows, stages = [], []

    print(f"=== {m}x{n} {hand} {direction} ks={ks}   "
          f"(a healthy ring: across {expected}, within 0, stray 0) ===")

    with contextlib.redirect_stdout(io.StringIO()):
        strands = _get_active_strands(
            json.loads(engine.generate_json(m, n, ks[0], direction)))
        stages.append({"level": 0, "k": None, "label": "starting stitch",
                       "json": NX.build_starting_stitch_json(
                           m, n, hand, reference_strands=strands)})
        real_to_virtual, virtual_to_real = NX._identity_relabel(hand, m, n)
        result = NX.align_continuation_level(
            strands, m, n, ks[0], direction, hand, 1,
            {"level": 1, "k": ks[0], "real_to_virtual": real_to_virtual,
             "virtual_to_real": virtual_to_real,
             "new_masks": [s for s in strands if s.get("type") == "MaskedStrand"
                           and NX._is_level_mask(s.get("layer_name", ""), 4, 5)]},
            verbose=False)
        stages.append({"level": 1, "k": ks[0], "label": "1st twist",
                       "json": NX._snapshot_json(strands)})
        snapshot = [dict(s) for s in strands]
    rows.append(describe(result, snapshot, 1, ks[0], expected))

    # Every settled level donates its combos as a seed for the next ones,
    # most recent first — deeper rings tend to land on combos already seen.
    seeds = [(rows[0]["ext"][0], rows[0]["ext"][1])]

    prev_v2r = virtual_to_real
    for level in range(2, len(ks) + 1):
        with contextlib.redirect_stdout(io.StringIO()):
            strands, info = NX.add_continuation_level(
                strands, m, n, ks[level - 1], direction, hand, level,
                k_prev=ks[level - 2], prev_virtual_to_real=prev_v2r,
                verbose=False)
            prev_v2r = info["virtual_to_real"]
            result = NX.align_continuation_level(
                strands, m, n, ks[level - 1], direction, hand, level, info,
                seed_extensions=list(reversed(seeds)), verbose=False)
            ordinal = {2: "2nd", 3: "3rd"}.get(level, f"{level}th")
            stages.append({"level": level, "k": ks[level - 1],
                           "label": f"{ordinal} twist",
                           "json": NX._snapshot_json(strands)})
            snapshot = [dict(s) for s in strands]
        rows.append(describe(result, snapshot, level, ks[level - 1], expected))
        seeds.append((rows[-1]["ext"][0], rows[-1]["ext"][1]))

    report = {"m": m, "n": n, "hand": hand, "direction": direction, "ks": ks,
              "expected": expected, "seconds": round(time.time() - started, 1),
              "rows": rows}

    if render:
        os.makedirs(out_dir, exist_ok=True)
        import mxn_continuation_render as RND
        canvas, kind = RND.create_render_canvas()
        prefix = f"{m}x{n}_{'_'.join(str(x) for x in ks)}_"
        written = RND.render_sequence(stages, out_dir, prefix=prefix,
                                      scale_factor=2.0, transparent=True,
                                      canvas=canvas)
        report["frames"] = [{"path": p, "label": lab} for p, lab in written]
        print(f"  rendered {len(written)} frames ({kind}) into {out_dir}")

    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"{m}x{n}_{'_'.join(str(x) for x in ks)}.json")
        with open(path, "w") as fh:
            json.dump(report, fh, indent=1)
        print(f"  wrote {path}")

    print(f"  ({report['seconds']:.0f}s) "
          f"{sum(1 for r in rows if r['healthy'])}/{len(rows)} levels are weaves")
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--m", type=int, required=True)
    ap.add_argument("--n", type=int, required=True)
    ap.add_argument("--ks", type=int, nargs="+", required=True,
                    help="one k per level, e.g. --ks 1 1 -1")
    ap.add_argument("--hand", default="lh", choices=("lh", "rh"))
    ap.add_argument("--direction", default="cw", choices=("cw", "ccw"))
    ap.add_argument("--render", action="store_true",
                    help="also draw the frames (needs openstrandstudio)")
    ap.add_argument("--out", default=None, help="directory for frames and JSON")
    args = ap.parse_args()

    if 0 in args.ks[1:]:
        print("note: k=0 preserves the continuation exactly, with no search")
    report = run(args.m, args.n, args.ks, args.hand, args.direction,
                 args.render, args.out)
    return 0 if all(r["healthy"] for r in report["rows"]) else 1


if __name__ == "__main__":
    sys.exit(main())
