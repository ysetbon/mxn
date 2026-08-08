# =============================================================================
# SNAPSHOT -- do not edit, and do not import this copy.
#
# The live module is `src/mxn_continuation_next.py`. This copy exists so the
# `continuation/` folder can be read on its own; `make_diagrams.py` imports
# from `src/`, never from here. If the two ever disagree, `src/` is right.
# =============================================================================

"""
MxN Multi-Level Continuation Generator (_6/_7, _8/_9, ... from an aligned _4/_5 stitch)
=======================================================================================

The existing generators (`mxn_lh_continuation` / `mxn_rh_continuation`) build a
starting stitch (`_1`, `_2`, `_3`) and grow ONE continuation level onto it
(`_4`, `_5`) for a given rotation `k`, then align that level so the `_4/_5`
strands form parallel bands with even gaps.

This module grows the NEXT level, and any level after that.

The idea
--------
Once the `_4/_5` level has been aligned it is, geometrically, just another
stitch ring: `2n` strands forming a "horizontal" band and `2m` strands forming
a "vertical" band, each strand carrying an inner endpoint (its start, welded to
the level below) and an outer endpoint (its end, out on the perimeter).

That is exactly the shape of the `_2/_3` ring of a starting stitch.  So we
*rename* the aligned `_4/_5` strands into a virtual `_2/_3` starting stitch,
run the very same k-machinery on it (emoji pairing, H/V ordering, mask order,
parallel alignment), and rename the resulting virtual `_4/_5` back out as the
real `_6/_7`.

Level bookkeeping::

    level 1:  _2/_3  --k1-->  _4/_5
    level 2:  _4/_5  --k2-->  _6/_7
    level 3:  _6/_7  --k3-->  _8/_9
    ...
    level L:  _(2L)/_(2L+1)  --kL-->  _(2L+2)/_(2L+3)

Every level takes its own independent `k` (positive, zero or negative).

The virtual relabel
-------------------
Level `L`'s ring is ordered by level `L-1`'s k-based H/V order lists, which are
the spatial order across each band (H = top->bottom, V = left->right in the
un-rotated frame).  A canonical starting stitch has

    H order at k=0 = [1_2, 1_3, 2_2, 2_3, ...]      (LH)
    V order at k=0 = [(n+1)_3, (n+1)_2, ...]        (LH)

so pairing the previous level's ordered ring positionally against those
canonical lists gives the virtual name of every real strand.  With `k1 = 0` the
map is the identity, which is the sanity check that the relabel is the right
one.

Symbolic emoji pairing
----------------------
`compute_emoji_pairings()` in the engines derives the perimeter purely from
coordinates (side classification by `|dx| >= |dy|`, then sort by x/y).  That is
fine for the axis-aligned starting stitch but meaningless once a ring has been
rotated by an arbitrary k.  `build_symbolic_pairings()` below reproduces the
engine's answer exactly (verified against every `m,n in 1..4`, every k, both
directions, both hands) from labels alone, so it keeps working on rotated rings.

Usage
-----
    from mxn_continuation_next import generate_multi_level_json

    # k=1 for the _4/_5 level, k=-1 for the _6/_7 level
    json_text, report = generate_multi_level_json(m=2, n=2, ks=[1, -1], hand="lh")

CLI::

    python3 mxn_continuation_next.py --m 2 --n 2 --ks 1 -1 --hand lh --direction cw
"""

import argparse
import copy
import json
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import mxn_lh_continuation as _lh
import mxn_rh_continuation as _rh
from ui_utils import _get_active_strands


__all__ = [
    "generate_multi_level_json",
    "add_continuation_level",
    "align_continuation_level",
    "build_symbolic_pairings",
    "build_level_relabel",
    "canonical_orders",
    "level_suffixes",
    "get_engine",
]


# Geometry constants, matching the level-1 generators.
TAIL_OFFSET = 42.0 + 42.0 / 3.0   # 56.0 - how far past the paired point a tail runs
RETRACT = 52.0                    # how far a tail is pulled back before its continuation welds on
STRAND_WIDTH = 46

# ---------------------------------------------------------------------------
# Alignment search defaults
#
# These are the twist sheet's settings, taken from
# `.claude/skills/stitch-sheet/scripts/run_stitch.py`, so a level here is
# aligned exactly the way the published Twist Stitches reference aligns one.
# `first_strand` is the one that matters: it drives the gaps down toward the
# 56px floor the sheet identifies as the tightest legal twist, where
# `avg_gaussian` settles wider. On 2x2 k=1 LH: 56.43/56.41 against 56.84/56.81.
# ---------------------------------------------------------------------------
ANGLE_MODE = "first_strand"
ANGLE_STEP_DEGREES = 0.5
MAX_EXTENSION = 100.0
MAX_PAIR_EXTENSION = 200
# Finest extension grid first; the search costs (ext_max/step + 1) ** pairs, so
# coarsen only as far as the combo budget forces.
EXT_STEPS = [10, 20, 25, 40, 50, 100]
COMBO_BUDGET = 400_000
# Every ring past the first sits further out, so its arms need to reach further
# than the sheet's 200px ceiling. Levels >= 2 grow the ceiling while the winning
# combo is pinned against it, up to this cap.
#
# 1200 rather than something smaller because 2x2 LH k1=2 k2=1 is still in
# fallback (gap 806px) at 450 and still pinned at 680; it only reaches a real
# solution near 1000 (gap 56.42, variance 0.004). Raising the cap costs nothing
# on easier stitches, which stop at the first interior optimum and never see it.
EXTENSION_CEILING_CAP = 1200
EXTENSION_CEILING_TRIES = 6

# Where a new level's stubs are welded onto the ring below, and therefore what
# extension 0 means.
#
# "crossing" puts each stub's foot on its source arm's own outermost weave point
# — the crossings you can see in the stitch — instead of a flat 52px setback.
# Extension is then measured from a feature of the pattern rather than from a
# constant, and the search reaches the same places with far less of it: on 2x2
# LH k=[1,1] the second level settles at (90, 70) against (240, 230)/(290, 290),
# with gaps 56.58/56.60 against 56.66/56.03. Level 1 is unaffected — the engines
# build it themselves and nothing is welded onto it.
ANCHOR = "crossing"


