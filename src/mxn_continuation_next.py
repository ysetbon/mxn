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
                           verbose=True):
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
        retract:      how far each source tail is pulled back before the weld.
        tail_offset:  how far past the paired point the new tail runs.

    Returns:
        (all_strands, info) where info carries the relabel maps, the new strand
        list, the new mask list and the ordering used.
    """
    engine = get_engine(hand)
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
    for real_name in real_to_virtual:
        _retract_end(source_by_name[real_name], retract)

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


def align_continuation_level(strands, m, n, k, direction, hand, level, level_info,
                             angle_step_degrees=0.5, max_extension=100.0,
                             strand_width=STRAND_WIDTH, max_pair_extension=200,
                             pair_extension_step=10, use_gpu=False,
                             angle_mode="avg_gaussian", verbose=True):
    """
    Run the engine's parallel alignment on one continuation level.

    The level's source ring is presented to the engine as `_2/_3` and the new
    ring as `_4/_5`, so the existing (tested) search runs unchanged.  Results
    are copied back onto the real strands afterwards — both the new tails and
    any extension the search applied to the source tails.

    Returns:
        dict with the horizontal and vertical alignment results.
    """
    engine = get_engine(hand)
    virtual_list, back_map = _build_virtual_view(strands, level_info, level)

    if verbose:
        print(f"\n--- LEVEL {level} alignment (k={k}, {direction}, mode={angle_mode}) ---")

    h_result = engine.align_horizontal_strands_parallel(
        virtual_list, n,
        angle_step_degrees=angle_step_degrees,
        max_extension=max_extension,
        strand_width=strand_width,
        max_pair_extension=max_pair_extension,
        pair_extension_step=pair_extension_step,
        m=m, k=k, direction=direction,
        use_gpu=use_gpu,
        angle_mode=angle_mode,
    )
    if h_result.get("success") or h_result.get("is_fallback"):
        virtual_list = engine.apply_parallel_alignment(virtual_list, h_result)

    v_result = engine.align_vertical_strands_parallel(
        virtual_list, n, m,
        angle_step_degrees=angle_step_degrees,
        max_extension=max_extension,
        strand_width=strand_width,
        max_pair_extension=max_pair_extension,
        pair_extension_step=pair_extension_step,
        k=k, direction=direction,
        use_gpu=use_gpu,
        angle_mode=angle_mode,
    )
    if v_result.get("success") or v_result.get("is_fallback"):
        virtual_list = engine.apply_parallel_alignment(virtual_list, v_result)

    for v_strand in virtual_list:
        real = back_map.get(v_strand["layer_name"])
        if real is not None:
            _copy_geometry(v_strand, real)

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

    return {"horizontal": h_result, "vertical": v_result}


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


def generate_multi_level_json(m, n, ks, hand="lh", direction="cw",
                              align=True, angle_mode="avg_gaussian",
                              angle_step_degrees=0.5, max_extension=100.0,
                              strand_width=STRAND_WIDTH, max_pair_extension=200,
                              pair_extension_step=10, use_gpu=False,
                              retract=RETRACT, tail_offset=TAIL_OFFSET,
                              verbose=True):
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
            angle_mode=angle_mode, verbose=verbose,
        )
        level_entry["alignment"] = {
            "horizontal": _result_line(results["horizontal"]),
            "vertical": _result_line(results["vertical"]),
        }
    report["levels"].append(level_entry)

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
                angle_mode=angle_mode, verbose=verbose,
            )
            entry["alignment"] = {
                "horizontal": _result_line(results["horizontal"]),
                "vertical": _result_line(results["vertical"]),
            }
        report["levels"].append(entry)

    for idx, strand in enumerate(strands):
        strand["index"] = idx

    report["total_strands"] = len(strands)
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
    parser.add_argument("--angle-mode", default="avg_gaussian",
                        choices=["first_strand", "avg_gaussian", "gaussian", "uniform"])
    parser.add_argument("--max-pair-extension", type=int, default=200)
    parser.add_argument("--pair-extension-step", type=int, default=10)
    parser.add_argument("--use-gpu", action="store_true")
    parser.add_argument("--out", default=None, help="output JSON path")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    direction = args.direction or ("cw" if args.hand == "lh" else "ccw")

    json_text, report = generate_multi_level_json(
        args.m, args.n, args.ks, hand=args.hand, direction=direction,
        align=not args.no_align, angle_mode=args.angle_mode,
        max_pair_extension=args.max_pair_extension,
        pair_extension_step=args.pair_extension_step,
        use_gpu=args.use_gpu, verbose=not args.quiet,
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