def pick_extension_step(pairs, ext_max=MAX_PAIR_EXTENSION, budget=COMBO_BUDGET):
    """
    Finest extension-grid step whose combo count fits the budget — the twist
    sheet's `--ext-step auto` rule, so wide stitches coarsen the same way there
    and here.

    Returns (step, combos).
    """
    pairs = max(pairs, 1)
    for step in EXT_STEPS:
        combos = (ext_max // step + 1) ** pairs
        if combos <= budget:
            return step, combos
    step = EXT_STEPS[-1]
    return step, (ext_max // step + 1) ** pairs


# ---------------------------------------------------------------------------
# Engine selection
# ---------------------------------------------------------------------------

def get_engine(hand):
    """Return the LH or RH continuation module for `hand` ("lh" / "rh")."""
    hand = (hand or "lh").lower()
    if hand == "lh":
        return _lh
    if hand == "rh":
        return _rh
    raise ValueError(f"hand must be 'lh' or 'rh', got {hand!r}")


# Which endpoint of a ring strand sits on the TOP side and on the RIGHT side.
# Bottom is the complement of top, left the complement of right.
# These reproduce the side/endpoint layout that each engine's
# compute_emoji_pairings() derives from coordinates on a starting stitch.
_SIDE_ENDPOINT_RULES = {
    "lh": {"top": {"_3": "start", "_2": "end"}, "right": {"_2": "start", "_3": "end"}},
    "rh": {"top": {"_3": "end", "_2": "start"}, "right": {"_3": "end", "_2": "start"}},
}


def _other(endpoint_type):
    return "start" if endpoint_type == "end" else "end"


# ---------------------------------------------------------------------------
# Level bookkeeping
# ---------------------------------------------------------------------------

def level_suffixes(level):
    """
    Return (src_a, src_b, dst_a, dst_b) numeric suffixes for a 1-based level.

    level 1 -> (2, 3, 4, 5)   |   level 2 -> (4, 5, 6, 7)   |   level 3 -> (6, 7, 8, 9)
    """
    if level < 1:
        raise ValueError("level must be >= 1")
    return 2 * level, 2 * level + 1, 2 * level + 2, 2 * level + 3


def canonical_orders(hand, m, n):
    """
    The k=0 H and V order lists of a starting stitch — the canonical label
    sequence a rotated ring is relabelled onto.
    """
    engine = get_engine(hand)
    return (
        list(engine.get_horizontal_order_k(m, n, 0, "cw")),
        list(engine.get_vertical_order_k(m, n, 0, "cw")),
    )


# ---------------------------------------------------------------------------
# Symbolic (label-only) emoji pairing
# ---------------------------------------------------------------------------

def build_perimeter(hand, m, n):
    """
    Build the clockwise perimeter of a starting stitch as a list of
    (layer_name, endpoint_type) pairs, plus the per-side slices.

    Perimeter order is top -> right -> reversed(bottom) -> reversed(left),
    matching compute_emoji_pairings() in both engines.
    """
    h0, v0 = canonical_orders(hand, m, n)
    rules = _SIDE_ENDPOINT_RULES[hand.lower()]
    top_rule, right_rule = rules["top"], rules["right"]

    top = [(lbl, top_rule[lbl[-2:]]) for lbl in v0]
    bottom = [(lbl, _other(top_rule[lbl[-2:]])) for lbl in v0]
    right = [(lbl, right_rule[lbl[-2:]]) for lbl in h0]
    left = [(lbl, _other(right_rule[lbl[-2:]])) for lbl in h0]

    perimeter = top + right + list(reversed(bottom)) + list(reversed(left))
    return perimeter, top, right, bottom, left


def build_symbolic_pairings(hand, m, n, k, direction):
    """
    Emoji pairing for a starting stitch, expressed with labels instead of
    coordinates.

    Returns:
        dict {source_layer_name: (paired_layer_name, paired_endpoint_type)}

    Only END endpoints get an entry, because a continuation always welds onto
    its parent's end and runs to wherever the same emoji shows up.  This is a
    drop-in symbolic twin of `compute_emoji_pairings()` — same answer, but it
    survives a ring that has been rotated off the axes.
    """
    engine = get_engine(hand)
    perimeter, top, right, bottom, left = build_perimeter(hand, m, n)

    top_labels = list(range(len(top)))
    right_labels = list(range(len(top), len(top) + len(right)))
    bottom_labels = list(reversed(top_labels[:len(bottom)]))
    left_labels = list(reversed(right_labels[:len(left)]))
    base_labels = top_labels + right_labels + bottom_labels + left_labels

    rotated = engine.rotate_labels(base_labels, k, direction)

    pairings = {}
    for i, (layer, endpoint_type) in enumerate(perimeter):
        if endpoint_type != "end":
            continue
        for j, (other_layer, other_type) in enumerate(perimeter):
            if other_layer == layer and other_type == endpoint_type:
                continue
            if rotated[j] == rotated[i]:
                pairings[layer] = (other_layer, other_type)
                break
    return pairings


# ---------------------------------------------------------------------------
# Virtual relabel: previous level's ring -> canonical starting stitch
# ---------------------------------------------------------------------------

def build_level_relabel(hand, m, n, k_prev, direction, level):
    """
    Map the real strand names of level `level`'s source ring onto canonical
    starting-stitch names.

    `level` is the level being BUILT (>= 2); `k_prev` is the k that produced the
    source ring, i.e. the k of level `level - 1`.

    Returns:
        (real_to_virtual, virtual_to_real) dicts of layer_name -> layer_name.
    """
    engine = get_engine(hand)
    src_a, src_b, _, _ = level_suffixes(level)

    eff_dir = engine._get_effective_direction_for_max_k_special(m, n, k_prev, direction)
    h_prev = engine.get_horizontal_order_k(m, n, k_prev, eff_dir)
    v_prev = engine.get_vertical_order_k(m, n, k_prev, eff_dir)

    def to_source(label):
        set_part, suffix = label.split("_")
        return f"{set_part}_{src_a if suffix == '2' else src_b}"

    h_real = [to_source(lbl) for lbl in h_prev]
    v_real = [to_source(lbl) for lbl in v_prev]

    h_canon, v_canon = canonical_orders(hand, m, n)
    if len(h_real) != len(h_canon) or len(v_real) != len(v_canon):
        raise ValueError(
            f"ring size mismatch: H {len(h_real)} vs {len(h_canon)}, V {len(v_real)} vs {len(v_canon)}"
        )

    real_to_virtual = {}
    for real, virtual in list(zip(h_real, h_canon)) + list(zip(v_real, v_canon)):
        real_to_virtual[real] = virtual
    virtual_to_real = {v: r for r, v in real_to_virtual.items()}
    return real_to_virtual, virtual_to_real


def _identity_relabel(hand, m, n):
    """Level 1's relabel: the starting stitch already IS the canonical stitch."""
    h_canon, v_canon = canonical_orders(hand, m, n)
    ident = {lbl: lbl for lbl in h_canon + v_canon}
    return ident, dict(ident)


# ---------------------------------------------------------------------------
# Strand construction helpers
# ---------------------------------------------------------------------------

def _bump_suffix(layer_name, src_a, src_b, dst_a, dst_b):
    """`3_4` -> `3_6` when (src_a, dst_a) == (4, 6)."""
    set_part, suffix = layer_name.split("_")
    suffix = int(suffix)
    if suffix == src_a:
        return f"{set_part}_{dst_a}"
    if suffix == src_b:
        return f"{set_part}_{dst_b}"
    raise ValueError(f"{layer_name!r} is not a level source strand (_{src_a}/_{src_b})")


def _set_endpoints(strand, start, end):
    """Write start/end and keep control points + centre consistent."""
    strand["start"] = {"x": float(start["x"]), "y": float(start["y"])}
    strand["end"] = {"x": float(end["x"]), "y": float(end["y"])}
    strand["control_points"] = [dict(strand["start"]), dict(strand["end"])]
    strand["control_point_center"] = {
        "x": (strand["start"]["x"] + strand["end"]["x"]) / 2.0,
        "y": (strand["start"]["y"] + strand["end"]["y"]) / 2.0,
    }


def _retract_end(strand, distance):
    """Pull a tail's end back along its own axis, so the next level welds inside it."""
    dx = strand["end"]["x"] - strand["start"]["x"]
    dy = strand["end"]["y"] - strand["start"]["y"]
    length = math.hypot(dx, dy)
    if length <= 0.001 or distance <= 0.0:
        return
    nx, ny = dx / length, dy / length
    _set_endpoints(
        strand,
        strand["start"],
        {"x": strand["end"]["x"] - nx * distance, "y": strand["end"]["y"] - ny * distance},
    )


def _segment_crossing(a, b):
    """Parameter along `a` where it crosses `b`, or None if the segments miss."""
    x1, y1 = a["start"]["x"], a["start"]["y"]
    x2, y2 = a["end"]["x"], a["end"]["y"]
    x3, y3 = b["start"]["x"], b["start"]["y"]
    x4, y4 = b["end"]["x"], b["end"]["y"]
    den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(den) < 1e-9:
        return None
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den
    u = ((x1 - x3) * (y1 - y2) - (y1 - y3) * (x1 - x2)) / den
    return t if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0 else None


def crossing_anchors(source_by_name, fallback=RETRACT):
    """
    How far to pull each arm of a ring back so its end lands on its own OUTERMOST
    crossing with the other band — the ring's own weave points.

    This is the anchor the extension search should start from: extension 0 puts
    the new stub's foot on a crossing rather than at an arbitrary flat setback,
    so the extension the search reports is measured from a feature of the
    stitch instead of from a constant.

    The two bands are read off the geometry as the ring's two direction
    families, so this works at any level and for any k without relabel algebra.
    An arm that crosses nothing keeps the flat fallback.
    """
    names = list(source_by_name)
    if len(names) < 4 or len(names) % 2:
        return {}
    band_a, band_b, _ = _split_direction_families(source_by_name, names)

    anchors = {}
    for mine, others in ((band_a, band_b), (band_b, band_a)):
        for name in mine:
            arm = source_by_name[name]
            ts = [t for other in others
                  if (t := _segment_crossing(arm, source_by_name[other])) is not None]
            length = math.hypot(arm["end"]["x"] - arm["start"]["x"],
                                arm["end"]["y"] - arm["start"]["y"])
            anchors[name] = length * (1.0 - max(ts)) if ts else fallback
    return anchors


def _extend_past(start, target, extension):
    """Point `extension` px beyond `target` on the ray start -> target."""
    dx = target["x"] - start["x"]
    dy = target["y"] - start["y"]
    length = math.hypot(dx, dy)
    if length < 0.001:
        return {"x": target["x"], "y": target["y"]}
    return {
        "x": target["x"] + dx / length * extension,
        "y": target["y"] + dy / length * extension,
    }


def _make_attached(parent, layer_name, start, end):
    """Clone a parent strand's schema into a new AttachedStrand welded to its end."""
    strand = copy.deepcopy(parent)
    strand.pop("deletion_rectangles", None)
    strand.pop("first_selected_strand", None)
    strand.pop("second_selected_strand", None)
    strand["type"] = "AttachedStrand"
    strand["layer_name"] = layer_name
    strand["set_number"] = parent["set_number"]
    strand["has_circles"] = [True, False]
    strand["is_first_strand"] = False
    strand["is_start_side"] = False
    strand["attached_to"] = parent["layer_name"]
    strand["attachment_side"] = 1
    strand["angle"] = 0
    strand["length"] = 0
    _set_endpoints(strand, start, end)
    return strand


def _make_mask(v_strand, layer_name, set_number, first_strand, second_strand):
    """Clone a strand's schema into a MaskedStrand over the v x h crossing."""
    strand = copy.deepcopy(v_strand)
    strand.pop("attached_to", None)
    strand.pop("attachment_side", None)
    strand.pop("angle", None)
    strand.pop("length", None)
    strand["type"] = "MaskedStrand"
    strand["layer_name"] = layer_name
    strand["set_number"] = set_number
    strand["has_circles"] = [False, False]
    strand["is_first_strand"] = False
    strand["is_start_side"] = True
    strand["control_points"] = [None, None]
    strand["control_point_center"] = {
        "x": (v_strand["start"]["x"] + v_strand["end"]["x"]) / 2.0,
        "y": (v_strand["start"]["y"] + v_strand["end"]["y"]) / 2.0,
    }
    strand["deletion_rectangles"] = []
    strand["first_selected_strand"] = first_strand
    strand["second_selected_strand"] = second_strand
    return strand


# ---------------------------------------------------------------------------
# Growing one continuation level
# ---------------------------------------------------------------------------

def add_continuation_level(strands, m, n, k, direction, hand, level,
                           k_prev=None, retract=RETRACT, tail_offset=TAIL_OFFSET,
                           anchor=None, verbose=True):
    """
    Grow one continuation level onto an existing (ideally already aligned) ring.

    Args:
        strands:      full strand list; mutated in place for the source tails
                      (their ends get retracted) and returned extended.
        m, n:         grid size.
        k:            rotation for THIS level.
        direction:    "cw" / "ccw".
        hand:         "lh" / "rh".
        level:        1-based level being built (>= 2 here; level 1 is the
                      engines' own generate_json).
        k_prev:       the k that produced the source ring. Required for level >= 2.
        retract:      flat setback, used when `anchor="flat"` and as the fallback
                      for an arm that crosses nothing.
        tail_offset:  how far past the paired point the new tail runs.
        anchor:       `"crossing"` welds each new stub at its source arm's own
                      outermost weave point, so extension 0 sits on a crossing;
                      `"flat"` uses `retract` for every arm. Defaults to
                      `ANCHOR`, resolved at call time so it can be overridden.

    Returns:
        (all_strands, info) where info carries the relabel maps, the new strand
        list, the new mask list and the ordering used.
    """
    engine = get_engine(hand)
    if anchor is None:
        anchor = ANCHOR
    src_a, src_b, dst_a, dst_b = level_suffixes(level)
    src_suffixes = (f"_{src_a}", f"_{src_b}")

    if level == 1:
        real_to_virtual, virtual_to_real = _identity_relabel(hand, m, n)
    else:
        if k_prev is None:
            raise ValueError("k_prev is required for level >= 2")
        real_to_virtual, virtual_to_real = build_level_relabel(hand, m, n, k_prev, direction, level)

    source_by_name = {
        s["layer_name"]: s
        for s in strands
        if s.get("type") == "AttachedStrand" and s.get("layer_name", "").endswith(src_suffixes)
    }
    missing = sorted(set(real_to_virtual) - set(source_by_name))
    if missing:
        raise ValueError(f"level {level}: missing source strands {missing}")

    eff_dir = engine._get_effective_direction_for_max_k_special(m, n, k, direction)
    pairings = build_symbolic_pairings(hand, m, n, k, eff_dir)

    # The level-1 generator resolves every paired position against the ring as it
    # stands BEFORE any tail is pulled back, so snapshot first and retract after.
    # (A paired endpoint is always a `start`, never a retracted `end`, but the
    # snapshot keeps that from being load-bearing.)
    endpoints_before = {
        name: {"start": dict(s["start"]), "end": dict(s["end"])}
        for name, s in source_by_name.items()
    }
    anchors = crossing_anchors(source_by_name, retract) if anchor == "crossing" else {}
    for real_name in real_to_virtual:
        _retract_end(source_by_name[real_name], anchors.get(real_name, retract))

    note = None
    if level > 1 and k == m + n and n > m:
        note = (f"level {level} k={k} is the max-k special case: the bespoke "
                f"straight/side layout the level-1 generator uses for it is defined in "
                f"grid coordinates and is not reproduced on a rotated ring, so this "
                f"level uses the generic paired layout instead.")

    if verbose:
        print(f"\n=== LEVEL {level}: _{src_a}/_{src_b} --k={k} {direction}--> _{dst_a}/_{dst_b} ({hand.upper()}) ===")
        if eff_dir != direction:
            print(f"  max-k special case: using effective direction {eff_dir}")
        if note:
            print(f"  NOTE: {note}")
        print(f"  relabel (real -> virtual): {dict(sorted(real_to_virtual.items()))}")

    # --- weld a new tail onto every source tail -----------------------------
    new_strands_by_virtual = {}
    for real_name, virtual_name in real_to_virtual.items():
        parent = source_by_name[real_name]

        paired = pairings.get(virtual_name)
        if paired is None:
            raise ValueError(f"no pairing for virtual strand {virtual_name}")
        paired_virtual, paired_endpoint = paired
        paired_real = virtual_to_real[paired_virtual]
        target = endpoints_before[paired_real][paired_endpoint]

        start = dict(parent["end"])
        end = _extend_past(start, target, tail_offset)
        child_name = _bump_suffix(real_name, src_a, src_b, dst_a, dst_b)
        child = _make_attached(parent, child_name, start, end)
        new_strands_by_virtual[virtual_name] = child

        if verbose:
            print(f"  {child_name:6s} (from {real_name}, virt {virtual_name}) "
                  f"-> pairs with {paired_real}.{paired_endpoint} ({paired_virtual}): "
                  f"({end['x']:.1f}, {end['y']:.1f})")

    # --- order them the way the engine orders a continuation ----------------
    v_order_virtual = engine.get_vertical_order_k(m, n, k, eff_dir)
    h_order_virtual = engine.get_horizontal_order_k(m, n, k, eff_dir)
    ordered_virtual = list(v_order_virtual) + list(h_order_virtual)
    new_strands = [new_strands_by_virtual[v] for v in ordered_virtual if v in new_strands_by_virtual]

    if verbose:
        print(f"  vertical order  : {list(v_order_virtual)} -> "
              f"{[new_strands_by_virtual[v]['layer_name'] for v in v_order_virtual]}")
        print(f"  horizontal order: {list(h_order_virtual)} -> "
              f"{[new_strands_by_virtual[v]['layer_name'] for v in h_order_virtual]}")

    # --- masks over the new crossings ---------------------------------------
    mask_order = engine.get_mask_order_k(m, n, k, eff_dir)
    new_masks = []
    for entry in mask_order:
        parts = entry.split("_")
        if len(parts) != 4:
            continue
        v_virtual = f"{parts[0]}_{parts[1]}"
        h_virtual = f"{parts[2]}_{parts[3]}"
        v_strand = new_strands_by_virtual.get(v_virtual)
        h_strand = new_strands_by_virtual.get(h_virtual)
        if v_strand is None or h_strand is None:
            continue
        new_masks.append(_make_mask(
            v_strand,
            f"{v_strand['layer_name']}_{h_strand['layer_name']}",
            int(f"{v_strand['set_number']}{h_strand['set_number']}"),
            v_strand["layer_name"],
            h_strand["layer_name"],
        ))

    if verbose:
        print(f"  masks ({len(new_masks)}): {[mk['layer_name'] for mk in new_masks]}")

    all_strands = list(strands) + new_strands + new_masks
    info = {
        "level": level,
        "k": k,
        "k_prev": k_prev,
        "effective_direction": eff_dir,
        "real_to_virtual": real_to_virtual,
        "virtual_to_real": virtual_to_real,
        "new_strands": new_strands,
        "new_masks": new_masks,
        "note": note,
        "vertical_order": [new_strands_by_virtual[v]["layer_name"] for v in v_order_virtual],
        "horizontal_order": [new_strands_by_virtual[v]["layer_name"] for v in h_order_virtual],
    }
    return all_strands, info


# ---------------------------------------------------------------------------
# Aligning one continuation level
# ---------------------------------------------------------------------------

def _build_virtual_view(strands, level_info, level):
    """
    Build the deep-copied `_2/_3 + _4/_5` strand list the alignment engine
    expects, and the map back to the real strands.
    """
    src_a, src_b, dst_a, dst_b = level_suffixes(level)
    real_to_virtual = level_info["real_to_virtual"]
    by_name = {s["layer_name"]: s for s in strands}

    virtual_list = []
    back_map = {}  # virtual layer_name -> real strand dict

    for real_name, virtual_name in real_to_virtual.items():
        virtual_set = int(virtual_name.split("_")[0])

        source = by_name[real_name]
        v_source = copy.deepcopy(source)
        v_source["layer_name"] = virtual_name
        v_source["set_number"] = virtual_set
        virtual_list.append(v_source)
        back_map[virtual_name] = source

        child_real = _bump_suffix(real_name, src_a, src_b, dst_a, dst_b)
        child_virtual = _bump_suffix(virtual_name, 2, 3, 4, 5)
        child = by_name.get(child_real)
        if child is None:
            continue
        v_child = copy.deepcopy(child)
        v_child["layer_name"] = child_virtual
        v_child["set_number"] = virtual_set
        v_child["attached_to"] = virtual_name
        virtual_list.append(v_child)
        back_map[child_virtual] = child

    return virtual_list, back_map


def _copy_geometry(src, dst):
    dst["start"] = copy.deepcopy(src["start"])
    dst["end"] = copy.deepcopy(src["end"])
    if src.get("control_points") is not None:
        dst["control_points"] = copy.deepcopy(src["control_points"])
    if src.get("control_point_center") is not None:
        dst["control_point_center"] = copy.deepcopy(src["control_point_center"])


def _is_pinned(result, ceiling):
    """True when the winning combo sits on the edge of the extension grid."""
    extensions = result.get("pair_extensions") or ()
    if not extensions:
        return False
    return max(extensions) >= ceiling


def _extension_ceilings(base, cap=EXTENSION_CEILING_CAP, growth=1.5,
                        tries=EXTENSION_CEILING_TRIES):
    """Ceiling schedule: the base, then 1.5x each time, stopping at the cap."""
    ceilings = []
    ceiling = int(base)
    for _ in range(max(tries, 1)):
        ceilings.append(ceiling)
        if ceiling >= cap:
            break
        ceiling = min(int(round(ceiling * growth / 10.0)) * 10, cap)
    return ceilings


# ---------------------------------------------------------------------------
# Direction-family rescue
#
# The engine splits a ring's arms into its two search groups by k-based NAME
# order, and then asks each group to settle on one shared heading. That holds
# while a group's arms arrive close to parallel, which is what happens at
# level 1: measured across every k on 2x2 and 3x3, a level-1 group's arms span
# only 1.03-4.70 degrees.
#
# It stops holding deeper in. At level 3 of 2x2 `ks = [1, 1, -1]` the name-order
# H group spans 55.3 degrees and the V group 49.0; at `ks = [1, 1, 1]` both span
# ~88. Those groups have no valid configuration at ANY heading and ANY extension
# — not a search failure, an impossible request. The arms are still perfectly
# pairable (every outside-in pair is antiparallel to 0.00 deg); they have simply
# stopped lining up with the name order, so each group ends up holding one pair
# from each direction family.
#
# Re-splitting the same arms by their actual heading recovers two families of
# the level-1 shape and the search succeeds again.
#
# The window has to grow with them. `first_strand` mode searches the first arm's
# heading +-20 deg, recentred at every extension combo. Level 1 never needs more
# than 7.21 of that 20. A regrouped 38-degree family needs 23.08 deg before any
# valid heading comes into range, and 27.6 to reach the good one, so all 441
# sampled extension combos are unreachable inside +-20. Hence a window sized to
# the family's own fan rather than a constant, and spanning both directions
# along the family line, since a family's best heading can sit antiparallel to
# its reference.
# ---------------------------------------------------------------------------
FAMILY_MIN_HALF_WINDOW = 20.0     # never search narrower than the engine's default


def _line_angle(strand):
    """Heading of a strand as an undirected line, in [0, 180)."""
    dx = strand["end"]["x"] - strand["start"]["x"]
    dy = strand["end"]["y"] - strand["start"]["y"]
    return math.degrees(math.atan2(dy, dx)) % 180.0


def _line_separation(a, b):
    """Angle between two undirected lines, in [0, 90]."""
    d = abs(a - b) % 180.0
    return min(d, 180.0 - d)


def _line_mean(lines):
    """Circular mean of undirected lines (doubled-angle averaging)."""
    doubled = [math.radians(2.0 * L) for L in lines]
    mx = sum(math.cos(a) for a in doubled) / len(doubled)
    my = sum(math.sin(a) for a in doubled) / len(doubled)
    return math.degrees(math.atan2(my, mx)) / 2.0


def _line_fan(lines):
    """Widest separation between any two lines in a group."""
    return max((_line_separation(a, b) for a in lines for b in lines), default=0.0)


def _split_direction_families(by_name, names):
    """
    Split arms into two equal direction families, minimising the wider fan.

    Each arm in turn seeds a candidate split: rank the others by how close their
    line is to the seed's and cut in half. The split whose worse family is
    narrowest wins. Within a family the arms are ordered across the family line,
    which is the spatial order the engine's outside-in pairing expects.

    Returns (family_a, family_b, worst_fan) with each family a list of names.
    """
    lines = {nm: _line_angle(by_name[nm]) for nm in names}
    half = len(names) // 2
    best = None
    for seed in names:
        ranked = sorted(names, key=lambda nm: _line_separation(lines[nm], lines[seed]))
        groups = (ranked[:half], ranked[half:])
        worst = max(_line_fan([lines[nm] for nm in g]) for g in groups)
        if best is None or worst < best[0]:
            best = (worst, groups)

    worst_fan, groups = best
    ordered = []
    for group in groups:
        mean = _line_mean([lines[nm] for nm in group])
        ux, uy = math.cos(math.radians(mean)), math.sin(math.radians(mean))
        # signed distance across the family line
        key = {nm: -by_name[nm]["start"]["x"] * uy + by_name[nm]["start"]["y"] * ux
               for nm in group}
        ordered.append(sorted(group, key=lambda nm: key[nm]))
    return ordered[0], ordered[1], worst_fan


def _family_window(by_name, family):
    """
    Absolute angle range to search for one direction family.

    Centred on the family's own line, half-width the family's fan but never
    below the engine's default 20 deg, and extended by 180 so both directions
    along that line are reachable. A custom range is static (the engine only
    recentres the automatic `first_strand` window per extension combo), so this
    has to cover the answer outright.
    """
    lines = [_line_angle(by_name[nm]) for nm in family]
    mean = _line_mean(lines)
    half = max(FAMILY_MIN_HALF_WINDOW, _line_fan(lines))
    return mean - half, mean + 180.0 + half


def _ring_crossings(virtual_list):
    """
    Score the new ring by its weave, as `across - within`.

    This is the one measure that catches a collapsed level. The gap test looks
    inside a band and reads clean on a ring that has folded over — measured on
    2x2 ks=[1,1,1], where the third level reports gaps of 56.47/56.60, as tight
    as anything in the working range, on a ring that is not a weave.

    A well-formed m x n ring has exactly (2m)(2n) crossings BETWEEN its two
    bands and NONE inside either one, because a band's arms are parallel. Both
    halves matter: counting only the total lets a ring reach the right number
    through the wrong pairs. Measured on 2x2 ks=[1,1,-1] at level 3, which hits
    16 crossings while `3_8` crosses `3_9` and `4_8` crosses `4_9` — same-set
    arms, which in a real stitch never meet. Masks are laid across the bands, so
    a ring like that also masks the wrong pairs.

    Subtracting the within-band crossings keeps one number to maximise while
    making a mis-formed ring score strictly below a clean one of the same total.
    """
    arms = [s for s in virtual_list
            if s.get("type") == "AttachedStrand"
            and s.get("layer_name", "").endswith(("_4", "_5"))]
    if len(arms) < 4:
        return 0
    by_name = {s["layer_name"]: s for s in arms}
    band_a, band_b, _ = _split_direction_families(by_name, list(by_name))
    band_a = set(band_a)

    across = within = 0
    for i, a in enumerate(arms):
        for b in arms[i + 1:]:
            if _segment_crossing(a, b) is None:
                continue
            if (a["layer_name"] in band_a) == (b["layer_name"] in band_a):
                within += 1
            else:
                across += 1
    return across - within


def _plan_family_rescue(virtual_list, h_order, v_order):
    """
    Work out the direction-family split for a level, from the ring as it stands
    before any alignment runs.

    Returns None when the arms cannot be regrouped (odd counts, or the two
    groups are not the same size), or when the split is no better than the
    k-based one — in that case there is nothing to rescue.
    """
    if len(h_order) != len(v_order) or len(h_order) < 2:
        return None

    by_name = {s["layer_name"]: s for s in virtual_list}
    names = [nm for nm in list(h_order) + list(v_order) if nm in by_name]
    if len(names) != len(h_order) + len(v_order):
        return None

    fam_a, fam_b, worst_fan = _split_direction_families(by_name, names)
    k_fan = max(_line_fan([_line_angle(by_name[nm]) for nm in group])
                for group in (h_order, v_order))
    if worst_fan >= k_fan:
        return None

    # Keep the family that most resembles the k-based H group on the H side, so
    # the two searches stay in their usual roles.
    h_set = set(h_order)
    if len(h_set & set(fam_b)) > len(h_set & set(fam_a)):
        fam_a, fam_b = fam_b, fam_a

    return {
        "h_order": fam_a,
        "v_order": fam_b,
        "h_window": _family_window(by_name, fam_a),
        "v_window": _family_window(by_name, fam_b),
        "family_fan": worst_fan,
        "k_fan": k_fan,
    }


def _attempt_rank(entry):
    """
    Rank fallback candidates when no ceiling produced an interior optimum:
    a real solution beats a fallback, then the evenest gaps, then the
    shortest arms (a bigger stitch for the same evenness is not a better one).
    """
    result = entry["result"]
    return (
        0 if result.get("success") else 1,
        result.get("gap_variance", float("inf")),
        max(result.get("pair_extensions") or (0,)),
    )


def _mask_pairs(v_order, h_order, k):
    """
    Which crossings carry a mask, for bands given in spatial order.

    This is `get_mask_order_k`'s rule, restated so it can be applied to bands the
    engine did not name: every other vertical arm takes the even horizontals and
    the rest take the odd ones, with the phase set by the parity of k. Only half
    the crossings get a mask; the others come out right from draw order alone.
    """
    h_even, h_odd = list(h_order[0::2]), list(h_order[1::2])
    pairs = []
    for index, v in enumerate(v_order):
        if k % 2 == 1:
            target = h_even if index % 2 == 0 else h_odd
        else:
            target = h_odd if index % 2 == 0 else h_even
        pairs.extend((v, h) for h in target)
    return pairs


def _order_disagreement(candidate, reference):
    """
    How far a band's order departs from the engine's, as a count of swapped
    neighbours over the names the two share.

    Zero means the candidate walks the band the same way the engine does.
    """
    rank = {name: i for i, name in enumerate(reference)}
    shared = [rank[n] for n in candidate if n in rank]
    return sum(1 for i, a in enumerate(shared) for b in shared[i + 1:] if a > b)


def _relay_masks(masks, virtual_list, back_map, plan, k, h_order, v_order, verbose):
    """
    Re-lay the masks across the bands the ring actually has.

    `add_continuation_level` builds masks before the level is aligned, pairing
    them by the engine's k-based H/V split. When the direction-family rescue
    then aligns the ring on a different split, half those pairs no longer meet:
    measured on 2x2 ks=[1,1,-1] at level 3, where the ring is a clean 16/16
    weave but 4 of its 8 masks name two arms that never cross.

    A mask's identity is the pair it covers, so re-pointing it is the repair.
    Band roles and spatial order are conventions we cannot read off the families
    directly, so every combination is tried and the one that puts all eight
    masks on real crossings wins. If none does, the masks are left alone.
    """
    arms = {s["layer_name"]: s for s in virtual_list
            if s.get("type") == "AttachedStrand"
            and s["layer_name"].endswith(("_4", "_5"))}
    names = list(arms)
    crossing = {frozenset((a, b))
                for i, a in enumerate(names) for b in names[i + 1:]
                if _segment_crossing(arms[a], arms[b]) is not None}
    real_to_virtual = {strand["layer_name"]: virtual
                       for virtual, strand in back_map.items()}

    def stray(pairs):
        return sum(1 for v, h in pairs if frozenset((v, h)) not in crossing)

    current = [(real_to_virtual.get(m.get("first_selected_strand")),
                real_to_virtual.get(m.get("second_selected_strand")))
               for m in masks]
    if all(v and h for v, h in current) and not stray(current):
        return False

    # Several arrangements put every mask on a real crossing while covering a
    # DIFFERENT half of the checkerboard, which inverts who goes over at those
    # crossings. Landing on crossings is necessary, not sufficient. So rank by
    # how closely each one walks the bands the way the engine walks its own —
    # that is what carries the over-and-under convention from level 1 outward.
    best = None
    for v_band, h_band, roles in ((plan["v_order"], plan["h_order"], "as planned"),
                                  (plan["h_order"], plan["v_order"], "roles swapped")):
        for v_rev in (False, True):
            for h_rev in (False, True):
                v_seq = list(reversed(v_band)) if v_rev else list(v_band)
                h_seq = list(reversed(h_band)) if h_rev else list(h_band)
                pairs = _mask_pairs(v_seq, h_seq, k)
                if len(pairs) != len(masks):
                    continue
                score = (stray(pairs),
                         _order_disagreement(v_seq, v_order)
                         + _order_disagreement(h_seq, h_order),
                         roles != "as planned")
                if best is None or score < best[0]:
                    best = (score, pairs, roles, v_rev, h_rev)

    if best is None or best[0][0]:
        if verbose:
            print(f"    masks: no re-pairing puts them all on crossings "
                  f"({'none fit' if best is None else str(best[0][0]) + ' stray'}), "
                  f"leaving them")
        return False

    (_stray, disagree, _swapped), pairs, roles, v_rev, h_rev = best
    for mask, (v_virtual, h_virtual) in zip(masks, pairs):
        v_real = back_map.get(v_virtual)
        h_real = back_map.get(h_virtual)
        if v_real is None or h_real is None:
            return False
        mask["first_selected_strand"] = v_real["layer_name"]
        mask["second_selected_strand"] = h_real["layer_name"]
        mask["layer_name"] = f"{v_real['layer_name']}_{h_real['layer_name']}"
        mask["set_number"] = int(f"{v_real['set_number']}{h_real['set_number']}")
        # A mask paints the strand it covers for, so it has to carry that
        # strand's colour. `_make_mask` cloned it from whichever arm the k-based
        # pairing named, and re-pointing without this leaves the covered patch
        # painted in the old arm's colour.
        if v_real.get("color") is not None:
            mask["color"] = copy.deepcopy(v_real["color"])
    if verbose:
        print(f"    masks: re-laid across the direction families, {len(masks)} on "
              f"real crossings ({roles}"
              f"{', V reversed' if v_rev else ''}{', H reversed' if h_rev else ''}, "
              f"{disagree} order disagreements with the engine)")
    return True


def _pinned_search(align, window, target, pairs, verbose, label):
    """
    Run one group's alignment but return the configuration at a GIVEN extension
    combo rather than the one the search would have chosen.

    The engine already reports every valid configuration it finds through
    `on_config_callback`, so this listens for the combo we want and keeps its
    best-variance instance. The grid is sized to contain the target exactly: a
    step that divides every value in it, and a ceiling that reaches the largest.

    Returns (result, settings), or (None, None) if that combo is never valid.
    """
    target = tuple(int(v) for v in target)
    step = math.gcd(*(list(target) + [0])) or 10
    ceiling = max(max(target), step)

    grabbed = {}

    def grab(_angle_deg, extensions, result, *_rest):
        if tuple(extensions) != target or not result.get("valid"):
            return
        best = grabbed.get("r")
        if best is None or result.get("gap_variance", 0) < best.get("gap_variance", 0):
            grabbed["r"] = copy.deepcopy(result)

    align(ceiling, step, window, grab)
    if "r" not in grabbed:
        if verbose:
            print(f"    {label}: {target} is never a valid configuration here")
        return None, None

    result = dict(grabbed["r"])
    result.update({
        "success": True,
        "angle_degrees": math.degrees(result["angle"]),
        "pair_extensions": target,
    })
    return result, {"ceiling": ceiling, "step": step, "pairs": pairs,
                    "combos": 1, "attempts": 1, "pinned": False,
                    "mirrored": True}


def _mirror_extensions(attempt, chosen, plan, expected, sides, verbose):
    """
    Give both bands the same extensions, copied from whichever one sits closer
    to its anchor.

    A square stitch should be symmetric, and on 2x2 it comes out that way on its
    own — every level lands on the same combo for H and V. On 3x3 the two bands
    disagree, and the band that stayed closest to the purple points is the one
    that looks right; the other has wandered. So copy the near band's combo onto
    the far one and keep the result if the ring is no worse.

    `sides` picks which levels this applies to. Returns the mirrored attempt, or
    None to keep what we had.
    """
    if not sides:
        return None
    h_ext = tuple(chosen["h"].get("pair_extensions") or ())
    v_ext = tuple(chosen["v"].get("pair_extensions") or ())
    if not h_ext or not v_ext or h_ext == v_ext or len(h_ext) != len(v_ext):
        return None
    if not (chosen["h"].get("success") and chosen["v"].get("success")):
        return None

    # The near band -- the one that had to reach least -- donates first. Its combo
    # is not always legal on the other band, though: measured on 3x3 ks=[1,1,-1]
    # at level 3, where H's (10, 30, 20) is never a valid configuration for V. So
    # if the near band cannot donate, the far band tries, since a symmetric
    # stitch on the far band's combo still beats two bands that disagree.
    if max(v_ext) <= max(h_ext):
        order = [(v_ext, (v_ext, None), "V -> H"), (h_ext, (None, h_ext), "H -> V")]
    else:
        order = [(h_ext, (None, h_ext), "H -> V"), (v_ext, (v_ext, None), "V -> H")]

    if verbose:
        print(f"    bands disagree: H{h_ext} V{v_ext} — trying "
              f"{' then '.join(side for _d, _f, side in order)}")
    for donor, force, side in order:
        alt = attempt(plan, force)
        if alt is None:
            if verbose:
                print(f"    {side} {donor}: never a valid configuration on the "
                      f"other band")
            continue
        if alt["crossings"] < chosen["crossings"]:
            if verbose:
                print(f"    {side} {donor}: ring drops to {alt['crossings']}"
                      f"/{expected}, rejected")
            continue
        if verbose:
            print(f"    {side} {donor}: ring {alt['crossings']}/{expected}, "
                  f"both bands on {donor}")
        return alt
    if verbose:
        print(f"    neither band can donate, keeping H{h_ext} V{v_ext}")
    return None


def _search_group(run, pairs, base_ceiling, fixed_step, escalate, verbose, label):
    """
    Run one group's alignment, growing the extension ceiling while the winner
    is pinned against it.

    A pinned winner means the search wanted longer arms than the grid allowed,
    so its "best" is an artefact of the bound, not an optimum. Growing until the
    optimum is interior fixes that.

    We stop at the FIRST interior success rather than continuing to grow,
    because an over-wide grid lets a degenerate long-armed solution win the
    variance tie-break. Measured on 2x2 LH k1=1 k2=1, where 300px already gives
    an interior optimum: a 1000px ceiling trades 240px arms for 1000px ones to
    move the gap 56.66 -> 56.42. That is a far bigger, floppier stitch for a
    quarter of a pixel, so the schedule must not chase it.

    If every ceiling stays pinned, fall back to the best attempt by
    `_attempt_rank` rather than blindly taking the widest one.

    Returns (result, settings).
    """
    ceilings = _extension_ceilings(base_ceiling) if escalate else [int(base_ceiling)]

    attempts = []
    for index, ceiling in enumerate(ceilings):
        if fixed_step is None:
            step, combos = pick_extension_step(pairs, ceiling)
        else:
            step = int(fixed_step)
            combos = (ceiling // step + 1) ** pairs

        result = run(ceiling, step)
        settings = {"ceiling": ceiling, "step": step, "pairs": pairs,
                    "combos": combos, "attempts": index + 1}

        if not (result.get("success") or result.get("is_fallback")):
            if verbose:
                print(f"    {label}: ceiling {ceiling} -> no solution, growing")
            attempts.append({"result": result, "settings": settings})
            continue

        attempts.append({"result": result, "settings": settings})
        pinned = _is_pinned(result, ceiling)

        if result.get("success") and not pinned:
            if verbose and index:
                print(f"    {label}: ceiling {ceiling} -> interior optimum "
                      f"{result.get('pair_extensions')}, accepted")
            settings["pinned"] = False
            return result, settings

        if verbose:
            state = "pinned at" if pinned else "only a fallback at"
            print(f"    {label}: ceiling {ceiling} -> {state} "
                  f"{result.get('pair_extensions')}, growing")

    usable = [a for a in attempts
              if a["result"].get("success") or a["result"].get("is_fallback")]
    chosen = min(usable, key=_attempt_rank) if usable else attempts[-1]
    chosen["settings"]["pinned"] = _is_pinned(chosen["result"], chosen["settings"]["ceiling"])
    if verbose:
        print(f"    {label}: no interior optimum in {len(ceilings)} ceilings, "
              f"keeping ceiling {chosen['settings']['ceiling']}")
    return chosen["result"], chosen["settings"]


def align_continuation_level(strands, m, n, k, direction, hand, level, level_info,
                             angle_step_degrees=ANGLE_STEP_DEGREES,
                             max_extension=MAX_EXTENSION,
                             strand_width=STRAND_WIDTH,
                             max_pair_extension=MAX_PAIR_EXTENSION,
                             pair_extension_step=None, use_gpu=False,
                             angle_mode=ANGLE_MODE, escalate_extension=None,
                             mirror_sides=None, verbose=True):
    """
    Run the engine's parallel alignment on one continuation level.

    The level's source ring is presented to the engine as `_2/_3` and the new
    ring as `_4/_5`, so the existing (tested) search runs unchanged.  Results
    are copied back onto the real strands afterwards — both the new tails and
    any extension the search applied to the source tails.

    Defaults are the twist sheet's (`run_stitch.py`), including its per-group
    `--ext-step auto` rule: `pair_extension_step=None` picks the finest grid
    each group's pair count can afford. Pass a number to pin the grid.

    `escalate_extension` grows the extension ceiling while the winning combo is
    pinned against it (see `_search_group`). It defaults to ON for level >= 2
    and OFF for level 1: every ring past the first sits further out and needs
    longer arms than the sheet's 200px ceiling allows, while level 1 must keep
    reproducing the published twist exactly. Pass True/False to force it.

    Returns:
        dict with the horizontal and vertical alignment results, plus the
        search settings actually used.
    """
    engine = get_engine(hand)
    virtual_list, back_map = _build_virtual_view(strands, level_info, level)

    if escalate_extension is None:
        escalate_extension = level >= 2
    if mirror_sides is None:
        # Level 1 is the published twist and must reproduce exactly; from the
        # second level on, a square stitch should be symmetric.
        mirror_sides = level >= 2 and m == n

    # Group sizes come from the engine's own k-based sets, exactly as the twist
    # sheet sizes its search.
    _, h_order, _, v_order = engine._build_k_based_strand_sets(m, n, k, direction)
    h_pairs = max((len(h_order) + 1) // 2, 1)
    v_pairs = max((len(v_order) + 1) // 2, 1)

    if verbose:
        print(f"\n--- LEVEL {level} alignment (k={k}, {direction}, mode={angle_mode}, "
              f"escalate={escalate_extension}) ---")

    # Planned from the untouched ring, so both searches in an attempt agree on the
    # split even though the H search moves arms before V runs.
    rescue = _plan_family_rescue(virtual_list, h_order, v_order)
    expected_crossings = len(h_order) * len(v_order)

    def attempt(plan, force=(None, None)):
        """
        Align the level once, either with the engine's k-based groups (plan None)
        or with the direction families, and report the ring it produced.

        `force` pins one side's extension combo instead of letting it choose —
        see `_mirror_extensions`.
        """
        working, back = _build_virtual_view(strands, level_info, level)

        def align_h(ceiling, step, window, grab=None):
            lo, hi = window if window else (None, None)
            return engine.align_horizontal_strands_parallel(
                working, n,
                angle_step_degrees=angle_step_degrees,
                max_extension=max_extension,
                strand_width=strand_width,
                custom_angle_min=lo, custom_angle_max=hi,
                on_config_callback=grab,
                max_pair_extension=ceiling,
                pair_extension_step=step,
                m=m, k=k, direction=direction,
                use_gpu=use_gpu,
                angle_mode=angle_mode,
            )

        def align_v(ceiling, step, window, grab=None):
            lo, hi = window if window else (None, None)
            return engine.align_vertical_strands_parallel(
                working, n, m,
                angle_step_degrees=angle_step_degrees,
                max_extension=max_extension,
                strand_width=strand_width,
                custom_angle_min=lo, custom_angle_max=hi,
                on_config_callback=grab,
                max_pair_extension=ceiling,
                pair_extension_step=step,
                k=k, direction=direction,
                use_gpu=use_gpu,
                angle_mode=angle_mode,
            )

        if plan is None:
            orders = (list(h_order), list(v_order))
            windows = (None, None)
            restore = None
        else:
            orders = (plan["h_order"], plan["v_order"])
            windows = (plan["h_window"], plan["v_window"])
            forced = (set(orders[0]), list(orders[0]), set(orders[1]), list(orders[1]))
            restore = engine._build_k_based_strand_sets
            engine._build_k_based_strand_sets = lambda *a, **kw: forced

        try:
            results, settings = [], []
            for align, order, window, pin, label in (
                    (align_h, orders[0], windows[0], force[0], "H"),
                    (align_v, orders[1], windows[1], force[1], "V")):
                pairs = max((len(order) + 1) // 2, 1)
                if pin is None:
                    res, sett = _search_group(
                        lambda ceiling, step, _a=align, _w=window: _a(ceiling, step, _w),
                        pairs, max_pair_extension, pair_extension_step,
                        escalate_extension, verbose,
                        label if plan is None else f"{label}*")
                else:
                    res, sett = _pinned_search(align, window, pin, pairs, verbose, label)
                    if res is None:
                        return None
                if plan is not None:
                    sett["rescued"] = True
                    sett["family"] = list(order)
                    sett["window"] = [window[0], window[1]]
                if res.get("success") or res.get("is_fallback"):
                    working = engine.apply_parallel_alignment(working, res)
                results.append(res)
                settings.append(sett)
        finally:
            if restore is not None:
                engine._build_k_based_strand_sets = restore

        return {"h": results[0], "v": results[1],
                "h_settings": settings[0], "v_settings": settings[1],
                "virtual_list": working, "back_map": back,
                "crossings": _ring_crossings(working)}

    chosen = attempt(None)
    plan_used = None
    if rescue is not None and chosen["crossings"] < expected_crossings:
        if verbose:
            print(f"    k-based groups (fan {rescue['k_fan']:.1f} deg) gave a ring with "
                  f"{chosen['crossings']}/{expected_crossings} crossings — retrying on "
                  f"the direction families (fan {rescue['family_fan']:.1f} deg)")
        alt = attempt(rescue)
        if alt["crossings"] > chosen["crossings"]:
            if verbose:
                print(f"    direction families gave {alt['crossings']}"
                      f"/{expected_crossings} — taking them")
            chosen, plan_used = alt, rescue
        elif verbose:
            print(f"    direction families gave {alt['crossings']}"
                  f"/{expected_crossings} — keeping the k-based result")

    mirrored = _mirror_extensions(attempt, chosen, plan_used, expected_crossings,
                                  mirror_sides, verbose)
    if mirrored is not None:
        chosen = mirrored

    h_result, v_result = chosen["h"], chosen["v"]
    h_settings, v_settings = chosen["h_settings"], chosen["v_settings"]
    virtual_list, back_map = chosen["virtual_list"], chosen["back_map"]

    for v_strand in virtual_list:
        real = back_map.get(v_strand["layer_name"])
        if real is not None:
            _copy_geometry(v_strand, real)

    # A regrouped ring has different bands from the ones the masks were built
    # against, so re-pair them before they take their geometry.
    relaid = False
    if plan_used is not None and level_info["new_masks"]:
        relaid = _relay_masks(level_info["new_masks"], virtual_list, back_map,
                              plan_used, k, list(h_order), list(v_order), verbose)

    # Masks copy the geometry of the vertical strand they sit on.
    by_name = {s["layer_name"]: s for s in strands}
    for mask in level_info["new_masks"]:
        owner = by_name.get(mask.get("first_selected_strand"))
        if owner is not None:
            mask["start"] = copy.deepcopy(owner["start"])
            mask["end"] = copy.deepcopy(owner["end"])
            mask["control_point_center"] = {
                "x": (owner["start"]["x"] + owner["end"]["x"]) / 2.0,
                "y": (owner["start"]["y"] + owner["end"]["y"]) / 2.0,
            }

    if verbose:
        print(f"  H: {_result_line(h_result)}")
        print(f"  V: {_result_line(v_result)}")

    return {
        "horizontal": h_result,
        "vertical": v_result,
        "search": {
            "angle_step": angle_step_degrees,
            "angle_mode": angle_mode,
            "escalated": escalate_extension,
            "masks_relaid": relaid,
            "horizontal": h_settings,
            "vertical": v_settings,
        },
    }


def _result_line(result):
    if result.get("preserve_continuation"):
        return f"preserved ({result.get('message', '')})"
    state = "ok" if result.get("success") else ("fallback" if result.get("is_fallback") else "FAILED")
    if result.get("success") or result.get("is_fallback"):
        return (f"{state} angle={result.get('angle_degrees', 0):.2f}° "
                f"avg_gap={result.get('average_gap', 0):.2f}px "
                f"exts={result.get('pair_extensions')}")
    return f"{state} - {result.get('message', '')}"


# ---------------------------------------------------------------------------
# Full multi-level pipeline
# ---------------------------------------------------------------------------

def _history_json(strands):
    """Wrap a strand list in the OpenStrandStudio history envelope."""
    history = {
        "type": "OpenStrandStudioHistory",
        "version": 1,
        "current_step": 2,
        "max_step": 2,
        "states": [],
    }
    for step in (1, 2):
        history["states"].append({
            "step": step,
            "data": {
                "strands": strands,
                "groups": {},
                "selected_strand_name": None,
                "locked_layers": [],
                "lock_mode": False,
                "shadow_enabled": False,
                "show_control_points": step == 1,
                "shadow_overrides": {},
            },
        })
    return json.dumps(history, indent=2)


def _snapshot_json(strands):
    """Deep-copy the current strand list into a self-contained, re-indexed document."""
    snapshot = copy.deepcopy(strands)
    for idx, strand in enumerate(snapshot):
        strand["index"] = idx
    return _history_json(snapshot)


def build_starting_stitch_json(m, n, hand, reference_strands=None):
    """
    The starting stitch on its own — `_1`/`_2`/`_3` plus their `_2 x _3` masks,
    with full-length tails (no continuation welded on yet).

    This is the stretch generator's own output, which is the same base geometry
    the continuation generators build on. `reference_strands` recolours it to
    match another run's per-set colours, so a stage sequence keeps one palette
    (set colours above set 2 are randomised on every generate call).
    """
    if hand == "lh":
        import mxn_lh_strech as stretch
    else:
        import mxn_rh_stretch as stretch

    data = json.loads(stretch.generate_json(m, n))
    strands = _get_active_strands(data)

    if reference_strands:
        colors = {}
        for strand in reference_strands:
            colors.setdefault(strand["set_number"], strand.get("color"))
        for strand in strands:
            color = colors.get(strand["set_number"])
            if color:
                strand["color"] = copy.deepcopy(color)

    for idx, strand in enumerate(strands):
        strand["index"] = idx
    return _history_json(strands)


def generate_multi_level_json(m, n, ks, hand="lh", direction="cw",
                              align=True, angle_mode=ANGLE_MODE,
                              angle_step_degrees=ANGLE_STEP_DEGREES,
                              max_extension=MAX_EXTENSION,
                              strand_width=STRAND_WIDTH,
                              max_pair_extension=MAX_PAIR_EXTENSION,
                              pair_extension_step=None, use_gpu=False,
                              escalate_extension=None,
                              retract=RETRACT, tail_offset=TAIL_OFFSET,
                              collect_stages=False, verbose=True):
    """
    Build a starting stitch and grow one continuation level per entry in `ks`,
    aligning each level before the next one is welded on.

    Args:
        m, n:       grid size (m verticals, n horizontals).
        ks:         list of rotations, one per level.  `ks[0]` drives _4/_5,
                    `ks[1]` drives _6/_7, `ks[2]` drives _8/_9, ...
                    Each may be positive, zero or negative.
        hand:       "lh" or "rh".
        direction:  "cw" or "ccw".
        align:      run the parallel alignment after each level (recommended —
                    level L+1 is derived from level L's ALIGNED geometry).
        collect_stages: also return one JSON snapshot per stage in
                    `report["stages"]` — the starting stitch, then the pattern
                    after each level is welded on and aligned. Every snapshot
                    comes from this one run, so the per-set colours match.

    Returns:
        (json_text, report) — report lists per-level ordering and alignment.
    """
    if not ks:
        raise ValueError("ks must contain at least one k (the _4/_5 level)")

    engine = get_engine(hand)
    ks = [int(k) for k in ks]

    # ---- level 1: the engines' own starting stitch + _4/_5 continuation ----
    level1_json = engine.generate_json(m, n, ks[0], direction)
    data = json.loads(level1_json)
    strands = _get_active_strands(data)

    report = {
        "m": m, "n": n, "hand": hand, "direction": direction, "ks": ks,
        "levels": [],
    }

    stages = [] if collect_stages else None
    if stages is not None:
        stages.append({
            "level": 0,
            "k": None,
            "label": "starting stitch (_1/_2/_3)",
            "json": build_starting_stitch_json(m, n, hand, reference_strands=strands),
        })

    ident_real_to_virtual, ident_virtual_to_real = _identity_relabel(hand, m, n)
    level1_info = {
        "level": 1,
        "k": ks[0],
        "k_prev": None,
        "real_to_virtual": ident_real_to_virtual,
        "virtual_to_real": ident_virtual_to_real,
        "new_masks": [s for s in strands
                      if s.get("type") == "MaskedStrand"
                      and _is_level_mask(s.get("layer_name", ""), 4, 5)],
    }

    level_entry = {
        "level": 1,
        "k": ks[0],
        "suffixes": "_2/_3 -> _4/_5",
        "strands": [s["layer_name"] for s in strands
                    if s.get("type") == "AttachedStrand"
                    and s.get("layer_name", "").endswith(("_4", "_5"))],
    }

    if align:
        results = align_continuation_level(
            strands, m, n, ks[0], direction, hand, 1, level1_info,
            angle_step_degrees=angle_step_degrees, max_extension=max_extension,
            strand_width=strand_width, max_pair_extension=max_pair_extension,
            pair_extension_step=pair_extension_step, use_gpu=use_gpu,
            angle_mode=angle_mode, escalate_extension=escalate_extension,
            verbose=verbose,
        )
        level_entry["alignment"] = {
            "horizontal": _result_line(results["horizontal"]),
            "vertical": _result_line(results["vertical"]),
        }
    report["levels"].append(level_entry)
    if stages is not None:
        stages.append({
            "level": 1,
            "k": ks[0],
            "label": f"+ _4/_5 at k={ks[0]}" + (" (aligned)" if align else ""),
            "json": _snapshot_json(strands),
        })

    # ---- levels 2..N: the generic machinery -------------------------------
    for idx, k in enumerate(ks[1:], start=2):
        src_a, src_b, dst_a, dst_b = level_suffixes(idx)
        strands, info = add_continuation_level(
            strands, m, n, k, direction, hand, idx,
            k_prev=ks[idx - 2], retract=retract, tail_offset=tail_offset,
            verbose=verbose,
        )
        entry = {
            "level": idx,
            "k": k,
            "suffixes": f"_{src_a}/_{src_b} -> _{dst_a}/_{dst_b}",
            "strands": [s["layer_name"] for s in info["new_strands"]],
            "masks": [s["layer_name"] for s in info["new_masks"]],
            "vertical_order": info["vertical_order"],
            "horizontal_order": info["horizontal_order"],
            "relabel": info["real_to_virtual"],
            "note": info["note"],
        }
        if align:
            results = align_continuation_level(
                strands, m, n, k, direction, hand, idx, info,
                angle_step_degrees=angle_step_degrees, max_extension=max_extension,
                strand_width=strand_width, max_pair_extension=max_pair_extension,
                pair_extension_step=pair_extension_step, use_gpu=use_gpu,
                angle_mode=angle_mode, escalate_extension=escalate_extension,
                verbose=verbose,
            )
            entry["alignment"] = {
                "horizontal": _result_line(results["horizontal"]),
                "vertical": _result_line(results["vertical"]),
            }
        report["levels"].append(entry)
        if stages is not None:
            stages.append({
                "level": idx,
                "k": k,
                "label": f"+ _{dst_a}/_{dst_b} at k={k}" + (" (aligned)" if align else ""),
                "json": _snapshot_json(strands),
            })

    for idx, strand in enumerate(strands):
        strand["index"] = idx

    report["total_strands"] = len(strands)
    if stages is not None:
        report["stages"] = stages
    return _history_json(strands), report


def _is_level_mask(layer_name, dst_a, dst_b):
    """True for a mask name like `3_4_1_5` built from the given suffix pair."""
    parts = layer_name.split("_")
    if len(parts) != 4:
        return False
    return parts[1] in (str(dst_a), str(dst_b)) and parts[3] in (str(dst_a), str(dst_b))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_report(report):
    print("\n" + "=" * 70)
    print(f"MULTI-LEVEL CONTINUATION  {report['hand'].upper()} {report['m']}x{report['n']} "
          f"{report['direction'].upper()}  ks={report['ks']}")
    print("=" * 70)
    for entry in report["levels"]:
        print(f"\nLevel {entry['level']}  k={entry['k']}  {entry['suffixes']}")
        if entry.get("note"):
            print(f"  NOTE   : {entry['note']}")
        print(f"  strands: {entry['strands']}")
        if entry.get("masks"):
            print(f"  masks  : {entry['masks']}")
        if entry.get("vertical_order"):
            print(f"  V order: {entry['vertical_order']}")
            print(f"  H order: {entry['horizontal_order']}")
        if entry.get("alignment"):
            print(f"  align H: {entry['alignment']['horizontal']}")
            print(f"  align V: {entry['alignment']['vertical']}")
    print(f"\nTotal strands: {report['total_strands']}")
    print("=" * 70)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Grow _6/_7 (and beyond) from an aligned _4/_5 MxN stitch.")
    parser.add_argument("--m", type=int, default=2, help="vertical sets (default 2)")
    parser.add_argument("--n", type=int, default=2, help="horizontal sets (default 2)")
    parser.add_argument("--ks", type=int, nargs="+", default=[1, -1],
                        help="one k per level: first drives _4/_5, second _6/_7, ... "
                             "(default: 1 -1)")
    parser.add_argument("--hand", choices=["lh", "rh"], default="lh")
    parser.add_argument("--direction", choices=["cw", "ccw"], default=None,
                        help="default: cw for lh, ccw for rh (the paired convention)")
    parser.add_argument("--no-align", action="store_true", help="skip parallel alignment")
    parser.add_argument("--angle-mode", default=ANGLE_MODE,
                        choices=["first_strand", "avg_gaussian", "gaussian", "uniform"])
    parser.add_argument("--max-pair-extension", type=int, default=MAX_PAIR_EXTENSION)
    parser.add_argument("--pair-extension-step", type=int, default=None,
                        help="pin the extension grid; default is the twist sheet's "
                             "auto rule (finest step each group's pair count affords)")
    parser.add_argument("--use-gpu", action="store_true")
    parser.add_argument("--no-escalate", action="store_true",
                        help="never grow the extension ceiling, even on levels >= 2")
    parser.add_argument("--escalate-level-1", action="store_true",
                        help="also grow it on level 1 (breaks twist-sheet parity)")
    parser.add_argument("--out", default=None, help="output JSON path")
    parser.add_argument("--png", default=None,
                        help="also render a PNG, drawn exactly the way main.py draws "
                             "(needs PyQt5 and a sibling openstrandstudio checkout)")
    parser.add_argument("--sequence-dir", default=None,
                        help="render one frame per stage into this directory: the "
                             "starting stitch, then the pattern after each level, all "
                             "on shared bounds so the frames line up")
    parser.add_argument("--scale", type=float, default=2.0, help="PNG pixels per canvas unit")
    parser.add_argument("--transparent", action="store_true", help="transparent PNG background")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    direction = args.direction or ("cw" if args.hand == "lh" else "ccw")

    json_text, report = generate_multi_level_json(
        args.m, args.n, args.ks, hand=args.hand, direction=direction,
        align=not args.no_align, angle_mode=args.angle_mode,
        max_pair_extension=args.max_pair_extension,
        pair_extension_step=args.pair_extension_step,
        use_gpu=args.use_gpu, collect_stages=bool(args.sequence_dir),
        escalate_extension=(False if args.no_escalate
                            else (True if args.escalate_level_1 else None)),
        verbose=not args.quiet,
    )

    _print_report(report)

    out = args.out
    if out is None:
        levels = "_".join(f"k{k}" for k in args.ks)
        out_dir = os.path.join(_HERE, "mxn", "mxn_continueing",
                               f"mxn_{args.hand}_continuation_multi")
        os.makedirs(out_dir, exist_ok=True)
        out = os.path.join(
            out_dir,
            f"mxn_{args.hand}_{args.m}x{args.n}_continue_{levels}_{direction}.json",
        )
    with open(out, "w", encoding="utf-8") as handle:
        handle.write(json_text)
    print(f"\nSaved: {out}")

    if args.png or args.sequence_dir:
        # Lazy import: the generator itself needs neither PyQt5 nor OpenStrandStudio.
        from mxn_continuation_render import (
            create_render_canvas, render_json_to_file, render_sequence,
        )

        canvas, kind = create_render_canvas()

        if args.png:
            image = render_json_to_file(json_text, args.png, scale_factor=args.scale,
                                        transparent=args.transparent, canvas=canvas)
            print(f"Saved: {args.png} ({image.width()}x{image.height()}, "
                  f"{len(canvas.strands)} layers, {kind} canvas)")

        if args.sequence_dir:
            frames = render_sequence(report["stages"], args.sequence_dir,
                                     scale_factor=args.scale,
                                     transparent=args.transparent, canvas=canvas)
            print(f"\nSequence ({kind} canvas, shared bounds):")
            for path, label in frames:
                print(f"  {path}  -  {label}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
