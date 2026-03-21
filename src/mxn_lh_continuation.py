"""
MxN LH Continuation Generator

Generates LH stretch patterns with continuation strands (_4, _5).
The continuation is based on emoji pairing logic where:
- _4 start = _2 end (attached to it)
- _4 end = paired position (same emoji on opposite side)
- _5 start = _3 end (attached to it)
- _5 end = paired position (same emoji on opposite side)

Usage:
    from mxn_lh_continuation import generate_json
    json_content = generate_json(m=2, n=2, k=0, direction="cw")
"""

import copy
import json
import itertools
import os
import sys
import random
import time
import colorsys
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, ThreadPoolExecutor, wait

# Emoji names matching the order in mxn_emoji_renderer.get_animal_pool()
EMOJI_NAMES = [
    "dog", "cat", "mouse", "rabbit", "hedgehog",      # 0-4
    "fox", "bear", "panda", "koala", "tiger",         # 5-9
    "lion", "cow", "pig", "frog", "monkey",           # 10-14
    "chicken", "penguin", "bird", "chick", "duck",    # 15-19
    "owl", "bat", "wolf", "boar", "horse",            # 20-24
    "unicorn", "bee", "bug", "butterfly", "snail",    # 25-29
    "ladybug", "turtle", "snake", "lizard", "t-rex",  # 30-34
    "sauropod", "octopus", "squid", "shrimp", "lobster",  # 35-39
    "crab", "blowfish", "tropical_fish", "fish", "dolphin",  # 40-44
    "whale", "crocodile", "zebra", "giraffe", "bison"  # 45-49
]

def get_emoji_name(index):
    """Get emoji name by index, with fallback for out-of-range indices."""
    if 0 <= index < len(EMOJI_NAMES):
        return EMOJI_NAMES[index]
    return f"emoji_{index}"


__all__ = [
    "generate_json",
    # Backwards/alternate public entrypoints
    "mxn_lh_continue",
    "mxn_lh_continute",
    # Parallel alignment functions
    "align_horizontal_strands_parallel",
    "align_vertical_strands_parallel",
    "apply_parallel_alignment",
    "print_alignment_debug",
    "get_alignment_combo_guard",
]


def mxn_lh_continue(m, n, k=0, direction="cw"):
    """Alias for `generate_json` (LH continuation)."""
    return generate_json(m=m, n=n, k=k, direction=direction)


def mxn_lh_continute(m, n, k=0, direction="cw"):
    """Typo-compatible alias for `mxn_lh_continue`."""
    return mxn_lh_continue(m=m, n=n, k=k, direction=direction)


def generate_json(m, n, k=0, direction="cw"):
    """
    Generate LH stretch pattern WITH continuation (_4, _5 strands).

    Args:
        m: Number of vertical strands
        n: Number of horizontal strands
        k: Emoji rotation value (determines pairing)
        direction: "cw" or "ccw" (rotation direction)

    Returns:
        JSON string with base + continuation strands
    """
    # Constants and parameters (same as mxn_lh_strech.py)
    grid_unit = 42.0
    gap = grid_unit * (2.0 / 3.0)  # 28.0
    stride = 4.0 * gap  # 112.0
    length = stride
    center_x = 1274.0 - grid_unit
    center_y = 434.0 - grid_unit
    tail_offset = grid_unit + grid_unit / 3  # 56.0

    # Colors
    fixed_colors = {
        1: {"r": 255, "g": 255, "b": 255, "a": 255},
        2: {"r": 85, "g": 170, "b": 0, "a": 255},
    }

    index_counter = [0]  # Use list to allow modification in nested function

    def get_color(set_num):
        if set_num in fixed_colors:
            return fixed_colors[set_num]
        h, s, l = random.random(), random.uniform(0.2, 0.9), random.uniform(0.1, 0.9)
        r, g, b = [int(x * 255) for x in colorsys.hls_to_rgb(h, l, s)]
        return {"r": r, "g": g, "b": b, "a": 255}

    def create_strand_base(
        start,
        end,
        color,
        layer_name,
        set_number,
        strand_type="Strand",
        attached_to=None,
        attachment_side=None,
    ):
        if strand_type == "Strand":
            has_circles = [True, True]
        elif strand_type == "AttachedStrand":
            has_circles = [True, False]
        else:  # MaskedStrand
            has_circles = [False, False]

        cp_center = {
            "x": (start["x"] + end["x"]) / 2,
            "y": (start["y"] + end["y"]) / 2,
        }

        if strand_type == "MaskedStrand":
            control_points = [None, None]
        else:
            control_points = [
                {"x": start["x"], "y": start["y"]},
                {"x": end["x"], "y": end["y"]},
            ]

        strand = {
            "type": strand_type,
            "index": index_counter[0],
            "start": start,
            "end": end,
            "width": 46,
            "color": color,
            "stroke_color": {"r": 0, "g": 0, "b": 0, "a": 255},
            "stroke_width": 4,
            "has_circles": has_circles,
            "layer_name": layer_name,
            "set_number": set_number,
            "is_first_strand": strand_type == "Strand",
            "is_start_side": strand_type == "Strand" or strand_type == "MaskedStrand",
            "start_line_visible": True,
            "end_line_visible": True,
            "is_hidden": False,
            "start_extension_visible": False,
            "end_extension_visible": False,
            "start_arrow_visible": False,
            "end_arrow_visible": False,
            "full_arrow_visible": False,
            "shadow_only": False,
            "closed_connections": [False, False],
            "arrow_color": None,
            "arrow_transparency": 100,
            "arrow_texture": "none",
            "arrow_shaft_style": "solid",
            "arrow_head_visible": True,
            "arrow_casts_shadow": False,
            "knot_connections": {},
            "circle_stroke_color": {"r": 0, "g": 0, "b": 0, "a": 255},
            "start_circle_stroke_color": {"r": 0, "g": 0, "b": 0, "a": 255},
            "end_circle_stroke_color": {"r": 0, "g": 0, "b": 0, "a": 255},
            "control_points": control_points,
            "control_point_center": cp_center,
            "control_point_center_locked": False,
            "bias_control": {
                "triangle_bias": 0.5,
                "circle_bias": 0.5,
                "triangle_position": None,
                "circle_position": None,
            },
            "triangle_has_moved": False,
            "control_point2_shown": False,
            "control_point2_activated": False,
        }

        if attached_to:
            strand["attached_to"] = attached_to
            strand["attachment_side"] = attachment_side
            strand["angle"] = 0
            strand["length"] = 0
            strand["is_start_side"] = False

        if strand_type == "MaskedStrand":
            strand["deletion_rectangles"] = []

        index_counter[0] += 1
        return strand

    # =========================================================================
    # STEP 1: Generate base strands (_1, _2, _3) - same as mxn_lh_strech.py
    # =========================================================================
    strands_1 = []  # Main strands (_1)
    strands_2 = []  # Attached strands (_2)
    strands_3 = []  # Attached strands (_3)

    # Verticals (Sets n+1 ... n+m)
    for i in range(m):
        cx = center_x + (i - (m - 1) / 2) * stride
        v_set_num = n + 1 + i

        h_top_cy = center_y - (n - 1) / 2.0 * stride
        h_bottom_cy = center_y + (n - 1) / 2.0 * stride

        end_y = h_top_cy - stride / 2.0
        start_y = h_bottom_cy + stride / 2.0

        start_pt = {"x": cx + gap, "y": start_y}
        end_pt = {"x": cx - gap, "y": end_y}

        main_layer = f"{v_set_num}_1"
        color = get_color(v_set_num)

        # Main Strand (_1)
        main_strand = create_strand_base(start_pt, end_pt, color, main_layer, v_set_num, "Strand")
        strands_1.append(main_strand)

        # Attached Strand (_3) - Top (End)
        att_3_end = {"x": end_pt["x"], "y": start_pt["y"] + tail_offset}
        strand_2_3 = create_strand_base(
            end_pt, att_3_end, color, f"{v_set_num}_3", v_set_num,
            "AttachedStrand", main_layer, 1,
        )
        strands_3.append(strand_2_3)

        # Attached Strand (_2) - Bottom (Start)
        att_2_end = {"x": start_pt["x"], "y": end_pt["y"] - tail_offset}
        strand_2_2 = create_strand_base(
            start_pt, att_2_end, color, f"{v_set_num}_2", v_set_num,
            "AttachedStrand", main_layer, 0,
        )
        strands_2.append(strand_2_2)

    # Horizontals (Sets 1 ... n)
    for i in range(n):
        cy = center_y + (i - (n - 1) / 2) * stride
        h_set_num = 1 + i

        base_half_w = ((m - 1) * stride + length) / 2

        start_pt = {"x": center_x - base_half_w, "y": cy + gap}
        end_pt = {"x": center_x + base_half_w, "y": cy - gap}
        main_layer = f"{h_set_num}_1"
        color = get_color(h_set_num)

        # Main Strand (_1)
        main_strand = create_strand_base(start_pt, end_pt, color, main_layer, h_set_num, "Strand")
        strands_1.append(main_strand)

        # Attached Strand (_2) - Right (End)
        att_2_end = {"x": start_pt["x"] - tail_offset, "y": end_pt["y"]}
        strand_1_2 = create_strand_base(
            end_pt, att_2_end, color, f"{h_set_num}_2", h_set_num,
            "AttachedStrand", main_layer, 1,
        )
        strands_2.append(strand_1_2)

        # Attached Strand (_3) - Left (Start)
        att_3_end = {"x": end_pt["x"] + tail_offset, "y": start_pt["y"]}
        strand_1_3 = create_strand_base(
            start_pt, att_3_end, color, f"{h_set_num}_3", h_set_num,
            "AttachedStrand", main_layer, 0,
        )
        strands_3.append(strand_1_3)

    # Combine base strands
    base_strands = strands_1 + strands_2 + strands_3

    # =========================================================================
    # STEP 2: Generate base masked strands (_2 x _3 crossings)
    # =========================================================================
    base_masked = []
    v_tails = [s for s in base_strands if s["set_number"] > n and s["type"] == "AttachedStrand"]
    h_tails = [s for s in base_strands if s["set_number"] <= n and s["type"] == "AttachedStrand"]

    print(f"\n=== STEP 2: Generating _2 x _3 base masks (LH) ===")
    for v in v_tails:
        for h in h_tails:
            is_match = False
            if v["layer_name"].endswith("_2") and h["layer_name"].endswith("_3"):
                is_match = True
            elif v["layer_name"].endswith("_3") and h["layer_name"].endswith("_2"):
                is_match = True

            if is_match:
                masked_strand = create_strand_base(
                    v["start"], v["end"], v["color"],
                    f"{v['layer_name']}_{h['layer_name']}",
                    int(f"{v['set_number']}{h['set_number']}"),
                    "MaskedStrand"
                )
                masked_strand["first_selected_strand"] = v["layer_name"]
                masked_strand["second_selected_strand"] = h["layer_name"]
                base_masked.append(masked_strand)
                print(f"  Base mask: {v['layer_name']} x {h['layer_name']}")

    print(f"Total _2/_3 base masks: {len(base_masked)}")
    print(f"Base mask layer names: {[m['layer_name'] for m in base_masked]}")

    # =========================================================================
    # STEP 3: Compute emoji pairings based on k and direction
    # =========================================================================

    pairings = compute_emoji_pairings(base_strands, m, n, k, direction)

    # =========================================================================
    # STEP 4: Generate continuation strands (_4, _5)
    #
    # Per the docstring:
    # - _4 attaches to _2's end and extends to the paired position (same emoji)
    # - _5 attaches to _3's end and extends to the paired position (same emoji)
    #
    # The end position is determined by the emoji pairing (which depends on k).
    # The ends are extended further outward (by tail_offset) to reach near the emoji positions.
    # =========================================================================
    strands_4 = []
    strands_5 = []

    import math

    def extend_endpoint(start_x, start_y, end_x, end_y, extension):
        """Extend the endpoint further in the same direction by the given amount."""
        dx = end_x - start_x
        dy = end_y - start_y
        length = math.sqrt(dx * dx + dy * dy)
        if length < 0.001:
            return end_x, end_y
        # Normalize and extend
        nx = dx / length
        ny = dy / length
        return end_x + nx * extension, end_y + ny * extension

    print(f"\n=== STEP 4: Generating _4 and _5 strands ===")
    print(f"Using emoji pairings to determine end positions (k={k}, {direction})")
    print(f"Pairings: {pairings}")

    for strand in base_strands:
        if strand["type"] != "AttachedStrand":
            continue

        layer_name = strand["layer_name"]
        set_num = strand["set_number"]
        color = strand["color"]

        if layer_name.endswith("_2"):
            # Retract _2's end by 52px toward _2's start (default extension)
            dx = strand["end"]["x"] - strand["start"]["x"]
            dy = strand["end"]["y"] - strand["start"]["y"]
            length = math.sqrt(dx * dx + dy * dy)
            if length > 0.001:
                nx = dx / length
                ny = dy / length
                strand["end"]["x"] -= nx * 52
                strand["end"]["y"] -= ny * 52
            # Update control_points and control_point_center to match new end
            if strand.get("control_points") and strand["control_points"][1] is not None:
                strand["control_points"][1]["x"] = strand["end"]["x"]
                strand["control_points"][1]["y"] = strand["end"]["y"]
            strand["control_point_center"]["x"] = (strand["start"]["x"] + strand["end"]["x"]) / 2
            strand["control_point_center"]["y"] = (strand["start"]["y"] + strand["end"]["y"]) / 2
            # _4 attaches to _2's new end and goes to the paired position
            start_x = strand["end"]["x"]
            start_y = strand["end"]["y"]

            # Get paired position from emoji pairing
            pairing_key = f"{layer_name}_end"
            if pairing_key in pairings:
                paired_pos = pairings[pairing_key]
                base_end_x = paired_pos["x"]
                base_end_y = paired_pos["y"]
            else:
                # Fallback: shouldn't happen if pairings are computed correctly
                print(f"  WARNING: No pairing found for {pairing_key}, using start position")
                base_end_x = start_x
                base_end_y = start_y

            # Extend the end further outward (near emoji position)
            end_x, end_y = extend_endpoint(start_x, start_y, base_end_x, base_end_y, tail_offset)

            strand_4 = create_strand_base(
                {"x": start_x, "y": start_y},
                {"x": end_x, "y": end_y},
                color,
                f"{set_num}_4",
                set_num,
                "AttachedStrand",
                layer_name,
                1,
            )
            strands_4.append(strand_4)
            print(f"  Created {set_num}_4 (from _2): start=({start_x}, {start_y}), end=({end_x:.1f}, {end_y:.1f})")

        elif layer_name.endswith("_3"):
            # Retract _3's end by 52px toward _3's start (default extension)
            dx = strand["end"]["x"] - strand["start"]["x"]
            dy = strand["end"]["y"] - strand["start"]["y"]
            length = math.sqrt(dx * dx + dy * dy)
            if length > 0.001:
                nx = dx / length
                ny = dy / length
                strand["end"]["x"] -= nx * 52
                strand["end"]["y"] -= ny * 52
            # Update control_points and control_point_center to match new end
            if strand.get("control_points") and strand["control_points"][1] is not None:
                strand["control_points"][1]["x"] = strand["end"]["x"]
                strand["control_points"][1]["y"] = strand["end"]["y"]
            strand["control_point_center"]["x"] = (strand["start"]["x"] + strand["end"]["x"]) / 2
            strand["control_point_center"]["y"] = (strand["start"]["y"] + strand["end"]["y"]) / 2
            # _5 attaches to _3's new end and goes to the paired position
            start_x = strand["end"]["x"]
            start_y = strand["end"]["y"]

            # Get paired position from emoji pairing
            pairing_key = f"{layer_name}_end"
            if pairing_key in pairings:
                paired_pos = pairings[pairing_key]
                base_end_x = paired_pos["x"]
                base_end_y = paired_pos["y"]
            else:
                # Fallback: shouldn't happen if pairings are computed correctly
                print(f"  WARNING: No pairing found for {pairing_key}, using start position")
                base_end_x = start_x
                base_end_y = start_y

            # Extend the end further outward (near emoji position)
            end_x, end_y = extend_endpoint(start_x, start_y, base_end_x, base_end_y, tail_offset)

            strand_5 = create_strand_base(
                {"x": start_x, "y": start_y},
                {"x": end_x, "y": end_y},
                color,
                f"{set_num}_5",
                set_num,
                "AttachedStrand",
                layer_name,
                1,
            )
            strands_5.append(strand_5)
            print(f"  Created {set_num}_5 (from _3): start=({start_x}, {start_y}), end=({end_x:.1f}, {end_y:.1f})")

    # Order continuation strands based on get_vertical_order_k then get_horizontal_order_k
    # Convert _2 -> _4 and _3 -> _5 for the ordering
    vertical_order_k = get_vertical_order_k(m, n, k, direction)
    horizontal_order_k = get_horizontal_order_k(m, n, k, direction)

    # Convert vertical order (_2/_3) to continuation order (_4/_5)
    vertical_continuation_order = []
    for layer in vertical_order_k:
        # e.g., "3_2" -> "3_4", "3_3" -> "3_5"
        parts = layer.split("_")
        new_suffix = "4" if parts[1] == "2" else "5"
        vertical_continuation_order.append(f"{parts[0]}_{new_suffix}")

    # Convert horizontal order (_2/_3) to continuation order (_4/_5)
    horizontal_continuation_order = []
    for layer in horizontal_order_k:
        # e.g., "1_2" -> "1_4", "1_3" -> "1_5"
        parts = layer.split("_")
        new_suffix = "4" if parts[1] == "2" else "5"
        horizontal_continuation_order.append(f"{parts[0]}_{new_suffix}")

    # Combined order: vertical first, then horizontal
    continuation_order = vertical_continuation_order + horizontal_continuation_order

    print(f"\nVertical order (k={k}, {direction}): {vertical_order_k} -> {vertical_continuation_order}")
    print(f"Horizontal order (k={k}, {direction}): {horizontal_order_k} -> {horizontal_continuation_order}")

    # Build lookup and sort continuation strands by the computed order
    all_continuation = strands_4 + strands_5
    strand_lookup = {s["layer_name"]: s for s in all_continuation}

    continuation_strands = []
    for layer_name in continuation_order:
        if layer_name in strand_lookup:
            continuation_strands.append(strand_lookup[layer_name])

    print(f"\nTotal: {len(strands_4)} _4 strands: {[s['layer_name'] for s in strands_4]}")
    print(f"Total: {len(strands_5)} _5 strands: {[s['layer_name'] for s in strands_5]}")
    print(f"Continuation order: {[s['layer_name'] for s in continuation_strands]}")

    # =========================================================================
    # STEP 5: Generate _4/_5 masks using get_mask_order_k
    # =========================================================================
    print(f"\n=== STEP 5: Generating _4/_5 continuation masks ===")

    masks_info = compute_4_5_masks(base_strands, continuation_strands, m, n, k, direction)

    continuation_masked = []
    for mask_info in masks_info:
        v_strand = mask_info["v_strand"]
        h_strand = mask_info["h_strand"]

        # Create MaskedStrand using vertical strand's geometry
        masked_strand = create_strand_base(
            v_strand["start"], v_strand["end"], v_strand["color"],
            mask_info["layer_name"],
            mask_info["set_number"],
            "MaskedStrand"
        )
        masked_strand["first_selected_strand"] = mask_info["first_strand"]
        masked_strand["second_selected_strand"] = mask_info["second_strand"]
        continuation_masked.append(masked_strand)
        print(f"  Created _4/_5 mask: {mask_info['layer_name']}")

    print(f"Total _4/_5 masks created: {len(continuation_masked)}")

    # =========================================================================
    # STEP 6: Combine all strands and build JSON
    # =========================================================================
    all_strands = base_strands + base_masked + continuation_strands + continuation_masked

    print(f"\n=== STEP 6: Final strand counts ===")
    print(f"Base strands: {len(base_strands)}")
    print(f"Base masked: {len(base_masked)}")
    print(f"Continuation strands (_4 + _5): {len(continuation_strands)}")
    print(f"Continuation masked: {len(continuation_masked)}")
    print(f"TOTAL strands: {len(all_strands)}")

    # Re-index all strands
    for idx, s in enumerate(all_strands):
        s["index"] = idx

    # Build history JSON
    history = {
        "type": "OpenStrandStudioHistory",
        "version": 1,
        "current_step": 2,
        "max_step": 2,
        "states": [],
    }

    for step in range(1, 3):
        state_data = {
            "strands": all_strands,
            "groups": {},
            "selected_strand_name": None,
            "locked_layers": [],
            "lock_mode": False,
            "shadow_enabled": False,
            "show_control_points": step == 1,
            "shadow_overrides": {},
        }
        history["states"].append({"step": step, "data": state_data})

    return json.dumps(history, indent=2)


def get_starting_order(m, n):
    """
    LH version: starting by the **top-right** and going **counterclockwise**.
    Perimeter order is: **top + left + bottom + right**.

    Matches the UI/emoji layout:
    - Top side uses `_2` (right → left)
    - Left side uses `_2` (top → bottom)
    - Bottom side uses `_3` (left → right)
    - Right side uses `_3` (bottom → top)

    Example (m=2, n=2):
    ["4_2", "3_2", "1_2", "2_2", "3_3", "4_3", "2_3", "1_3"]
    top: ["4_2", "3_2"]
    left: ["1_2", "2_2"]
    bottom: ["3_3", "4_3"]
    right: ["2_3", "1_3"]
    """
    top = [f"{i}_2" for i in reversed(range(n + 1, n + m + 1))]
    left = [f"{i}_2" for i in range(1, n  + 1)]
    bottom = [f"{i}_3" for i in range(n + 1, n + m + 1)]
    right = [f"{i}_3" for i in reversed(range(1, n  + 1))]
    
    return top + left + bottom + right

def get_starting_order_oposite_orientation(m, n):
    """
    starting by top left side and going clockwise. Top side + right side + bottom side + left side.

    Matches the UI/emoji layout:
    - Top side uses `_2` (left → right)
    - Right side uses `_3` (top → bottom)
    - Bottom side uses `_3` (right → left)
    - Left side uses `_2` (bottom → top)

    Example (m=2, n=2):
    ["3_2", "4_2", "1_3", "2_3", "4_3", "3_3", "2_2", "1_2"]
    top: ["3_2", "4_2"]
    right: ["1_3", "2_3"]
    bottom: ["4_3", "3_3"]
    left: ["2_2", "1_2"]
    """
 
    # Top: vertical sets (n+1..n+m), `_2`, left -> right
    top = [f"{i}_2" for i in range(n + 1, n + m + 1)]
    # Right: horizontal sets (1..n), `_3`, top -> bottom
    right = [f"{i}_3" for i in range(1, n + 1)]
    # Bottom: vertical sets (n+1..n+m), `_3`, right -> left
    bottom = [f"{i}_3" for i in reversed(range(n + 1, n + m + 1))]
    # Left: horizontal sets (1..n), `_2`, bottom -> top
    left = [f"{i}_2" for i in reversed(range(1, n + 1))]
    return top + right + bottom + left

def get_horizontal_order_k(m, n, k, direction):
    """
    This code works properly!
    if k is even - full order is top + left + bottom + right of get_starting_order. horizontal order when k = 0 we have pointer 1 to be pointing at first element of left side (1_2), pointer 2 pointing at last element of right side (1_3), pointer 3 pointing at second element of left side (2_2), pointer 4 pointing at one before last element of right side (2_3), etc. if k is even and not 0 we shift the pointers to the left by k/2 positions of the array of the total get_starting_order (see examples for k=2 and k=4).

    if k is odd - full order is top + right + bottom + left of get_starting_order_oposite_orientation. horizontal order when k = 1 we have pointer 1 to be pointing at first element of right side (1_3), pointer 2 pointing at last element of left side (1_2), pointer 3 pointing at second element of right side (2_3), pointer 4 pointing at one before last element of left side (2_2), etc. if k is odd and not 1 we shift the pointers to the right by (k-1)/2 positions of the array of the total get_starting_order_oposite_orientation.

    if k is negative, it is equals to 4*(m+n) + k.

    example for 2x2 with k = 0 cw, total order is (top:[4_2, 3_2] left:[1_2, 2_2] bottom:[3_3, 4_3] right:[2_3, 1_3]) ["4_2", "3_2", "1_2", "2_2", "3_3", "4_3", "2_3", "1_3"]
    so pointers: 1->1_2, 2->1_3, 3->2_2, 4->2_3, horizontal order is 1_2 1_3 2_2 2_3.

    example for 2x2 with k = 1 cw, get_starting_order_oposite_orientation (top: [3_2, 4_2] right[1_3, 2_3] bottom[4_3, 3_3] left[2_2, 1_2]) ["3_2", "4_2", "1_3", "2_3", "4_3", "3_3", "2_2", "1_2"] so pointers: 1->1_3, 2->1_2, 3->2_3, 4->2_2, horizontal order is 1_3 1_2 2_3 2_2.

    example for 2x2 with k = 2 cw, initial pointers: 1->1_2, 2->1_3, 3->2_2, 4->2_3 (for k = 0) , and the total order is (top:[4_2, 3_2] left:[1_2, 2_2] bottom:[3_3, 4_3] right:[2_3, 1_3]) ["4_2", "3_2", "1_2", "2_2", "3_3", "4_3", "2_3", "1_3"], we shift the pointers by k/2 = 1 positions, so the new pointers are (shifting to the left by 1 position): 1->3_2, 2->2_3, 3->1_2, 4->4_3, horizontal order is 3_2 2_3 1_2 4_3.

    example for 2x2 with k = 3 cw, initial pointers: 1->1_3, 2->1_2, 3->2_3, 4->2_2 (for k = 1) , and the get_starting_order_oposite_orientation (top: [3_2, 4_2] right[1_3, 2_3] bottom[4_3, 3_3] left[2_2, 1_2]) ["3_2", "4_2", "1_3", "2_3", "4_3", "3_3", "2_2", "1_2"], we shift the pointers by (k-1)/2 = 1 position, so the new pointers are (shifting to the right by 1 position): 1->2_3, 2->3_2, 3->4_3, 4->1_2, horizontal order is 2_3 3_2 4_3 1_2.

    example for 2x2 with k = 4 cw, initial pointers: 1->1_2, 2->1_3, 3->2_2, 4->2_3 (for k = 0) , and the total order is (top:[4_2, 3_2] left:[1_2, 2_2] bottom:[3_3, 4_3] right:[2_3, 1_3]) ["4_2", "3_2", "1_2", "2_2", "3_3", "4_3", "2_3", "1_3"], we shift the pointers by k/2 = 2 positions, so the new pointers are (shifting to the left by 2 positions): 
    4_2 4_3 3_2 3_3
    

    example for 2x2 with k = -1 cw, its eqals 4*(m+n) + k = 4*(2+2) + (-1) = 15, initial pointers: 1->1_3, 2->1_2, 3->2_3, 4->2_2 (for k = 1) , and the get_starting_order_oposite_orientation (top: [3_2, 4_2] right[1_3, 2_3] bottom[4_3, 3_3] left[2_2, 1_2]) ["3_2", "4_2", "1_3", "2_3", "4_3", "3_3", "2_2", "1_2"], we shift the pointers by (k-1)/2 = (15-1)/2 = 7 positions, so the new pointers are (shifting to the right by 7 positions): 1->4_2, 2->2_2, 3->1_3, 4->3_3, horizontal order is 4_2 2_2 1_3 3_3.

    we shift the pointers by (k-1)/2 = (15-1)/2 = 7 positions, so the new pointers are (shifting to the right by 7 positions): 1->4_2, 2->2_2, 3->1_3, 4->3_3, horizontal order is 4_2 2_2 1_3 3_3.


    When direction is ccw, just change the k value to -k.
    """

    if direction == "ccw":
        k = -k

    total_len = 2 * (m + n)
    full_order = get_starting_order(m, n)
    full_order_oposite_orientation = get_starting_order_oposite_orientation(m, n)
    # k=0 pointers for horizontal order pointer = ["1_2", "1_3", "2_2", "2_3", ...]
    pointer_k0 = []
    for i in range(n):
        pointer_k0.append(f"{i+1}_2")
        pointer_k0.append(f"{i+1}_3")
    pointer_k1 = []
    for i in range(n):
        pointer_k1.append(f"{i+1}_3")
        pointer_k1.append(f"{i+1}_2")
    if k == 0:
        return pointer_k0
    if k == 1:
        return pointer_k1

    # Normalize negative k to the positive equivalent (per examples in the docstring)
    if k < 0:
        k = 4 * (m + n) + k

    if k % 2 == 0:
        # Even k: shift LEFT by (k/2) on get_starting_order (see docstring examples for k=2,4)
        shift_steps = k // 2
        pointer_k = list(pointer_k0)
        for i in range(len(pointer_k)):
            strand = pointer_k[i]
            shift_position = full_order.index(strand)
            pointer_k[i] = full_order[(shift_position - shift_steps) % total_len]
    else:
        # Odd k: shift RIGHT by (k-1)/2 on get_starting_order_oposite_orientation
        shift_steps = (k-1)//2
        pointer_k = list(pointer_k1)
        for i in range(len(pointer_k)):
            strand = pointer_k[i]
            shift_position = full_order_oposite_orientation.index(strand)
            pointer_k[i] = full_order_oposite_orientation[(shift_position + shift_steps) % total_len]
    for i in range(len(pointer_k)):
        print(f"horizontal_order_k[{i}]: {pointer_k[i]}")
    return pointer_k

def get_vertical_order_k(m, n, k, direction):
    """
    Get the *vertical* endpoint order for an m×n continuation, at rotation `k` and `direction`.

    This follows the same conventions as `get_horizontal_order_k()` in this file:

    - **Direction handling**: for LH, when `direction == "ccw"`, we flip `k` (so the examples
      below are written for **cw**, matching the docstrings in this file).
    - **Negative k**: if `k < 0`, it is normalized using `k = 4*(m+n) + k`
      (kept consistent with `get_horizontal_order_k`'s implementation).
    - **Parity**:
      - even `k`: base pointers come from the `k=0` pattern and are shifted in
        `get_starting_order(m, n)` by `-(k/2)` (left by `k/2`).
      - odd `k`: base pointers come from the `k=1` pattern and are shifted in
        `get_starting_order_oposite_orientation(m, n)` by `+((k-1)/2)` (right by `(k-1)/2`).

    The returned list has length `2*m` and contains labels like `"3_2"` / `"3_3"`.

    CW examples for **m=2, n=2** (vertical sets are 3 and 4):
    - k = 0 (cw) -> ["3_2", "3_3", "4_2", "4_3"]
    - k = 1 (cw) -> ["3_3", "3_2", "4_3", "4_2"]
    """

    # Match LH horizontal convention: flip k for "ccw"
    if direction == "ccw":
        k = -k

    total_len = 2 * (m + n)
    full_order = get_starting_order(m, n)
    full_order_oposite_orientation = get_starting_order_oposite_orientation(m, n)

    # k=0 pointers for vertical order: ["(n+1)_3", "(n+1)_2", "(n+2)_3", "(n+2)_2", ...]
    # Note: vertical uses _3 before _2 (opposite of horizontal) due to 90° rotation
    pointer_k0 = []
    for i in range(m):
        pointer_k0.append(f"{n + 1 + i}_3")
        pointer_k0.append(f"{n + 1 + i}_2")

    # k=1 pointers for vertical order: ["(n+1)_2", "(n+1)_3", "(n+2)_2", "(n+2)_3", ...]
    pointer_k1 = []
    for i in range(m):
        pointer_k1.append(f"{n + 1 + i}_2")
        pointer_k1.append(f"{n + 1 + i}_3")

    if k == 0:
        return pointer_k0
    if k == 1:
        return pointer_k1

    # Normalize negative k to the positive equivalent (kept consistent with horizontal impl)
    if k < 0:
        k = 4 * (m + n) + k

    if k % 2 == 0:
        # Even k: shift LEFT by (k/2) on get_starting_order (see horizontal docstring examples)
        shift_steps = k // 2
        out = list(pointer_k0)
        for i in range(len(out)):
            # search the strand in the full_order (same break logic style as RH horizontal)
            for strand in full_order:
                if out[i] == strand:
                    shift_position = full_order.index(strand)
                    out[i] = full_order[(shift_position - shift_steps) % total_len]
                    break
        
    else:
        # Odd k: shift RIGHT by (k-1)/2 on get_starting_order_oposite_orientation
        shift_steps = (k - 1) // 2
        out = list(pointer_k1)
        for i in range(len(out)):
            # search the strand in the full_order_oposite_orientation (same break logic style as RH horizontal)
            for strand in full_order_oposite_orientation:
                if out[i] == strand:
                    shift_position = full_order_oposite_orientation.index(strand)
                    out[i] = full_order_oposite_orientation[(shift_position + shift_steps) % total_len]
                    break
    for i in range(len(out)):
        print(f"vertical_order_k[{i}]: {out[i]}")

    return out

def get_mask_order_k(m, n, k, direction):
    """
    From get_horizontal_order_k and get_vertical_order_k, get the mask order for a given k and direction.

    For even values of k, we pair odd indexes of get_vertical_order_k with even indexes of get_horizontal_order_k, and vice versa. 
    Example for 2x2 with k=0 cw, horizontal order is 1_2 1_3 2_2 2_3 and vertical order is 3_2 3_3 4_2 4_3, 
    so the mask order is 3_2_1_3 3_2_2_3 3_3_1_2 3_3_2_2 4_2_1_3 4_2_2_3 4_3_1_2 4_3_2_2.

    For odd values of k, we pair odd indexes of get_vertical_order_k with odd indexes of get_horizontal_order_k, and vice versa. Example for 2x2 with k=1 cw, horizontal order is 2_3 1_2 1_3 2_2 and vertical order is 4_3 3_2 3_3 4_2, so the mask order is 4_3_2_3 4_3_1_2 4_2_2_3 4_2_1_2 3_2_2_3 3_2_1_2 3_3_2_3 3_3_1_2.
    """
    horizontal_order_k = get_horizontal_order_k(m, n, k, direction)
    vertical_order_k = get_vertical_order_k(m, n, k, direction)

    if not horizontal_order_k or not vertical_order_k:
        return []

    #h_even is the even indexes of horizontal_order
    #h_odd is the odd indexes of horizontal_order
    h_even = [h for idx, h in enumerate(horizontal_order_k) if idx % 2 == 0]
    h_odd = [h for idx, h in enumerate(horizontal_order_k) if idx % 2 == 1]
    
    mask_order = []
    
    if k % 2 == 1:
        for idx, v in enumerate(vertical_order_k):
            target_h = h_even if idx % 2 == 0 else h_odd
            for h in target_h:
                mask_order.append(f"{v}_{h}")
    else:
        for idx, v in enumerate(vertical_order_k):
            target_h = h_odd if idx % 2 == 0 else h_even
            for h in target_h:
                mask_order.append(f"{v}_{h}")

    return mask_order


def compute_4_5_masks(base_strands, continuation_strands, m, n, k, direction):
    """
    Compute the masks for the _4 and _5 strands using get_mask_order_k.

    The mask order from get_mask_order_k gives pairings like "3_2_1_3"
    which means vertical strand 3_2 crosses horizontal strand 1_3.

    For _4/_5 strands:
    - _4 strands attach to _2 ends, so 3_2 → 3_4
    - _5 strands attach to _3 ends, so 1_3 → 1_5

    This creates masks like "3_4_1_5" for the continuation crossings.

    Returns:
        list: List of mask dictionaries with keys:
            - first_strand: layer name of first strand (vertical _4 or _5)
            - second_strand: layer name of second strand (horizontal _4 or _5)
            - layer_name: combined mask name
    """
    mask_order = get_mask_order_k(m, n, k, direction)

    print(f"\n=== Computing _4/_5 masks ===")
    print(f"Base mask order from get_mask_order_k: {mask_order}")

    # Build lookup for continuation strands by layer name
    strand_lookup = {s["layer_name"]: s for s in continuation_strands}

    masks_info = []

    for mask_entry in mask_order:
        # Parse the mask entry: "3_2_1_3" → vertical="3_2", horizontal="1_3"
        parts = mask_entry.split("_")
        if len(parts) != 4:
            print(f"  Warning: Invalid mask entry format: {mask_entry}")
            continue

        v_set = parts[0]
        v_suffix = parts[1]  # "2" or "3"
        h_set = parts[2]
        h_suffix = parts[3]  # "2" or "3"

        # Convert to _4 and _5
        # _2 → _4, _3 → _5
        v_new_suffix = "4" if v_suffix == "2" else "5"
        h_new_suffix = "4" if h_suffix == "2" else "5"

        v_layer = f"{v_set}_{v_new_suffix}"  # e.g., "3_4"
        h_layer = f"{h_set}_{h_new_suffix}"  # e.g., "1_5"

        # Check if strands exist
        v_strand = strand_lookup.get(v_layer)
        h_strand = strand_lookup.get(h_layer)

        if not v_strand or not h_strand:
            print(f"  Warning: Could not find strands {v_layer} and/or {h_layer}")
            continue

        mask_info = {
            "first_strand": v_layer,
            "second_strand": h_layer,
            "layer_name": f"{v_layer}_{h_layer}",
            "v_strand": v_strand,
            "h_strand": h_strand,
            "set_number": int(f"{v_set}{h_set}"),
        }
        masks_info.append(mask_info)
        print(f"  Mask: {mask_entry} -> {v_layer}_{h_layer}")

    print(f"Total _4/_5 mask pairs: {len(masks_info)}")
    return masks_info





def compute_emoji_pairings(strands, m, n, k, direction):
    """
    Compute which endpoints pair together based on emoji rotation.

    This must match EXACTLY how mxn_emoji_renderer assigns emojis:
    - The renderer considers BOTH start AND end of each _2/_3 strand
    - Endpoints are classified by strand DIRECTION (horizontal vs vertical)
    - Endpoints are sorted by perimeter position (clockwise from top-left)
    - Top/Right get unique labels, Bottom/Left mirror them
    - Rotation k shifts all labels around the perimeter
    - Each endpoint pairs with the OTHER endpoint that has the same emoji

    Returns:
        dict: {"{layer_name}_end": {"x": x, "y": y}, ...}
    """
    # Collect BOTH start and end of each _2/_3 strand (matching emoji renderer)
    all_endpoints = []

    for strand in strands:
        if strand["type"] != "AttachedStrand":
            continue

        layer_name = strand["layer_name"]
        if not (layer_name.endswith("_2") or layer_name.endswith("_3")):
            continue

        # Get both start and end positions
        start_x = strand["start"]["x"]
        start_y = strand["start"]["y"]
        end_x = strand["end"]["x"]
        end_y = strand["end"]["y"]

        dx = end_x - start_x
        dy = end_y - start_y

        # Classify endpoints by strand DIRECTION (same as emoji renderer)
        if abs(dx) >= abs(dy):
            # Horizontal strand
            if start_x <= end_x:
                start_side = "left"
                end_side = "right"
            else:
                start_side = "right"
                end_side = "left"
        else:
            # Vertical strand
            if start_y <= end_y:
                start_side = "top"
                end_side = "bottom"
            else:
                start_side = "bottom"
                end_side = "top"

        # Add START endpoint
        all_endpoints.append({
            "layer_name": layer_name,
            "endpoint_type": "start",
            "x": start_x,
            "y": start_y,
            "side": start_side,
            "set_number": strand["set_number"],
        })

        # Add END endpoint
        all_endpoints.append({
            "layer_name": layer_name,
            "endpoint_type": "end",
            "x": end_x,
            "y": end_y,
            "side": end_side,
            "set_number": strand["set_number"],
        })

    if not all_endpoints:
        return {}

    # Group endpoints by side
    top_eps = [ep for ep in all_endpoints if ep["side"] == "top"]
    right_eps = [ep for ep in all_endpoints if ep["side"] == "right"]
    bottom_eps = [ep for ep in all_endpoints if ep["side"] == "bottom"]
    left_eps = [ep for ep in all_endpoints if ep["side"] == "left"]

    # Sort by position (same as emoji renderer):
    # Top/Bottom: sort by X (left to right)
    # Left/Right: sort by Y (top to bottom)
    top_eps.sort(key=lambda ep: ep["x"])
    bottom_eps.sort(key=lambda ep: ep["x"])
    left_eps.sort(key=lambda ep: ep["y"])
    right_eps.sort(key=lambda ep: ep["y"])

    # Build perimeter order (clockwise from top-left):
    # top (L->R), right (T->B), bottom (R->L reversed), left (B->T reversed)
    perimeter_order = (
        top_eps +
        right_eps +
        list(reversed(bottom_eps)) +
        list(reversed(left_eps))
    )

    total = len(perimeter_order)
    if total == 0:
        return {}

    # Assign perimeter indices
    for idx, ep in enumerate(perimeter_order):
        ep["perimeter_index"] = idx

    # Build base labels with mirroring at k=0 (SAME AS EMOJI RENDERER)
    # Top and Right get unique labels
    # Bottom mirrors Top, Left mirrors Right
    top_count = len(top_eps)
    right_count = len(right_eps)
    bottom_count = len(bottom_eps)
    left_count = len(left_eps)

    # Unique labels for top and right
    top_labels = list(range(top_count))
    right_labels = list(range(top_count, top_count + right_count))

    # Mirror for bottom and left
    bottom_labels = list(reversed(top_labels[:bottom_count]))
    left_labels = list(reversed(right_labels[:left_count]))

    # Combine in perimeter order
    base_labels = top_labels + right_labels + bottom_labels + left_labels

    # Apply rotation k
    rotated_labels = rotate_labels(base_labels, k, direction)

    # Assign rotated labels to endpoints
    for idx, ep in enumerate(perimeter_order):
        ep["emoji_index"] = rotated_labels[idx]

    # Build pairing map: for each END endpoint, find where the matching emoji is
    # The _4 strand attaches to _2's END and goes to where the same emoji appears
    # The _5 strand attaches to _3's END and goes to where the same emoji appears
    pairings = {}
    for ep in perimeter_order:
        # Only build pairings for END endpoints (since _4/_5 attach to ends)
        if ep.get("endpoint_type") != "end":
            continue

        target_emoji = ep["emoji_index"]

        # Find the OTHER endpoint with the same emoji (any endpoint except this one)
        for other_ep in perimeter_order:
            # Skip self (same layer AND same endpoint type)
            if other_ep["layer_name"] == ep["layer_name"] and other_ep.get("endpoint_type") == ep.get("endpoint_type"):
                continue
            if other_ep["emoji_index"] == target_emoji:
                pairings[f"{ep['layer_name']}_end"] = {
                    "x": other_ep["x"],
                    "y": other_ep["y"],
                }
                break

    # Debug output
    print(f"\n=== Emoji Pairing Debug (k={k}, {direction}) ===")
    print(f"Top ({len(top_eps)}): {[(ep['layer_name'], ep.get('endpoint_type','?'), ep['emoji_index']) for ep in top_eps]}")
    print(f"Right ({len(right_eps)}): {[(ep['layer_name'], ep.get('endpoint_type','?'), ep['emoji_index']) for ep in right_eps]}")
    print(f"Bottom ({len(bottom_eps)}): {[(ep['layer_name'], ep.get('endpoint_type','?'), ep['emoji_index']) for ep in bottom_eps]}")
    print(f"Left ({len(left_eps)}): {[(ep['layer_name'], ep.get('endpoint_type','?'), ep['emoji_index']) for ep in left_eps]}")
    print(f"Pairings: {pairings}")
    print("=" * 50)

    return pairings


def rotate_labels(labels, k, direction):
    """
    Rotate labels by k positions.

    Args:
        labels: List of label indices
        k: Rotation amount
        direction: "cw" or "ccw"

    Returns:
        New list with rotated labels
    """
    n = len(labels)
    if n == 0:
        return labels

    # Normalize shift
    shift = k % n
    if shift < 0:
        shift += n

    # CCW is opposite of CW
    if direction == "ccw":
        shift = (n - shift) % n

    # Rotate: each label moves to position (i + shift) % n
    out = [None] * n
    for i in range(n):
        out[(i + shift) % n] = labels[i]

    return out


# =============================================================================
# PARALLEL ALIGNMENT FUNCTIONS
# =============================================================================

import math


def _build_k_based_strand_sets(m, n, k, direction):
    """
    Build the k-based horizontal and vertical _4/_5 strand name sets and order lists.

    Returns:
        (h_names_set, h_order_list, v_names_set, v_order_list)
    """
    h_order_23 = get_horizontal_order_k(m, n, k, direction)
    v_order_23 = get_vertical_order_k(m, n, k, direction)

    def convert_23_to_45(order_list):
        result = []
        for label in order_list:
            parts = label.split("_")
            new_suffix = "4" if parts[1] == "2" else "5"
            result.append(f"{parts[0]}_{new_suffix}")
        return result

    h_order = convert_23_to_45(h_order_23)
    v_order = convert_23_to_45(v_order_23)

    return set(h_order), h_order, set(v_order), v_order


def _normalize_angle_near_reference(angle_deg, ref_angle_deg):
    """Wrap an angle to the representation closest to the reference angle."""
    return ref_angle_deg + ((angle_deg - ref_angle_deg + 180.0) % 360.0 - 180.0)


def _compute_pair_angle_averages(pair_angles):
    """Return the uniform and Gaussian-weighted averages for the pair angles."""
    uniform_avg = sum(pair_angles) / len(pair_angles)
    num_pairs = len(pair_angles)
    if num_pairs == 1:
        return uniform_avg, pair_angles[0]

    sigma = max(num_pairs / 2.0, 1.0)
    center = num_pairs - 1
    weights = []
    for i in range(num_pairs):
        weights.append(math.exp(-0.5 * ((i - center) / sigma) ** 2))

    total_w = sum(weights)
    weights = [w / total_w for w in weights]
    gaussian_avg = sum(angle * weight for angle, weight in zip(pair_angles, weights))
    return uniform_avg, gaussian_avg


def _compute_pair_angle_range(sorted_strands, angle_mode="first_strand"):
    """
    Compute angle range from a sorted list of strand dicts.

    Modes:
        "first_strand"           : first strand angle ±20°
        "avg_gaussian"/"gaussian": use the uniform average and Gaussian average
                                    as the two bounds of the range
        "uniform"                : legacy behavior, average angle ±20°

    Returns (initial_angle, angle_min, angle_max, pair_angles_debug).
    """
    strand_angles = []
    for s in sorted_strands:
        dx = s["target"]["x"] - s["start"]["x"]
        dy = s["target"]["y"] - s["start"]["y"]
        strand_angles.append(math.degrees(math.atan2(dy, dx)))

    num = len(sorted_strands)
    pairs = []
    for i in range(num // 2):
        pairs.append((i, num - 1 - i))
    if num % 2 == 1:
        pairs.append((num // 2, None))

    ref_angle = strand_angles[0]
    pair_angles = []
    for left_idx, right_idx in pairs:
        left_angle = _normalize_angle_near_reference(strand_angles[left_idx], ref_angle)
        if right_idx is not None:
            right_angle = _normalize_angle_near_reference(strand_angles[right_idx], ref_angle)
            left_diff = abs(left_angle - ref_angle)
            right_diff = abs(right_angle - ref_angle)
            pair_angle = left_angle if left_diff <= right_diff else right_angle
        else:
            pair_angle = left_angle
            if abs(pair_angle - ref_angle) > 90:
                pair_angle -= 180.0
            pair_angle = _normalize_angle_near_reference(pair_angle, ref_angle)
        pair_angles.append(pair_angle)

    pair_debug = list(zip(
        [sorted_strands[left]["strand"]["layer_name"] for left, _ in pairs],
        [sorted_strands[right]["strand"]["layer_name"] if right is not None else "solo" for _, right in pairs],
        pair_angles
    ))

    if angle_mode == "first_strand":
        initial_angle = ref_angle
        return initial_angle, initial_angle - 20.0, initial_angle + 20.0, pair_debug

    uniform_avg, gaussian_avg = _compute_pair_angle_averages(pair_angles)

    if angle_mode == "uniform":
        return uniform_avg, uniform_avg - 20.0, uniform_avg + 20.0, pair_debug

    if angle_mode in ("avg_gaussian", "gaussian"):
        angle_min = min(uniform_avg, gaussian_avg)
        angle_max = max(uniform_avg, gaussian_avg)
        initial_angle = (uniform_avg + gaussian_avg) / 2.0
        return initial_angle, angle_min, angle_max, pair_debug

    initial_angle = ref_angle
    return initial_angle, initial_angle - 20.0, initial_angle + 20.0, pair_debug


def get_parallel_alignment_preview(all_strands, n, m, k=0, direction="cw", angle_mode="first_strand"):
    """
    Get preview information for parallel alignment angle ranges.
    Returns first/last strand positions and default angle ranges for both H and V.

    angle_mode: "first_strand" | "avg_gaussian"

    Returns:
        dict with:
            - horizontal: {first, last, initial_angle, angle_min, angle_max}
            - vertical: {first, last, initial_angle, angle_min, angle_max}
    """
    result = {"horizontal": None, "vertical": None}

    # Build k-based strand sets for correct grouping
    h_names_set, h_order_list, v_names_set, v_order_list = _build_k_based_strand_sets(m, n, k, direction)

    # Collect horizontal _4/_5 strands (k-based grouping)
    h_strands = []
    for strand in all_strands:
        if strand["type"] != "AttachedStrand":
            continue
        layer_name = strand["layer_name"]
        set_num = strand["set_number"]
        if layer_name not in h_names_set:
            continue
        if layer_name.endswith("_4") or layer_name.endswith("_5"):
            # Find the _2 or _3 strand this attaches to
            suffix = "_2" if layer_name.endswith("_4") else "_3"
            base_name = layer_name.rsplit("_", 1)[0] + suffix
            s2_3 = next((s for s in all_strands if s["layer_name"] == base_name), None)
            if s2_3:
                h_strands.append({
                    "strand": strand,
                    "strand_2_3": s2_3,
                    "set_number": set_num,
                    "start": {"x": strand["start"]["x"], "y": strand["start"]["y"]},
                    "target": {"x": strand["end"]["x"], "y": strand["end"]["y"]},
                })

    if len(h_strands) >= 2:
        # Sort by k-based order
        h_order_index = {name: i for i, name in enumerate(h_order_list)}
        h_strands.sort(key=lambda h: h_order_index.get(h["strand"]["layer_name"], 999))

        first_h = h_strands[0]
        last_h = h_strands[-1]

        print(f"\n--- Horizontal angle range (mode: {angle_mode}) ---")
        initial_angle, angle_min, angle_max, pair_debug = _compute_pair_angle_range(h_strands, angle_mode)
        for left_name, right_name, pa in pair_debug:
            print(f"    Pair ({left_name}, {right_name}): {pa:.1f}°")

        # Get full strand order
        strand_order = [h["strand"]["layer_name"] for h in h_strands]

        result["horizontal"] = {
            "first_start": first_h["start"],
            "first_target": first_h["target"],
            "last_start": last_h["start"],
            "last_target": last_h["target"],
            "initial_angle": initial_angle,
            "angle_min": angle_min,
            "angle_max": angle_max,
            "first_name": first_h["strand"]["layer_name"],
            "last_name": last_h["strand"]["layer_name"],
            "strand_order": strand_order,
        }

    # Collect vertical _4/_5 strands (k-based grouping)
    v_strands = []
    for strand in all_strands:
        if strand["type"] != "AttachedStrand":
            continue
        layer_name = strand["layer_name"]
        set_num = strand["set_number"]
        if layer_name not in v_names_set:
            continue
        if layer_name.endswith("_4") or layer_name.endswith("_5"):
            suffix = "_2" if layer_name.endswith("_4") else "_3"
            base_name = layer_name.rsplit("_", 1)[0] + suffix
            s2_3 = next((s for s in all_strands if s["layer_name"] == base_name), None)
            if s2_3:
                v_strands.append({
                    "strand": strand,
                    "strand_2_3": s2_3,
                    "set_number": set_num,
                    "start": {"x": strand["start"]["x"], "y": strand["start"]["y"]},
                    "target": {"x": strand["end"]["x"], "y": strand["end"]["y"]},
                })

    if len(v_strands) >= 2:
        # Sort by k-based order
        v_order_index = {name: i for i, name in enumerate(v_order_list)}
        v_strands.sort(key=lambda v: v_order_index.get(v["strand"]["layer_name"], 999))

        first_v = v_strands[0]
        last_v = v_strands[-1]

        print(f"\n--- Vertical angle range (mode: {angle_mode}) ---")
        initial_angle, angle_min, angle_max, pair_debug = _compute_pair_angle_range(v_strands, angle_mode)
        for left_name, right_name, pa in pair_debug:
            print(f"    Pair ({left_name}, {right_name}): {pa:.1f}°")

        # Get full strand order
        strand_order = [v["strand"]["layer_name"] for v in v_strands]

        result["vertical"] = {
            "first_start": first_v["start"],
            "first_target": first_v["target"],
            "last_start": last_v["start"],
            "last_target": last_v["target"],
            "initial_angle": initial_angle,
            "angle_min": angle_min,
            "angle_max": angle_max,
            "first_name": first_v["strand"]["layer_name"],
            "last_name": last_v["strand"]["layer_name"],
            "strand_order": strand_order,
        }

    return result


# ---------------------------------------------------------------------------
# GPU (CuPy) chunked combo search
# ---------------------------------------------------------------------------

def _check_cupy_available():
    """Check if CuPy is installed and a CUDA GPU is available."""
    try:
        import cupy as cp
        cp.cuda.Device(0).compute_capability
        return True
    except Exception:
        return False


def _cupy_search_combo_chunks(strands_list, pairs, pair_directions, pair_originals,
                               first_strand, ext_range_values, angle_step_degrees,
                               max_extension, strand_width,
                               custom_angle_min, custom_angle_max,
                               angle_mode="first_strand",
                               on_config_callback=None,
                               chunk_size=2048,
                               direction_type="horizontal",
                               allow_inner_extensions=True):
    """
    GPU-accelerated combo search using CuPy.  Replaces the itertools.product
    loop, processing *chunk_size* extension combos at a time on the GPU.

    Returns:
        (all_valid_results, best_fallback_info)
        - all_valid_results: list of valid result dicts (same schema as numpy path)
        - best_fallback_info: dict with best fallback or None
    """
    import cupy as cp
    import numpy as np

    S = len(strands_list)
    P = len(pairs)
    R = len(ext_range_values)
    total_combos = R ** P

    min_gap = strand_width + 10
    max_gap_val = strand_width * 1.5

    # --- Pre-extract strand data into numpy arrays ---
    orig_x = np.array([s["original_start"]["x"] for s in strands_list], dtype=np.float32)
    orig_y = np.array([s["original_start"]["y"] for s in strands_list], dtype=np.float32)
    tgt_x = np.array([s["target_position"]["x"] for s in strands_list], dtype=np.float32)
    tgt_y = np.array([s["target_position"]["y"] for s in strands_list], dtype=np.float32)

    s23_nx = np.zeros(S, dtype=np.float32)
    s23_ny = np.zeros(S, dtype=np.float32)
    for i, s in enumerate(strands_list):
        s23 = s["strand_2_3"]
        dx = s23["end"]["x"] - s23["start"]["x"]
        dy = s23["end"]["y"] - s23["start"]["y"]
        length = math.sqrt(dx * dx + dy * dy)
        if length > 0.001:
            s23_nx[i] = dx / length
            s23_ny[i] = dy / length

    # --- Build strand-to-pair mapping ---
    # For each strand, which pair index and which pair direction to use
    strand_pair_idx = np.zeros(S, dtype=np.int32)
    strand_pair_orig_x = np.zeros(S, dtype=np.float32)
    strand_pair_orig_y = np.zeros(S, dtype=np.float32)
    strand_pair_dir_nx = np.zeros(S, dtype=np.float32)
    strand_pair_dir_ny = np.zeros(S, dtype=np.float32)

    # Map strand objects to their index in strands_list
    strand_id_map = {id(s): i for i, s in enumerate(strands_list)}
    pair_left_idx = []
    pair_right_idx = []
    pair_has_right = []

    for pair_idx, (left_strand, right_strand) in enumerate(pairs):
        l_nx, l_ny, r_nx, r_ny = pair_directions[pair_idx]
        l_orig, r_orig = pair_originals[pair_idx]

        left_si = strand_id_map.get(id(left_strand))
        pair_left_idx.append(left_si if left_si is not None else -1)
        if left_si is not None:
            strand_pair_idx[left_si] = pair_idx
            strand_pair_orig_x[left_si] = l_orig["x"]
            strand_pair_orig_y[left_si] = l_orig["y"]
            strand_pair_dir_nx[left_si] = l_nx
            strand_pair_dir_ny[left_si] = l_ny

        if right_strand is not None:
            right_si = strand_id_map.get(id(right_strand))
            pair_right_idx.append(right_si if right_si is not None else -1)
            pair_has_right.append(True)
            if right_si is not None:
                strand_pair_idx[right_si] = pair_idx
                strand_pair_orig_x[right_si] = r_orig["x"]
                strand_pair_orig_y[right_si] = r_orig["y"]
                strand_pair_dir_nx[right_si] = r_nx
                strand_pair_dir_ny[right_si] = r_ny
        else:
            pair_right_idx.append(-1)
            pair_has_right.append(False)

    # --- Transfer constants to GPU ---
    tgt_x_gpu = cp.asarray(tgt_x)
    tgt_y_gpu = cp.asarray(tgt_y)
    s23_nx_gpu = cp.asarray(s23_nx)
    s23_ny_gpu = cp.asarray(s23_ny)
    spi_gpu = cp.asarray(strand_pair_idx)
    sp_orig_x_gpu = cp.asarray(strand_pair_orig_x)
    sp_orig_y_gpu = cp.asarray(strand_pair_orig_y)
    sp_dir_nx_gpu = cp.asarray(strand_pair_dir_nx)
    sp_dir_ny_gpu = cp.asarray(strand_pair_dir_ny)

    ext_range_gpu = cp.asarray(np.array(ext_range_values, dtype=np.float32))
    if allow_inner_extensions:
        inner_ext_cpu = np.arange(0, max_extension + 1, 5, dtype=np.float32)
    else:
        inner_ext_cpu = np.array([0.0], dtype=np.float32)
    inner_ext_gpu = cp.asarray(inner_ext_cpu)
    E = len(inner_ext_cpu)

    use_custom = custom_angle_min is not None and custom_angle_max is not None
    if use_custom:
        angle_values_cpu = np.arange(
            custom_angle_min,
            custom_angle_max + angle_step_degrees / 2,
            angle_step_degrees,
            dtype=np.float32,
        )
        angle_values_gpu = cp.asarray(angle_values_cpu)
    else:
        angle_values_cpu = None
        angle_values_gpu = None
    gaussian_weights_gpu = None
    if P > 1:
        sigma = max(P / 2.0, 1.0)
        center = P - 1
        gaussian_weights_cpu = np.array(
            [math.exp(-0.5 * ((i - center) / sigma) ** 2) for i in range(P)],
            dtype=np.float32,
        )
        gaussian_weights_cpu /= gaussian_weights_cpu.sum()
        gaussian_weights_gpu = cp.asarray(gaussian_weights_cpu)

    # Sign flip for alternating gap indices
    sign_flip_cpu = np.ones(max(S - 1, 1), dtype=np.float32)
    sign_flip_cpu[1::2] = -1.0
    sign_flip_gpu = cp.asarray(sign_flip_cpu)

    all_valid_results = []
    best_fallback_worst_gap = -float('inf')
    best_fallback_info = None

    first_strand_idx = 0  # first strand in strands_list

    print(f"\n--- GPU chunked search: {total_combos} combos, chunk_size={chunk_size}, "
          f"S={S}, E={E}, angle_mode={angle_mode} ---")

    for chunk_start in range(0, total_combos, chunk_size):
        chunk_end = min(chunk_start + chunk_size, total_combos)
        C = chunk_end - chunk_start

        # --- Step 1: Decode combo indices into per-pair extensions ---
        combo_flat = cp.arange(chunk_start, chunk_end, dtype=cp.int64)
        combo_ext_idx = cp.zeros((C, P), dtype=cp.int32)
        temp = combo_flat.copy()
        for p in range(P):
            combo_ext_idx[:, p] = (temp % R).astype(cp.int32)
            temp //= R
        combo_ext = ext_range_gpu[combo_ext_idx]  # (C, P)

        # --- Step 2: Compute shifted strand starts ---
        # combo_ext[:, strand_pair_idx[s]] gives extension for strand s's pair
        pair_ext_per_strand = combo_ext[:, spi_gpu]  # (C, S)
        shifted_x = sp_orig_x_gpu[None, :] + pair_ext_per_strand * sp_dir_nx_gpu[None, :]  # (C, S)
        shifted_y = sp_orig_y_gpu[None, :] + pair_ext_per_strand * sp_dir_ny_gpu[None, :]

        # --- Step 3: Base angles and search ranges per combo ---
        first_dx = tgt_x_gpu[first_strand_idx] - shifted_x[:, first_strand_idx]  # (C,)
        first_dy = tgt_y_gpu[first_strand_idx] - shifted_y[:, first_strand_idx]
        base_angle_rad = cp.arctan2(first_dy, first_dx)  # (C,)
        base_angle_deg = cp.rad2deg(base_angle_rad)

        dx_to_tgt = tgt_x_gpu[None, :] - shifted_x  # (C, S)
        dy_to_tgt = tgt_y_gpu[None, :] - shifted_y

        if use_custom:
            angle_min_deg = cp.full((C,), np.float32(custom_angle_min), dtype=cp.float32)
            angle_max_deg = cp.full((C,), np.float32(custom_angle_max), dtype=cp.float32)
            A = len(angle_values_cpu)
            angles_rad = cp.broadcast_to(cp.deg2rad(angle_values_gpu)[None, :], (C, A))
            angle_range_mask = cp.ones((C, A), dtype=cp.bool_)
        else:
            if angle_mode == "first_strand":
                angle_min_deg = base_angle_deg - np.float32(20.0)
                angle_max_deg = base_angle_deg + np.float32(20.0)
            else:
                strand_angle_deg = cp.rad2deg(cp.arctan2(dy_to_tgt, dx_to_tgt))
                ref_angle_deg = strand_angle_deg[:, first_strand_idx]
                pair_angle_columns = []
                for pair_idx in range(P):
                    left_angle = ref_angle_deg + cp.mod(
                        strand_angle_deg[:, pair_left_idx[pair_idx]] - ref_angle_deg + np.float32(180.0),
                        np.float32(360.0),
                    ) - np.float32(180.0)
                    if pair_has_right[pair_idx]:
                        right_angle = ref_angle_deg + cp.mod(
                            strand_angle_deg[:, pair_right_idx[pair_idx]] - ref_angle_deg + np.float32(180.0),
                            np.float32(360.0),
                        ) - np.float32(180.0)
                        left_diff = cp.abs(left_angle - ref_angle_deg)
                        right_diff = cp.abs(right_angle - ref_angle_deg)
                        pair_angle = cp.where(left_diff <= right_diff, left_angle, right_angle)
                    else:
                        pair_angle = cp.where(
                            cp.abs(left_angle - ref_angle_deg) > np.float32(90.0),
                            left_angle - np.float32(180.0),
                            left_angle,
                        )
                        pair_angle = ref_angle_deg + cp.mod(
                            pair_angle - ref_angle_deg + np.float32(180.0),
                            np.float32(360.0),
                        ) - np.float32(180.0)
                    pair_angle_columns.append(pair_angle)

                pair_angles_deg = cp.stack(pair_angle_columns, axis=1)
                uniform_avg = cp.mean(pair_angles_deg, axis=1)

                if angle_mode == "uniform":
                    angle_min_deg = uniform_avg - np.float32(20.0)
                    angle_max_deg = uniform_avg + np.float32(20.0)
                else:
                    if P == 1:
                        gaussian_avg = pair_angles_deg[:, 0]
                    else:
                        gaussian_avg = cp.sum(pair_angles_deg * gaussian_weights_gpu[None, :], axis=1)
                    angle_min_deg = cp.minimum(uniform_avg, gaussian_avg)
                    angle_max_deg = cp.maximum(uniform_avg, gaussian_avg)

            chunk_angle_min = float(cp.min(angle_min_deg).get())
            chunk_angle_max = float(cp.max(angle_max_deg).get())
            angle_values_cpu = np.arange(
                chunk_angle_min,
                chunk_angle_max + angle_step_degrees / 2,
                angle_step_degrees,
                dtype=np.float32,
            )
            angle_values_gpu = cp.asarray(angle_values_cpu)
            A = len(angle_values_cpu)
            angles_rad = cp.broadcast_to(cp.deg2rad(angle_values_gpu)[None, :], (C, A))
            angle_range_mask = (
                angle_values_gpu[None, :] >= angle_min_deg[:, None] - np.float32(1e-4)
            ) & (
                angle_values_gpu[None, :] <= angle_max_deg[:, None] + np.float32(1e-4)
            )

        # --- Step 4: goes_positive per combo per strand ---
        ref_cos = cp.cos(base_angle_rad)[:, None]
        ref_sin = cp.sin(base_angle_rad)[:, None]
        goes_positive = (dx_to_tgt * ref_cos + dy_to_tgt * ref_sin) >= 0  # (C, S)

        # --- Step 5: Strand angles ---
        strand_angles = cp.where(
            goes_positive[:, :, None],
            angles_rad[:, None, :],
            angles_rad[:, None, :] + cp.float32(math.pi)
        )  # (C, S, A)
        cos_sa = cp.cos(strand_angles)
        sin_sa = cp.sin(strand_angles)

        # --- Step 6: Inner extensions and projections ---
        ext_starts_x = shifted_x[:, :, None] + inner_ext_gpu[None, None, :] * s23_nx_gpu[None, :, None]  # (C, S, E)
        ext_starts_y = shifted_y[:, :, None] + inner_ext_gpu[None, None, :] * s23_ny_gpu[None, :, None]

        dx_ext = tgt_x_gpu[None, :, None] - ext_starts_x  # (C, S, E)
        dy_ext = tgt_y_gpu[None, :, None] - ext_starts_y

        # proj[c, s, e, a]
        proj = (dx_ext[:, :, :, None] * cos_sa[:, :, None, :] +
                dy_ext[:, :, :, None] * sin_sa[:, :, None, :])  # (C, S, E, A)

        # --- Step 7: First valid extension per (c, s, a) ---
        valid_proj = proj > 10
        has_any_valid = cp.any(valid_proj, axis=2)  # (C, S, A)
        all_strands_valid = cp.all(has_any_valid, axis=1) & angle_range_mask  # (C, A)
        first_valid_ext_idx = cp.argmax(valid_proj.astype(cp.int8), axis=2)  # (C, S, A)

        if S == 2:
            # --- 2-strand special case: ext1 x ext2 gap matrix ---
            chunk_fallback = _cupy_2strand_chunk(
                C, A, E, S, P, R,
                ext_starts_x, ext_starts_y, proj, cos_sa, sin_sa,
                inner_ext_gpu, inner_ext_cpu, combo_ext,
                min_gap, max_gap_val, strand_width,
                goes_positive, angles_rad, angle_range_mask, angle_min_deg, angle_max_deg,
                strands_list, pairs, pair_directions, pair_originals,
                all_valid_results, on_config_callback, direction_type,
                chunk_start, total_combos,
            )
            if chunk_fallback:
                fallback_worst_gap = chunk_fallback.get("worst_gap", 0)
                if fallback_worst_gap > best_fallback_worst_gap:
                    best_fallback_worst_gap = fallback_worst_gap
                    best_fallback_info = chunk_fallback
        else:
            # --- 3+ strand gap computation ---
            # Gather chosen positions at first valid extension
            c_3d = cp.broadcast_to(cp.arange(C, dtype=cp.int32)[:, None, None], (C, S, A))
            s_3d = cp.broadcast_to(cp.arange(S, dtype=cp.int32)[None, :, None], (C, S, A))
            a_3d = cp.broadcast_to(cp.arange(A, dtype=cp.int32)[None, None, :], (C, S, A))

            chosen_ext_x = ext_starts_x[c_3d, s_3d, first_valid_ext_idx]  # (C, S, A)
            chosen_ext_y = ext_starts_y[c_3d, s_3d, first_valid_ext_idx]
            chosen_length = proj[c_3d, s_3d, first_valid_ext_idx, a_3d]  # (C, S, A)

            chosen_end_x = chosen_ext_x + chosen_length * cos_sa
            chosen_end_y = chosen_ext_y + chosen_length * sin_sa

            ldx = chosen_end_x - chosen_ext_x
            ldy = chosen_end_y - chosen_ext_y
            lc = chosen_end_x * chosen_ext_y - chosen_end_y * chosen_ext_x
            ll = cp.sqrt(ldx ** 2 + ldy ** 2)
            inv_ll = cp.where(ll > 0.001, 1.0 / ll, cp.float32(0.0))

            # Signed gaps between consecutive strands: (C, S-1, A)
            signed_gaps = (ldy[:, :-1, :] * chosen_ext_x[:, 1:, :] +
                           (-ldx[:, :-1, :]) * chosen_ext_y[:, 1:, :] +
                           lc[:, :-1, :]) * inv_ll[:, :-1, :]
            signed_gaps = signed_gaps * sign_flip_gpu[None, :S - 1, None]

            abs_gaps = cp.abs(signed_gaps)

            # Direction consistency
            last_sg = (ldy[:, 0, :] * chosen_ext_x[:, -1, :] +
                       (-ldx[:, 0, :]) * chosen_ext_y[:, -1, :] +
                       lc[:, 0, :]) * inv_ll[:, 0, :]
            expected_sign = cp.where(last_sg >= 0, cp.float32(1.0), cp.float32(-1.0))

            dirs_ok = cp.where(
                expected_sign[:, None, :] > 0,
                signed_gaps > 0,
                signed_gaps < 0
            )
            all_dirs_ok = cp.all(dirs_ok, axis=1)  # (C, A)

            # Gap range validation
            gaps_in_range = (abs_gaps >= min_gap) & (abs_gaps <= max_gap_val)
            all_gaps_in_range = cp.all(gaps_in_range, axis=1)  # (C, A)

            # Combined validity
            valid_lines = cp.all(ll > 0.001, axis=1)  # (C, A)
            valid_mask = all_strands_valid & all_dirs_ok & all_gaps_in_range & valid_lines

            # Ranking metrics
            avg_gap = cp.mean(abs_gaps, axis=1)  # (C, A)
            gap_var = cp.var(abs_gaps, axis=1)
            first_last_dist = cp.abs(last_sg)

            # --- Extract valid results to CPU ---
            valid_indices = cp.where(valid_mask)
            valid_c = valid_indices[0].get()
            valid_a = valid_indices[1].get()

            if len(valid_c) > 0:
                # For each valid (c, a), pick the best angle per combo
                # (smallest first_last_dist, then gap_var)
                fld_cpu = first_last_dist[valid_indices[0], valid_indices[1]].get()
                gv_cpu = gap_var[valid_indices[0], valid_indices[1]].get()
                avg_gap_cpu = avg_gap[valid_indices[0], valid_indices[1]].get()
                angles_cpu = angles_rad[valid_indices[0], valid_indices[1]].get()
                ext_idx_cpu = first_valid_ext_idx.get()
                goes_pos_cpu = goes_positive.get()
                combo_ext_cpu = combo_ext.get()
                shifted_x_cpu = shifted_x.get()
                shifted_y_cpu = shifted_y.get()

                # Group by combo and pick best angle per combo
                unique_combos = np.unique(valid_c)
                for uc in unique_combos:
                    mask = valid_c == uc
                    indices = np.where(mask)[0]
                    # Pick best by (first_last_dist, gap_var)
                    best_vi = indices[0]
                    best_fld = fld_cpu[best_vi]
                    best_gv = gv_cpu[best_vi]
                    for vi in indices[1:]:
                        if (fld_cpu[vi], gv_cpu[vi]) < (best_fld, best_gv):
                            best_vi = vi
                            best_fld = fld_cpu[vi]
                            best_gv = gv_cpu[vi]

                    c_idx = valid_c[best_vi]
                    a_idx = valid_a[best_vi]
                    angle_rad_val = float(angles_cpu[best_vi])
                    angle_deg_val = float(np.degrees(angle_rad_val))

                    configs = []
                    for si in range(S):
                        ext_val = float(inner_ext_cpu[ext_idx_cpu[c_idx, si, a_idx]])
                        gp = bool(goes_pos_cpu[c_idx, si])
                        cfg = _build_config_dict(
                            strands_list[si],
                            ext_val,
                            angle_rad_val,
                            gp,
                            original_start_override={
                                "x": float(shifted_x_cpu[c_idx, si]),
                                "y": float(shifted_y_cpu[c_idx, si]),
                            },
                        )
                        if cfg is None:
                            break
                        configs.append(cfg)
                    else:
                        # Recompute gaps with Python for accuracy
                        py_gaps = []
                        py_signed = []
                        py_line_params = [precompute_line_params(c["extended_start"], c["end"]) for c in configs]
                        for i in range(len(configs) - 1):
                            sg = fast_perpendicular_distance(
                                py_line_params[i],
                                configs[i + 1]["extended_start"]["x"],
                                configs[i + 1]["extended_start"]["y"]
                            )
                            if i % 2 == 1:
                                sg = -sg
                            py_signed.append(sg)
                            py_gaps.append(abs(sg))

                        pair_exts = tuple(int(combo_ext_cpu[c_idx, p]) for p in range(P))

                        result = {
                            "valid": True,
                            "configurations": configs,
                            "gaps": py_gaps,
                            "signed_gaps": py_signed,
                            "gap_variance": float(np.var(py_gaps)) if py_gaps else 0,
                            "average_gap": float(np.mean(py_gaps)) if py_gaps else 0,
                            "worst_gap": min(py_gaps) if py_gaps else 0,
                            "angle": angle_rad_val,
                            "angle_degrees": angle_deg_val,
                            "min_gap": min_gap,
                            "max_gap": max_gap_val,
                            "first_last_distance": float(best_fld),
                            "pair_extensions": pair_exts,
                        }
                        all_valid_results.append(result)

                        if on_config_callback:
                            on_config_callback(angle_deg_val, pair_exts, result, direction_type)

            # --- Fallback tracking for invalid combos ---
            invalid_mask = ~valid_mask & all_strands_valid & all_dirs_ok & valid_lines
            if cp.any(invalid_mask):
                worst_per_ca = cp.min(abs_gaps, axis=1)  # (C, A)
                worst_per_ca = cp.where(invalid_mask, worst_per_ca, cp.float32(-1e9))
                best_fb_flat = int(cp.argmax(worst_per_ca))
                best_fb_c = best_fb_flat // A
                best_fb_a = best_fb_flat % A
                fb_worst = float(worst_per_ca[best_fb_c, best_fb_a])

                if fb_worst > best_fallback_worst_gap:
                    best_fallback_worst_gap = fb_worst
                    fb_angle_rad = float(angles_rad[best_fb_c, best_fb_a].get())
                    fb_angle_deg = float(np.degrees(fb_angle_rad))
                    fb_ext_idx = first_valid_ext_idx[best_fb_c, :, best_fb_a].get()
                    fb_combo_ext = combo_ext[best_fb_c].get()
                    fb_shifted_x = shifted_x[best_fb_c].get()
                    fb_shifted_y = shifted_y[best_fb_c].get()

                    fb_configs = []
                    for si in range(S):
                        ext_val = float(inner_ext_cpu[fb_ext_idx[si]])
                        original_start_override = {
                            "x": float(fb_shifted_x[si]),
                            "y": float(fb_shifted_y[si]),
                        }
                        cfg = _build_config_dict(
                            strands_list[si],
                            ext_val,
                            fb_angle_rad,
                            _compute_goes_positive_for_angle(
                                original_start_override,
                                strands_list[si]["target_position"],
                                fb_angle_rad,
                            ),
                            original_start_override=original_start_override,
                        )
                        if cfg:
                            fb_configs.append(cfg)

                    if len(fb_configs) == S:
                        fb_lp = [precompute_line_params(c["extended_start"], c["end"]) for c in fb_configs]
                        fb_gaps = []
                        fb_sg = []
                        for i in range(S - 1):
                            sg = fast_perpendicular_distance(
                                fb_lp[i],
                                fb_configs[i + 1]["extended_start"]["x"],
                                fb_configs[i + 1]["extended_start"]["y"]
                            )
                            if i % 2 == 1:
                                sg = -sg
                            fb_sg.append(sg)
                            fb_gaps.append(abs(sg))

                        best_fallback_info = {
                            "configurations": fb_configs,
                            "gaps": fb_gaps,
                            "signed_gaps": fb_sg,
                            "gap_variance": float(np.var(fb_gaps)) if fb_gaps else 0,
                            "average_gap": float(np.mean(fb_gaps)) if fb_gaps else 0,
                            "worst_gap": min(fb_gaps) if fb_gaps else 0,
                            "angle": fb_angle_rad,
                            "angle_degrees": fb_angle_deg,
                            "min_gap": min_gap,
                            "max_gap": max_gap_val,
                            "pair_extensions": tuple(int(fb_combo_ext[p]) for p in range(P)),
                            "directions_valid": True,
                        }

        if (chunk_start // chunk_size) % 10 == 0:
            print(f"  GPU chunk {chunk_start // chunk_size + 1}/"
                  f"{(total_combos + chunk_size - 1) // chunk_size}: "
                  f"{len(all_valid_results)} valid so far")

    print(f"  GPU search complete: {len(all_valid_results)} valid results, "
          f"fallback={'yes' if best_fallback_info else 'no'}")
    return all_valid_results, best_fallback_info


def _cupy_2strand_chunk(C, A, E, S, P, R,
                         ext_starts_x, ext_starts_y, proj, cos_sa, sin_sa,
                         inner_ext_gpu, inner_ext_cpu, combo_ext,
                         min_gap, max_gap_val, strand_width,
                         goes_positive, angles_rad, angle_range_mask, angle_min_deg, angle_max_deg,
                         strands_list, pairs, pair_directions, pair_originals,
                         all_valid_results, on_config_callback, direction_type,
                         chunk_start, total_combos):
    """Handle the 2-strand special case on GPU for a chunk."""
    import cupy as cp
    import numpy as np

    # proj[:, 0, :, :] is strand 0 projections: (C, E, A)
    # proj[:, 1, :, :] is strand 1 projections: (C, E, A)
    proj0 = proj[:, 0, :, :]  # (C, E, A)
    proj1 = proj[:, 1, :, :]

    valid_e1 = proj0 > 10  # (C, E, A)
    valid_e2 = proj1 > 10

    # Line params for strand 0 at each (c, e1, a)
    ext1_sx = ext_starts_x[:, 0, :]  # (C, E)
    ext1_sy = ext_starts_y[:, 0, :]
    ext1_end_x = ext1_sx[:, :, None] + proj0 * cos_sa[:, 0:1, None, :].squeeze(1)[:, None, :]
    # Simpler: cos_sa[:, 0, :] is (C, A)
    cos0 = cos_sa[:, 0, :]  # (C, A)
    sin0 = sin_sa[:, 0, :]

    # ext1_end_x[c, e1, a] = ext1_sx[c, e1] + proj0[c, e1, a] * cos0[c, a]
    ext1_end_x = ext1_sx[:, :, None] + proj0 * cos0[:, None, :]  # (C, E, A)
    ext1_end_y = ext1_sy[:, :, None] + proj0 * sin0[:, None, :]

    ldx1 = ext1_end_x - ext1_sx[:, :, None]  # (C, E, A)
    ldy1 = ext1_end_y - ext1_sy[:, :, None]
    lc1 = ext1_end_x * ext1_sy[:, :, None] - ext1_end_y * ext1_sx[:, :, None]
    ll1 = cp.sqrt(ldx1 ** 2 + ldy1 ** 2)
    valid_ll1 = ll1 > 0.001
    inv_ll1 = cp.where(valid_ll1, 1.0 / ll1, cp.float32(0.0))

    # Strand 1 extended start points
    ext2_x = ext_starts_x[:, 1, :]  # (C, E)
    ext2_y = ext_starts_y[:, 1, :]

    # Gap matrix: (C, E1, E2, A)
    # gap[c,e1,e2,a] = |ldy1[c,e1,a]*ext2_x[c,e2] + (-ldx1[c,e1,a])*ext2_y[c,e2] + lc1[c,e1,a]| * inv_ll1[c,e1,a]
    gap_matrix = cp.abs(
        ldy1[:, :, None, :] * ext2_x[:, None, :, None] +
        (-ldx1[:, :, None, :]) * ext2_y[:, None, :, None] +
        lc1[:, :, None, :]
    ) * inv_ll1[:, :, None, :]  # (C, E1, E2, A)

    # Validity: both exts valid, line valid, gap in range
    valid_2s = (valid_e1[:, :, None, :] & valid_e2[:, None, :, :] &
                valid_ll1[:, :, None, :] &
                angle_range_mask[:, None, None, :] &
                (gap_matrix >= min_gap) & (gap_matrix <= max_gap_val))

    # Find smallest gap per combo (flatten E1, E2, A)
    gap_ranked = cp.where(valid_2s, gap_matrix, cp.float32(float('inf')))
    gap_flat = gap_ranked.reshape(C, -1)  # (C, E1*E2*A)
    best_flat_idx = cp.argmin(gap_flat, axis=1)  # (C,)
    best_gap_val_arr = gap_flat[cp.arange(C, dtype=cp.int32), best_flat_idx]
    combo_has_valid = best_gap_val_arr < 1e30

    # Transfer valid combos to CPU
    valid_combo_mask = combo_has_valid.get()
    if not np.any(valid_combo_mask):
        valid_combo_indices = np.array([], dtype=np.int32)
    else:
        valid_combo_indices = np.where(valid_combo_mask)[0]

    best_flat_cpu = best_flat_idx.get()
    combo_ext_cpu = combo_ext.get()
    goes_pos_cpu = goes_positive.get()
    angles_rad_cpu = angles_rad.get()
    angle_min_cpu = angle_min_deg.get()
    angle_max_cpu = angle_max_deg.get()
    shifted_x_cpu = ext_starts_x[:, :, 0].get()
    shifted_y_cpu = ext_starts_y[:, :, 0].get()

    for vc in valid_combo_indices:
        flat_idx = int(best_flat_cpu[vc])
        e1_idx = flat_idx // (E * A)
        remainder = flat_idx % (E * A)
        e2_idx = remainder // A
        a_idx = remainder % A

        ext1_val = float(inner_ext_cpu[e1_idx])
        ext2_val = float(inner_ext_cpu[e2_idx])
        angle_rad_val = float(angles_rad_cpu[vc, a_idx])
        angle_deg_val = float(np.degrees(angle_rad_val))

        cfg1 = _build_config_dict(
            strands_list[0],
            ext1_val,
            angle_rad_val,
            bool(goes_pos_cpu[vc, 0]),
            original_start_override={
                "x": float(shifted_x_cpu[vc, 0]),
                "y": float(shifted_y_cpu[vc, 0]),
            },
        )
        cfg2 = _build_config_dict(
            strands_list[1],
            ext2_val,
            angle_rad_val,
            bool(goes_pos_cpu[vc, 1]),
            original_start_override={
                "x": float(shifted_x_cpu[vc, 1]),
                "y": float(shifted_y_cpu[vc, 1]),
            },
        )

        if cfg1 and cfg2:
            lp = precompute_line_params(cfg1["extended_start"], cfg1["end"])
            sg = fast_perpendicular_distance(lp, cfg2["extended_start"]["x"], cfg2["extended_start"]["y"])

            pair_exts = tuple(int(combo_ext_cpu[vc, p]) for p in range(P))

            result = {
                "valid": True,
                "configurations": [cfg1, cfg2],
                "gaps": [abs(sg)],
                "signed_gaps": [sg],
                "gap_variance": 0,
                "average_gap": abs(sg),
                "worst_gap": abs(sg),
                "angle": angle_rad_val,
                "angle_degrees": angle_deg_val,
                "min_gap": min_gap,
                "max_gap": max_gap_val,
                "first_last_distance": abs(sg),
                "pair_extensions": pair_exts,
            }
            all_valid_results.append(result)

            if on_config_callback:
                on_config_callback(angle_deg_val, pair_exts, result, direction_type)

    invalid_combo_indices = np.where(~valid_combo_mask)[0]
    if len(invalid_combo_indices) == 0:
        return None

    best_fallback_info = None
    best_fallback_gap = -float('inf')

    for ic in invalid_combo_indices:
        angle_deg_val = 0.5 * float(angle_min_cpu[ic] + angle_max_cpu[ic])
        angle_rad_val = math.radians(angle_deg_val)
        pair_exts = tuple(int(combo_ext_cpu[ic, p]) for p in range(P))

        original_start_1 = {
            "x": float(shifted_x_cpu[ic, 0]),
            "y": float(shifted_y_cpu[ic, 0]),
        }
        original_start_2 = {
            "x": float(shifted_x_cpu[ic, 1]),
            "y": float(shifted_y_cpu[ic, 1]),
        }
        cfg1 = _build_config_dict(
            strands_list[0],
            0.0,
            angle_rad_val,
            _compute_goes_positive_for_angle(
                original_start_1,
                strands_list[0]["target_position"],
                angle_rad_val,
            ),
            original_start_override=original_start_1,
        )
        cfg2 = _build_config_dict(
            strands_list[1],
            0.0,
            angle_rad_val,
            _compute_goes_positive_for_angle(
                original_start_2,
                strands_list[1]["target_position"],
                angle_rad_val,
            ),
            original_start_override=original_start_2,
        )
        if not cfg1 or not cfg2:
            continue

        line_params = precompute_line_params(cfg1["extended_start"], cfg1["end"])
        signed_gap = fast_perpendicular_distance(
            line_params,
            cfg2["extended_start"]["x"],
            cfg2["extended_start"]["y"],
        )
        abs_gap = abs(signed_gap)

        if abs_gap > best_fallback_gap:
            best_fallback_gap = abs_gap
            best_fallback_info = {
                "configurations": [cfg1, cfg2],
                "gaps": [abs_gap],
                "signed_gaps": [signed_gap],
                "gap_variance": 0,
                "average_gap": abs_gap,
                "worst_gap": abs_gap,
                "angle": angle_rad_val,
                "angle_degrees": angle_deg_val,
                "min_gap": min_gap,
                "max_gap": max_gap_val,
                "pair_extensions": pair_exts,
                "directions_valid": True,
            }

    return best_fallback_info


def _numpy_try_all_angles(strands_list, angles_deg, max_extension, strand_width, allow_inner_extensions=True):
    """
    Numpy-accelerated batch angle search. Tests ALL angles at once for a given
    set of strand start positions.

    For each angle, finds per-strand extensions and checks gap validity.
    Returns the best valid angle result, or None.

    This replaces the inner angle loop from the original code, giving ~40x speedup.
    """
    import numpy as np

    num_strands = len(strands_list)
    if num_strands < 2:
        return None

    min_gap = strand_width + 10
    max_gap = strand_width * 1.5
    ideal_gap = (min_gap + max_gap) / 2.0

    # Pre-extract strand data into numpy arrays
    starts = np.array([[s["original_start"]["x"], s["original_start"]["y"]] for s in strands_list])
    targets = np.array([[s["target_position"]["x"], s["target_position"]["y"]] for s in strands_list])

    # _2/_3 direction vectors per strand
    s23_nx = np.zeros(num_strands)
    s23_ny = np.zeros(num_strands)
    for i, s in enumerate(strands_list):
        s23 = s["strand_2_3"]
        dx = s23["end"]["x"] - s23["start"]["x"]
        dy = s23["end"]["y"] - s23["start"]["y"]
        length = math.sqrt(dx * dx + dy * dy)
        if length > 0.001:
            s23_nx[i] = dx / length
            s23_ny[i] = dy / length

    # Direction to target
    dx_to_target = targets[:, 0] - starts[:, 0]  # (num_strands,)
    dy_to_target = targets[:, 1] - starts[:, 1]

    dist_to_target = np.sqrt(dx_to_target**2 + dy_to_target**2)
    if np.any(dist_to_target < 0.001):
        return None

    # Determine goes_positive per strand using dot product with first strand direction.
    # The old heuristic (dy>=0 for vertical, dx>=0 for horizontal) fails when the
    # search angle is in a quadrant where dx and dy have different signs (e.g. ~-57°).
    # Dot product correctly determines alignment regardless of angle quadrant.
    ref_angle = np.arctan2(float(dy_to_target[0]), float(dx_to_target[0]))
    goes_positive = (dx_to_target * np.cos(ref_angle) + dy_to_target * np.sin(ref_angle)) >= 0

    # All angles
    angles_deg_arr = np.asarray(angles_deg, dtype=np.float64)
    angles_rad = np.radians(angles_deg_arr)
    num_angles = len(angles_rad)

    # Strand angles: (num_strands, num_angles)
    strand_angles = np.where(
        goes_positive[:, np.newaxis],
        angles_rad[np.newaxis, :],
        angles_rad[np.newaxis, :] + np.pi
    )
    cos_sa = np.cos(strand_angles)
    sin_sa = np.sin(strand_angles)

    # Inner extension range
    if allow_inner_extensions:
        inner_ext = np.arange(0, max_extension + 1, 5, dtype=np.float64)
    else:
        inner_ext = np.array([0.0], dtype=np.float64)
    num_ext = len(inner_ext)

    # Extended starts for all (strand, extension): (num_strands, num_ext)
    ext_starts_x = starts[:, 0:1] + inner_ext[np.newaxis, :] * s23_nx[:, np.newaxis]
    ext_starts_y = starts[:, 1:2] + inner_ext[np.newaxis, :] * s23_ny[:, np.newaxis]

    # dx, dy from extended start to target: (num_strands, num_ext)
    dx_ext = targets[:, 0:1] - ext_starts_x
    dy_ext = targets[:, 1:2] - ext_starts_y

    # Projection length for all (strand, extension, angle): (num_strands, num_ext, num_angles)
    proj_lengths = (dx_ext[:, :, np.newaxis] * cos_sa[:, np.newaxis, :] +
                    dy_ext[:, :, np.newaxis] * sin_sa[:, np.newaxis, :])

    # Valid where length > 10
    valid_proj = proj_lengths > 10

    # For each (strand, angle), find first valid extension index
    # argmax returns first True along axis=1
    has_any_valid = np.any(valid_proj, axis=1)  # (num_strands, num_angles)
    all_strands_valid_mask = np.all(has_any_valid, axis=0)  # (num_angles,)

    valid_angle_indices = np.where(all_strands_valid_mask)[0]
    if len(valid_angle_indices) == 0:
        return None

    # For valid angles, get the first valid extension per strand
    first_valid_ext_idx = np.argmax(valid_proj, axis=1)  # (num_strands, num_angles)

    # Compute extended starts and ends for valid angles
    si_range = np.arange(num_strands)

    best_result = None
    best_gap_variance = float('inf')
    best_first_last_dist = float('inf')

    for ai in valid_angle_indices:
        ext_idx = first_valid_ext_idx[:, ai]

        cfg_ext_start_x = ext_starts_x[si_range, ext_idx]
        cfg_ext_start_y = ext_starts_y[si_range, ext_idx]
        cfg_length = proj_lengths[si_range, ext_idx, ai]
        cfg_cos = cos_sa[:, ai]
        cfg_sin = sin_sa[:, ai]
        cfg_end_x = cfg_ext_start_x + cfg_length * cfg_cos
        cfg_end_y = cfg_ext_start_y + cfg_length * cfg_sin

        # Compute gaps between consecutive strands (perpendicular distance)
        # Line params for strand i: a=dy, b=-dx, c=x2*y1-y2*x1
        ldx = cfg_end_x - cfg_ext_start_x
        ldy = cfg_end_y - cfg_ext_start_y
        lc = cfg_end_x * cfg_ext_start_y - cfg_end_y * cfg_ext_start_x
        ll = np.sqrt(ldx * ldx + ldy * ldy)

        if np.any(ll < 0.001):
            continue

        inv_ll = 1.0 / ll

        # Perpendicular distances for consecutive pairs
        if num_strands == 2:
            # 2-strand special case: also search ext1 × ext2 for best gap
            # Use numpy to vectorize this
            line_a = ldy[0] * inv_ll[0]
            line_b = -ldx[0] * inv_ll[0]
            line_c_val = lc[0] * inv_ll[0]

            # All possible ext2 start points
            all_px = ext_starts_x[1, :]  # (num_ext,)
            all_py = ext_starts_y[1, :]

            # Check which ext2 values give valid projection at this angle
            all_proj = dx_ext[1, :] * cfg_cos[1] + dy_ext[1, :] * cfg_sin[1]  # (num_ext,)
            valid_ext2 = all_proj > 10

            # Compute gaps for all ext2
            all_gaps = np.abs(line_a * all_px + line_b * all_py + line_c_val)

            # Also need ext1 variations
            # For 2-strand, we want to search ext1 × ext2
            # Build all ext1 line params
            ext1_start_x = ext_starts_x[0, :]  # (num_ext,)
            ext1_start_y = ext_starts_y[0, :]
            ext1_proj = dx_ext[0, :] * cfg_cos[0] + dy_ext[0, :] * cfg_sin[0]
            valid_ext1 = ext1_proj > 10

            ext1_end_x = ext1_start_x + ext1_proj * cfg_cos[0]
            ext1_end_y = ext1_start_y + ext1_proj * cfg_sin[0]

            ext1_ldx = ext1_end_x - ext1_start_x
            ext1_ldy = ext1_end_y - ext1_start_y
            ext1_lc = ext1_end_x * ext1_start_y - ext1_end_y * ext1_start_x
            ext1_ll = np.sqrt(ext1_ldx**2 + ext1_ldy**2)

            valid_ext1_mask = valid_ext1 & (ext1_ll > 0.001)
            ext1_inv_ll = np.where(ext1_ll > 0.001, 1.0 / ext1_ll, 0.0)

            # Compute gaps for all (ext1, ext2): (num_ext_1, num_ext_2)
            ext1_a = ext1_ldy * ext1_inv_ll  # (num_ext,)
            ext1_b = -ext1_ldx * ext1_inv_ll
            ext1_c = ext1_lc * ext1_inv_ll

            # Gap matrix: (num_ext, num_ext) = ext1 lines × ext2 points
            gap_matrix = np.abs(
                ext1_a[:, np.newaxis] * all_px[np.newaxis, :] +
                ext1_b[:, np.newaxis] * all_py[np.newaxis, :] +
                ext1_c[:, np.newaxis]
            )

            # Valid mask: both ext1 and ext2 must have valid projections
            valid_mask = valid_ext1_mask[:, np.newaxis] & valid_ext2[np.newaxis, :]

            # Filter by gap range
            in_range = valid_mask & (gap_matrix >= min_gap) & (gap_matrix <= max_gap)

            if not np.any(in_range):
                continue

            # Find the smallest gap in range (prefer smallest first-last distance)
            gap_for_ranking = np.where(in_range, gap_matrix, np.inf)
            best_idx = np.unravel_index(np.argmin(gap_for_ranking), gap_for_ranking.shape)
            best_ext1_idx, best_ext2_idx = best_idx

            best_gap = gap_matrix[best_ext1_idx, best_ext2_idx]
            gap_variance = 0.0  # Single gap, no variance
            first_last_dist = float(best_gap)  # For 2 strands, first-last distance IS the gap

            if (first_last_dist, gap_variance) < (best_first_last_dist, best_gap_variance):
                best_first_last_dist = first_last_dist
                best_gap_variance = gap_variance
                # Reconstruct configs using Python (for return structure)
                angle_deg_val = float(angles_deg_arr[ai])
                angle_rad_val = float(angles_rad[ai])
                ext1_val = float(inner_ext[best_ext1_idx])
                ext2_val = float(inner_ext[best_ext2_idx])

                config1 = _build_config_dict(strands_list[0], ext1_val, angle_rad_val, goes_positive[0])
                config2 = _build_config_dict(strands_list[1], ext2_val, angle_rad_val, goes_positive[1])

                if config1 and config2:
                    # Recompute gap with Python for accuracy
                    lp = precompute_line_params(config1["extended_start"], config1["end"])
                    sg = fast_perpendicular_distance(lp, config2["extended_start"]["x"], config2["extended_start"]["y"])

                    best_result = {
                        "valid": True,
                        "configurations": [config1, config2],
                        "gaps": [abs(sg)],
                        "signed_gaps": [sg],
                        "gap_variance": 0,
                        "average_gap": abs(sg),
                        "worst_gap": abs(sg),
                        "angle": angle_rad_val,
                        "angle_degrees": angle_deg_val,
                        "min_gap": min_gap,
                        "max_gap": max_gap,
                        "first_last_distance": abs(sg),
                    }

        else:
            # 3+ strands: compute gaps between consecutive
            signed_gaps_arr = np.zeros(num_strands - 1)
            for i in range(num_strands - 1):
                sg = (ldy[i] * cfg_ext_start_x[i + 1] +
                      (-ldx[i]) * cfg_ext_start_y[i + 1] +
                      lc[i]) * inv_ll[i]
                if i % 2 == 1:
                    sg = -sg
                signed_gaps_arr[i] = sg

            abs_gaps = np.abs(signed_gaps_arr)

            # Check direction consistency
            last_sg = (ldy[0] * cfg_ext_start_x[-1] +
                       (-ldx[0]) * cfg_ext_start_y[-1] +
                       lc[0]) * inv_ll[0]
            expected_sign = 1.0 if last_sg >= 0 else -1.0

            directions_ok = True
            for i in range(num_strands - 1):
                if expected_sign > 0 and signed_gaps_arr[i] <= 0:
                    directions_ok = False
                    break
                if expected_sign < 0 and signed_gaps_arr[i] >= 0:
                    directions_ok = False
                    break

            if not directions_ok:
                continue

            # Check gap ranges
            all_in_range = np.all((abs_gaps >= min_gap) & (abs_gaps <= max_gap))

            if all_in_range:
                avg_gap = float(np.mean(abs_gaps))
                gap_var = float(np.var(abs_gaps))
                first_last_dist = abs(float(last_sg))

                if (first_last_dist, gap_var) < (best_first_last_dist, best_gap_variance):
                    best_first_last_dist = first_last_dist
                    best_gap_variance = gap_var
                    angle_deg_val = float(angles_deg_arr[ai])
                    angle_rad_val = float(angles_rad[ai])

                    # Build full config dicts using Python
                    configs = []
                    for si in range(num_strands):
                        ext_val = float(inner_ext[ext_idx[si]])
                        cfg = _build_config_dict(strands_list[si], ext_val, angle_rad_val, goes_positive[si])
                        if cfg is None:
                            break
                        configs.append(cfg)
                    else:
                        # Recompute gaps with Python for accuracy
                        py_gaps = []
                        py_signed = []
                        py_line_params = [precompute_line_params(c["extended_start"], c["end"]) for c in configs]
                        for i in range(len(configs) - 1):
                            px_v = configs[i + 1]["extended_start"]["x"]
                            py_v = configs[i + 1]["extended_start"]["y"]
                            sg = fast_perpendicular_distance(py_line_params[i], px_v, py_v)
                            if i % 2 == 1:
                                sg = -sg
                            py_signed.append(sg)
                            py_gaps.append(abs(sg))

                        best_result = {
                            "valid": True,
                            "configurations": configs,
                            "gaps": py_gaps,
                            "signed_gaps": py_signed,
                            "gap_variance": gap_var,
                            "average_gap": avg_gap,
                            "worst_gap": min(py_gaps) if py_gaps else 0,
                            "angle": angle_rad_val,
                            "angle_degrees": angle_deg_val,
                            "min_gap": min_gap,
                            "max_gap": max_gap,
                            "first_last_distance": first_last_dist,
                        }

    return best_result


def _select_best_result(valid_results, distance_tolerance=2.0):
    """
    Select best result using tiered priority:
    1. Smallest first-last distance (within distance_tolerance px)
    2. Lowest gap variance within that distance group
    3. If only 1 result at smallest distance, also compare with next group
    """
    if not valid_results:
        return None

    # Sort by first_last_distance
    sorted_results = sorted(
        valid_results,
        key=lambda r: r.get("first_last_distance", float('inf'))
    )

    smallest_dist = sorted_results[0].get("first_last_distance", float('inf'))

    # Group 1: all results within tolerance of the smallest distance
    group1 = [r for r in sorted_results
              if r.get("first_last_distance", float('inf')) <= smallest_dist + distance_tolerance]

    # Best in group 1 by gap variance
    best_g1 = min(group1, key=lambda r: r.get("gap_variance", float('inf')))

    if len(group1) > 1:
        # Multiple results in group 1, pick best variance
        print(f"  Selection: {len(group1)} results in smallest-distance group "
              f"(dist <= {smallest_dist + distance_tolerance:.1f}px), "
              f"best variance: {best_g1.get('gap_variance', 'N/A')}")
        return best_g1

    # Only 1 result in group 1 - also check group 2
    remaining = [r for r in sorted_results
                 if r.get("first_last_distance", float('inf')) > smallest_dist + distance_tolerance]

    if not remaining:
        print(f"  Selection: single result at dist={smallest_dist:.1f}px, no other groups")
        return best_g1

    # Group 2: within tolerance of the next smallest distance
    next_smallest = remaining[0].get("first_last_distance", float('inf'))
    group2 = [r for r in remaining
              if r.get("first_last_distance", float('inf')) <= next_smallest + distance_tolerance]

    best_g2 = min(group2, key=lambda r: r.get("gap_variance", float('inf')))

    # Compare: if group 2 has better variance, prefer it
    g1_var = best_g1.get("gap_variance", float('inf'))
    g2_var = best_g2.get("gap_variance", float('inf'))

    if g2_var < g1_var:
        g2_dist = best_g2.get("first_last_distance", float('inf'))
        print(f"  Selection: group2 (dist={g2_dist:.1f}px, var={g2_var:.6f}) beats "
              f"group1 (dist={smallest_dist:.1f}px, var={g1_var:.6f}) on variance")
        return best_g2
    else:
        print(f"  Selection: group1 (dist={smallest_dist:.1f}px, var={g1_var:.6f}) wins over "
              f"group2 (dist={next_smallest:.1f}px, var={g2_var:.6f})")
        return best_g1


def _compute_goes_positive_for_angle(original_start, target_position, angle_rad):
    """Determine strand direction using the same dot-product rule as the CPU fallback path."""
    dx_to_target = target_position["x"] - original_start["x"]
    dy_to_target = target_position["y"] - original_start["y"]
    return (dx_to_target * math.cos(angle_rad) + dy_to_target * math.sin(angle_rad)) >= 0


def _build_config_dict(h_strand, extension, angle_rad, goes_positive, original_start_override=None):
    """Build a configuration dict for a single strand at a given extension and angle."""
    original_start = original_start_override or h_strand["original_start"]
    target_position = h_strand["target_position"]

    strand_angle = angle_rad if goes_positive else angle_rad + math.pi
    cos_a = math.cos(strand_angle)
    sin_a = math.sin(strand_angle)

    s23 = h_strand["strand_2_3"]
    s23_dx = s23["end"]["x"] - s23["start"]["x"]
    s23_dy = s23["end"]["y"] - s23["start"]["y"]
    s23_len = math.sqrt(s23_dx**2 + s23_dy**2)
    if s23_len < 0.001:
        return None

    s23_nx = s23_dx / s23_len
    s23_ny = s23_dy / s23_len

    ext_start_x = original_start["x"] + extension * s23_nx
    ext_start_y = original_start["y"] + extension * s23_ny

    dx = target_position["x"] - ext_start_x
    dy = target_position["y"] - ext_start_y
    length = dx * cos_a + dy * sin_a

    if length <= 10:
        return None

    end_x = ext_start_x + length * cos_a
    end_y = ext_start_y + length * sin_a

    return {
        "strand": h_strand,
        "extended_start": {"x": ext_start_x, "y": ext_start_y},
        "end": {"x": end_x, "y": end_y},
        "length": length,
        "extension": extension,
        "angle": strand_angle,
        "goes_positive": bool(goes_positive),
    }


def _clone_alignment_strands(strands_list):
    """Clone only the mutable per-strand geometry needed for combo search."""
    clones = []
    for strand in strands_list:
        clones.append({
            "strand_4_5": strand["strand_4_5"],
            "strand_2_3": strand["strand_2_3"],
            "type": strand["type"],
            "set_number": strand["set_number"],
            "original_start": {
                "x": strand["original_start"]["x"],
                "y": strand["original_start"]["y"],
            },
            "target_position": {
                "x": strand["target_position"]["x"],
                "y": strand["target_position"]["y"],
            },
        })
    return clones


def _encode_pair_indices(strands_list, pairs):
    """Replace direct strand references with integer indices for worker transport."""
    strand_id_map = {id(strand): idx for idx, strand in enumerate(strands_list)}
    pair_indices = []
    for left_strand, right_strand in pairs:
        pair_indices.append((
            strand_id_map[id(left_strand)],
            strand_id_map[id(right_strand)] if right_strand is not None else None,
        ))
    return pair_indices


def _decode_combo_index(combo_index, ext_range_values, num_pairs):
    """Decode an itertools.product-style combo index into per-pair extensions."""
    if num_pairs <= 0:
        return ()

    radix = len(ext_range_values)
    combo = [ext_range_values[0]] * num_pairs
    value = combo_index
    for pair_idx in range(num_pairs - 1, -1, -1):
        combo[pair_idx] = ext_range_values[value % radix]
        value //= radix
    return tuple(combo)


def _build_angle_values(angle_min_deg, angle_max_deg, angle_step_degrees):
    """Build the same 0.01-degree stepped angle grid used by the serial CPU path."""
    step = max(1, int(angle_step_degrees * 100))
    angle_start = int(angle_min_deg * 100)
    angle_end = int(angle_max_deg * 100)
    return [h / 100.0 for h in range(angle_start, angle_end + 1, step)]


def _format_progress_duration(seconds):
    """Format elapsed/remaining time for terminal progress output."""
    total_seconds = max(0, int(seconds))
    hours, rem = divmod(total_seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _print_terminal_progress(label, completed, total, start_time, valid_count=0, final=False):
    """Print a single-line terminal progress bar with ETA."""
    safe_total = max(total, 1)
    bounded_completed = max(0, min(completed, safe_total))
    fraction = bounded_completed / safe_total

    elapsed = max(time.perf_counter() - start_time, 0.0)
    rate = bounded_completed / elapsed if elapsed > 1e-9 else 0.0
    remaining = max(safe_total - bounded_completed, 0)
    eta_seconds = remaining / rate if rate > 1e-9 else 0.0

    bar_width = 28
    filled = min(bar_width, int(bar_width * fraction))
    bar = "#" * filled + "-" * (bar_width - filled)

    line = (
        f"\r  {label} [{bar}] {bounded_completed:,}/{safe_total:,} "
        f"({fraction * 100:5.1f}%) | elapsed {_format_progress_duration(elapsed)} "
        f"| eta {_format_progress_duration(eta_seconds)} | valid {valid_count:,}"
    )
    sys.stdout.write(line + " " * 8)
    if final:
        sys.stdout.write("\n")
    sys.stdout.flush()


def _evaluate_cpu_combo_chunk(task):
    """
    Evaluate a contiguous range of combo indices using the existing CPU search logic.

    This keeps the validity math unchanged; the only difference is that multiple
    combo ranges can now run in parallel worker processes.
    """
    (
        strands_list,
        pair_indices,
        pair_directions,
        pair_originals,
        ext_range_values,
        combo_start,
        combo_end,
        angle_step_degrees,
        max_extension,
        strand_width,
        custom_angle_min,
        custom_angle_max,
        angle_mode,
    ) = task

    working_strands = _clone_alignment_strands(strands_list)
    use_custom = custom_angle_min is not None and custom_angle_max is not None

    valid_results = []
    best_fallback = None
    best_fallback_worst_gap = -float("inf")
    best_fallback_extensions = tuple(0 for _ in pair_indices)
    best_fallback_angle = 0.0

    for combo_index in range(combo_start, combo_end):
        combo = _decode_combo_index(combo_index, ext_range_values, len(pair_indices))

        for pair_idx, (left_idx, right_idx) in enumerate(pair_indices):
            ext = combo[pair_idx]
            l_nx, l_ny, r_nx, r_ny = pair_directions[pair_idx]
            l_orig, r_orig = pair_originals[pair_idx]

            left_strand = working_strands[left_idx]
            left_strand["original_start"]["x"] = l_orig["x"] + ext * l_nx
            left_strand["original_start"]["y"] = l_orig["y"] + ext * l_ny

            if right_idx is not None and r_orig is not None:
                right_strand = working_strands[right_idx]
                right_strand["original_start"]["x"] = r_orig["x"] + ext * r_nx
                right_strand["original_start"]["y"] = r_orig["y"] + ext * r_ny

        if use_custom:
            angle_min_deg = custom_angle_min
            angle_max_deg = custom_angle_max
        else:
            adapted = [
                {
                    "strand": strand["strand_4_5"],
                    "start": strand["original_start"],
                    "target": strand["target_position"],
                }
                for strand in working_strands
            ]
            _, angle_min_deg, angle_max_deg, _ = _compute_pair_angle_range(adapted, angle_mode)

        angles_deg_list = _build_angle_values(angle_min_deg, angle_max_deg, angle_step_degrees)
        np_result = _numpy_try_all_angles(
            working_strands,
            angles_deg_list,
            max_extension,
            strand_width,
            allow_inner_extensions=False,
        )

        if np_result and np_result.get("valid"):
            stored_result = copy.deepcopy(np_result)
            stored_result["pair_extensions"] = combo
            stored_result["combo_index"] = combo_index
            valid_results.append(stored_result)
            continue

        fallback_result = try_angle_configuration_first_last(
            working_strands,
            math.radians(angles_deg_list[len(angles_deg_list) // 2]) if angles_deg_list else 0,
            max_extension,
            strand_width,
            verbose=False,
            allow_inner_extensions=False,
        )
        fallback = fallback_result.get("fallback")
        if fallback and fallback_result.get("directions_valid", False):
            worst_gap = fallback.get("worst_gap", 0)
            if worst_gap > best_fallback_worst_gap:
                best_fallback_worst_gap = worst_gap
                best_fallback = copy.deepcopy(fallback)
                best_fallback_extensions = combo
                best_fallback_angle = fallback_result.get(
                    "angle_degrees",
                    angles_deg_list[len(angles_deg_list) // 2] if angles_deg_list else 0,
                )

    return {
        "chunk_start": combo_start,
        "chunk_end": combo_end,
        "valid_results": valid_results,
        "best_fallback": best_fallback,
        "best_fallback_worst_gap": best_fallback_worst_gap,
        "best_fallback_extensions": best_fallback_extensions,
        "best_fallback_angle": best_fallback_angle,
    }


def _get_cpu_worker_count(total_combos):
    """Choose a conservative default worker count, with env override for tuning."""
    env_value = os.environ.get("MXN_ALIGNMENT_CPU_WORKERS")
    if env_value:
        try:
            requested = int(env_value)
            if requested > 0:
                return min(requested, max(total_combos, 1))
        except ValueError:
            pass

    cpu_total = os.cpu_count() or 1
    if cpu_total <= 1 or total_combos < 2:
        return 1

    return min(max(cpu_total - 1, 1), total_combos, 8)


def _get_cpu_chunk_size(total_combos, worker_count):
    """Pick a chunk size that amortizes spawn overhead without delaying ordered saves too much."""
    env_value = os.environ.get("MXN_ALIGNMENT_CPU_CHUNK_SIZE")
    if env_value:
        try:
            requested = int(env_value)
            if requested > 0:
                return min(requested, max(total_combos, 1))
        except ValueError:
            pass

    target_chunks = max(worker_count * 4, 1)
    adaptive = total_combos // target_chunks if total_combos > 0 else 1
    return max(16, min(256, adaptive if adaptive > 0 else 16))


def _get_alignment_combo_limit(use_gpu=False):
    """
    Return the maximum allowed pair-extension combo count for the selected backend.

    Set MXN_ALIGNMENT_MAX_CPU_COMBOS or MXN_ALIGNMENT_MAX_GPU_COMBOS to a
    positive integer to override. Set either variable to 0 or a negative value
    to disable the guard for that backend.
    """
    env_name = "MXN_ALIGNMENT_MAX_GPU_COMBOS" if use_gpu else "MXN_ALIGNMENT_MAX_CPU_COMBOS"
    default_limit = 0 if use_gpu else 10_000_000
    env_value = os.environ.get(env_name)
    if env_value:
        try:
            requested = int(env_value)
            return requested if requested > 0 else None
        except ValueError:
            pass
    return default_limit if default_limit > 0 else None


def _count_pair_extension_values(max_pair_extension, pair_extension_step):
    """Return the number of pair-extension values generated by the outer search loop."""
    if pair_extension_step <= 0:
        return 1
    return len(range(0, max_pair_extension + pair_extension_step, pair_extension_step))


def _suggest_pair_extension_step(max_pair_extension, num_pairs, combo_limit):
    """Suggest the smallest pair-extension step that keeps the combo count under the limit."""
    if num_pairs <= 0 or combo_limit is None:
        return 1
    if max_pair_extension <= 0:
        return 1

    suggested_step = 1
    while True:
        ext_steps = _count_pair_extension_values(max_pair_extension, suggested_step)
        if ext_steps ** num_pairs <= combo_limit:
            return suggested_step
        suggested_step += 1


def get_alignment_combo_guard(total_combos, num_pairs, max_pair_extension, pair_extension_step, use_gpu=False):
    """
    Return guard metadata when a pair-extension search space is too large.

    Returns None when the search should proceed.
    """
    combo_limit = _get_alignment_combo_limit(use_gpu=use_gpu)
    if combo_limit is None or total_combos <= combo_limit:
        return None

    suggested_step = _suggest_pair_extension_step(max_pair_extension, num_pairs, combo_limit)
    suggested_ext_steps = _count_pair_extension_values(max_pair_extension, suggested_step)
    suggested_total_combos = suggested_ext_steps ** max(num_pairs, 0)
    backend_label = "GPU" if use_gpu else "CPU"

    message = (
        f"{backend_label} search skipped: {total_combos:,} pair-extension combos exceeds "
        f"the {backend_label} limit of {combo_limit:,}. "
        f"Increase Pair ext step to at least {suggested_step}px or lower Pair ext max."
    )
    if suggested_step != pair_extension_step:
        message += f" At {suggested_step}px, the search drops to about {suggested_total_combos:,} combos."

    return {
        "limit": combo_limit,
        "suggested_step": suggested_step,
        "suggested_total_combos": suggested_total_combos,
        "message": message,
    }


def _search_combo_space_cpu(
    strands_list,
    pairs,
    pair_directions,
    pair_originals,
    ext_range_values,
    angle_step_degrees,
    max_extension,
    strand_width,
    custom_angle_min,
    custom_angle_max,
    angle_mode,
    on_config_callback=None,
    direction_type="horizontal",
):
    """
    Search the CPU combo space while preserving the existing validity rules and
    callback order. Valid results are still emitted in original combo order.
    """
    total_combos = len(ext_range_values) ** len(pairs)
    worker_count = _get_cpu_worker_count(total_combos)
    chunk_size = _get_cpu_chunk_size(total_combos, worker_count)
    pair_indices = _encode_pair_indices(strands_list, pairs)

    all_valid_results = []
    best_fallback = None
    best_fallback_worst_gap = -float("inf")
    best_fallback_extensions = tuple(0 for _ in pairs)
    best_fallback_angle = 0.0
    completed_combos = 0
    valid_count = 0
    progress_start_time = time.perf_counter()
    last_progress_time = 0.0
    last_progress_completed = -1
    last_progress_was_final = False
    show_progress = total_combos >= chunk_size

    def report_progress(force=False, final=False):
        nonlocal last_progress_time, last_progress_completed, last_progress_was_final
        if not show_progress:
            return
        if final and completed_combos == total_combos and last_progress_completed == completed_combos:
            if not last_progress_was_final:
                sys.stdout.write("\n")
                sys.stdout.flush()
                last_progress_was_final = True
            return
        now = time.perf_counter()
        if not force and (now - last_progress_time) < 0.5 and completed_combos < total_combos:
            return
        _print_terminal_progress(
            f"{direction_type.capitalize()} CPU",
            completed_combos,
            total_combos,
            progress_start_time,
            valid_count=valid_count,
            final=final,
        )
        last_progress_time = now
        last_progress_completed = completed_combos
        last_progress_was_final = final

    def reset_results():
        nonlocal best_fallback, best_fallback_worst_gap, best_fallback_extensions, best_fallback_angle
        nonlocal completed_combos, valid_count, progress_start_time, last_progress_time
        nonlocal last_progress_completed, last_progress_was_final
        all_valid_results.clear()
        best_fallback = None
        best_fallback_worst_gap = -float("inf")
        best_fallback_extensions = tuple(0 for _ in pairs)
        best_fallback_angle = 0.0
        completed_combos = 0
        valid_count = 0
        progress_start_time = time.perf_counter()
        last_progress_time = 0.0
        last_progress_completed = -1
        last_progress_was_final = False

    def consume_chunk(chunk_result):
        nonlocal best_fallback, best_fallback_worst_gap, best_fallback_extensions, best_fallback_angle
        nonlocal completed_combos, valid_count

        chunk_fallback = chunk_result.get("best_fallback")
        chunk_worst_gap = chunk_result.get("best_fallback_worst_gap", -float("inf"))
        if chunk_fallback is not None and chunk_worst_gap > best_fallback_worst_gap:
            best_fallback = chunk_fallback
            best_fallback_worst_gap = chunk_worst_gap
            best_fallback_extensions = chunk_result.get("best_fallback_extensions", (0,))
            best_fallback_angle = chunk_result.get("best_fallback_angle", 0.0)

        chunk_valid_results = chunk_result.get("valid_results", [])
        all_valid_results.extend(chunk_valid_results)
        valid_count += len(chunk_valid_results)
        completed_combos += chunk_result.get("chunk_end", 0) - chunk_result.get("chunk_start", 0)
        report_progress()

    def run_executor(executor_cls):
        task_iter = iter(iter_chunk_tasks())
        submit_window = max(worker_count * 2, 1)

        with executor_cls(max_workers=worker_count) as executor:
            pending = set()

            def submit_next():
                try:
                    task = next(task_iter)
                except StopIteration:
                    return False
                pending.add(executor.submit(_evaluate_cpu_combo_chunk, task))
                return True

            for _ in range(submit_window):
                if not submit_next():
                    break

            while pending:
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    consume_chunk(future.result())
                    submit_next()

    run_parallel = worker_count > 1 and total_combos >= 64
    def iter_chunk_tasks():
        for chunk_start in range(0, total_combos, chunk_size):
            yield (
                strands_list,
                pair_indices,
                pair_directions,
                pair_originals,
                ext_range_values,
                chunk_start,
                min(chunk_start + chunk_size, total_combos),
                angle_step_degrees,
                max_extension,
                strand_width,
                custom_angle_min,
                custom_angle_max,
                angle_mode,
            )

    if run_parallel:
        print(
            f"  CPU parallel search: {worker_count} workers, chunk_size={chunk_size}, "
            f"{total_combos} combos"
        )
        report_progress(force=True)
        try:
            run_executor(ProcessPoolExecutor)
        except Exception as parallel_error:
            if show_progress and completed_combos:
                sys.stdout.write("\n")
                sys.stdout.flush()
            print(f"  CPU process search failed ({parallel_error}); retrying with threads.")
            reset_results()
            report_progress(force=True)
            try:
                run_executor(ThreadPoolExecutor)
            except Exception as thread_error:
                if show_progress and completed_combos:
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                print(f"  CPU threaded search failed ({thread_error}); retrying serially.")
                reset_results()
                run_parallel = False

    if not run_parallel:
        report_progress(force=True)
        for task in iter_chunk_tasks():
            consume_chunk(_evaluate_cpu_combo_chunk(task))

    report_progress(force=True, final=show_progress)
    all_valid_results.sort(key=lambda result: result.get("combo_index", -1))

    if on_config_callback:
        for result in all_valid_results:
            on_config_callback(
                result["angle_degrees"],
                result["pair_extensions"],
                result,
                direction_type,
            )

    return (
        all_valid_results,
        best_fallback,
        best_fallback_worst_gap,
        best_fallback_extensions,
        best_fallback_angle,
        total_combos,
    )


def align_horizontal_strands_parallel(all_strands, n,
                                       angle_step_degrees=0.5,
                                       max_extension=100.0, strand_width=46,
                                       custom_angle_min=None, custom_angle_max=None,
                                       on_config_callback=None,
                                       max_pair_extension=200,
                                       pair_extension_step=10,
                                       m=None, k=0, direction="cw",
                                       use_gpu=False,
                                       angle_mode="first_strand"):
    """
    Parallel alignment of horizontal _4/_5 strands using first-last pair approach.

    Algorithm:
    1. Calculate angle range from the selected auto mode (or use custom range)
    2. LAST strand should use angle + 180° (opposite direction)
    3. For each angle in range, check if first and last can reach their targets
    4. Then check if MIDDLE strands can adapt (with extensions if needed)
    5. Validate gaps are within strand_width to strand_width*1.5

    Args:
        all_strands: List of all strand dictionaries
        n: Number of horizontal strand sets (horizontal sets are 1..n)
        angle_step_degrees: Step size for angle search (default 0.5°)
        max_extension: Maximum allowed extension for _2/_3 strands
        strand_width: Width of strands for gap calculation (default 46)
        custom_angle_min: Optional custom minimum angle (degrees)
        custom_angle_max: Optional custom maximum angle (degrees)
        on_config_callback: Optional callback(angle_deg, extension, result) called for each config

    Returns:
        dict with success, angle, configurations, gaps, etc.
    """

    # Build k-based horizontal strand set
    if k != 0 and m is not None:
        h_names_set, h_order_list, _, _ = _build_k_based_strand_sets(m, n, k, direction)
    else:
        h_names_set = None
        h_order_list = None

    # Collect ALL _2/_3 strands (needed for structural pairing regardless of group)
    strands_2 = []
    strands_3 = []
    # Collect horizontal _4/_5 strands (filtered by k-based group)
    strands_4 = []
    strands_5 = []

    for strand in all_strands:
        if strand["type"] != "AttachedStrand":
            continue

        layer_name = strand["layer_name"]
        set_num = strand["set_number"]

        if layer_name.endswith("_2"):
            strands_2.append(strand)
        elif layer_name.endswith("_3"):
            strands_3.append(strand)
        elif layer_name.endswith("_4"):
            if h_names_set is not None:
                if layer_name in h_names_set:
                    strands_4.append(strand)
            else:
                if set_num <= n:
                    strands_4.append(strand)
        elif layer_name.endswith("_5"):
            if h_names_set is not None:
                if layer_name in h_names_set:
                    strands_5.append(strand)
            else:
                if set_num <= n:
                    strands_5.append(strand)

    if not strands_4 and not strands_5:
        return {
            "success": False,
            "message": "No horizontal _4/_5 strands found"
        }


    # Collect all horizontal _4/_5 strands with their target positions
    horizontal_strands = []

    for s4 in strands_4:
        set_num = s4["set_number"]
        s2 = next((s for s in strands_2 if s["set_number"] == set_num), None)
        if s2:
            horizontal_strands.append({
                "strand_4_5": s4,
                "strand_2_3": s2,
                "type": "_4",
                "set_number": set_num,
                "original_start": {"x": s4["start"]["x"], "y": s4["start"]["y"]},
                "target_position": {"x": s4["end"]["x"], "y": s4["end"]["y"]},
            })

    for s5 in strands_5:
        set_num = s5["set_number"]
        s3 = next((s for s in strands_3 if s["set_number"] == set_num), None)
        if s3:
            horizontal_strands.append({
                "strand_4_5": s5,
                "strand_2_3": s3,
                "type": "_5",
                "set_number": set_num,
                "original_start": {"x": s5["start"]["x"], "y": s5["start"]["y"]},
                "target_position": {"x": s5["end"]["x"], "y": s5["end"]["y"]},
            })

    # Sort by k-based order if available, otherwise by set_number
    if h_order_list is not None:
        h_order_index = {name: i for i, name in enumerate(h_order_list)}
        horizontal_strands.sort(key=lambda h: h_order_index.get(h["strand_4_5"]["layer_name"], 999))
    else:
        horizontal_strands.sort(key=lambda h: (h["set_number"], h["type"]))

    num_strands = len(horizontal_strands)
    if num_strands < 2:
        return {
            "success": False,
            "message": "Need at least 2 horizontal strands for parallel alignment"
        }

    # Build outside-in pairs: (1st, last), (2nd, one-before-last), etc.
    pairs = [(horizontal_strands[i], horizontal_strands[num_strands - 1 - i])
             for i in range(num_strands // 2)]
    # If odd number of strands, middle strand gets a solo pair entry
    if num_strands % 2 == 1:
        mid = num_strands // 2
        pairs.append((horizontal_strands[mid], None))

    # Compute _2/_3 extension directions and store originals for ALL pair members
    pair_directions = []  # [(left_nx, left_ny, right_nx, right_ny), ...]
    pair_originals = []   # [(left_orig, right_orig), ...]

    for left_strand, right_strand in pairs:
        # Left strand direction
        l_s23 = left_strand["strand_2_3"]
        l_dx = l_s23["end"]["x"] - l_s23["start"]["x"]
        l_dy = l_s23["end"]["y"] - l_s23["start"]["y"]
        l_len = math.sqrt(l_dx**2 + l_dy**2)
        l_nx = l_dx / l_len if l_len > 0.001 else 0
        l_ny = l_dy / l_len if l_len > 0.001 else 0

        # Right strand direction (if exists)
        if right_strand is not None:
            r_s23 = right_strand["strand_2_3"]
            r_dx = r_s23["end"]["x"] - r_s23["start"]["x"]
            r_dy = r_s23["end"]["y"] - r_s23["start"]["y"]
            r_len = math.sqrt(r_dx**2 + r_dy**2)
            r_nx = r_dx / r_len if r_len > 0.001 else 0
            r_ny = r_dy / r_len if r_len > 0.001 else 0
        else:
            r_nx, r_ny = 0, 0

        pair_directions.append((l_nx, l_ny, r_nx, r_ny))
        left_orig = {"x": left_strand["original_start"]["x"], "y": left_strand["original_start"]["y"]}
        right_orig = {"x": right_strand["original_start"]["x"], "y": right_strand["original_start"]["y"]} if right_strand else None
        pair_originals.append((left_orig, right_orig))

    print(f"\n=== Horizontal Parallel Alignment (Per-Pair Independent Extension) ===")
    print(f"Found {num_strands} horizontal _4/_5 strands, {len(pairs)} pairs")
    print(f"Max extension: {max_extension}")
    print(f"Strand width: {strand_width}")
    print(f"Per-pair extension: 0 to {max_pair_extension} px (step {pair_extension_step})")

    # Debug: Print details of each strand and pair membership
    print(f"\n--- Strand Details ---")
    for i, h in enumerate(horizontal_strands):
        dx = h['target_position']['x'] - h['original_start']['x']
        dy = h['target_position']['y'] - h['original_start']['y']
        angle = math.degrees(math.atan2(dy, dx))
        # Find which pair this strand belongs to
        pair_label = ""
        for pi, (left, right) in enumerate(pairs):
            if h is left:
                pair_label = f" [Pair {pi+1} LEFT]"
            elif h is right:
                pair_label = f" [Pair {pi+1} RIGHT]"
        print(f"  {i+1}. {h['strand_4_5']['layer_name']}{pair_label} angle={angle:.1f}°")

    # Use first strand for angle calculation reference
    first_strand = horizontal_strands[0]

    # Calculate the initial angle of the FIRST strand (from start to target)
    first_dx = first_strand["target_position"]["x"] - first_strand["original_start"]["x"]
    first_dy = first_strand["target_position"]["y"] - first_strand["original_start"]["y"]
    first_initial_angle = math.degrees(math.atan2(first_dy, first_dx))

    # Use custom angle range if provided, otherwise compute from angle_mode
    use_custom_h = custom_angle_min is not None and custom_angle_max is not None
    if use_custom_h:
        base_angle_min = custom_angle_min
        base_angle_max = custom_angle_max
        print(f"\n--- Using CUSTOM Horizontal Angle Range ---")
        print(f"    Custom range: {base_angle_min:.2f}° to {base_angle_max:.2f}°")
    else:
        # Build adapter list for _compute_pair_angle_range
        _adapted = [{"strand": h["strand_4_5"], "start": h["original_start"], "target": h["target_position"]}
                     for h in horizontal_strands]
        _, base_angle_min, base_angle_max, _pair_dbg = _compute_pair_angle_range(_adapted, angle_mode)
        print(f"\n--- Angle Range (mode={angle_mode}) ---")
        print(f"    First strand initial angle: {first_initial_angle:.2f}°")
        print(f"    Computed range: {base_angle_min:.2f}° to {base_angle_max:.2f}°")
        for ln, rn, pa in _pair_dbg:
            print(f"      Pair ({ln}, {rn}): {pa:.1f}°")

    # Nested loops: one extension range per pair (via itertools.product)
    all_valid_results = []

    # Track best fallback candidate (max-min optimization: maximize the worst gap)
    best_fallback = None
    best_fallback_worst_gap = -float('inf')
    best_fallback_extensions = tuple(0 for _ in pairs)
    best_fallback_angle = 0

    ext_range_values = list(range(0, max_pair_extension + pair_extension_step, pair_extension_step))
    num_pairs = len(pairs)
    total_combos = len(ext_range_values) ** num_pairs
    combo_count = total_combos
    can_use_gpu = use_gpu and _check_cupy_available()
    combo_guard = get_alignment_combo_guard(
        total_combos,
        num_pairs,
        max_pair_extension,
        pair_extension_step,
        use_gpu=can_use_gpu,
    )

    if combo_guard:
        print(f"\n=== Search Skipped ===")
        print(combo_guard["message"])
        return {
            "success": False,
            "message": combo_guard["message"],
        }

    # === GPU or CPU combo search ===
    if can_use_gpu:
        print(f"\n--- GPU search: {total_combos} extension combinations ({len(ext_range_values)} values x {num_pairs} pairs) ---")
        all_valid_results, gpu_fallback = _cupy_search_combo_chunks(
            horizontal_strands, pairs, pair_directions, pair_originals,
            first_strand, ext_range_values, angle_step_degrees,
            max_extension, strand_width,
            custom_angle_min if use_custom_h else None,
            custom_angle_max if use_custom_h else None,
            angle_mode=angle_mode,
            on_config_callback=on_config_callback,
            chunk_size=2048,
            direction_type="horizontal",
            allow_inner_extensions=False,
        )
        if gpu_fallback:
            best_fallback = gpu_fallback
            best_fallback_worst_gap = gpu_fallback.get("worst_gap", 0)
            best_fallback_extensions = gpu_fallback.get("pair_extensions", (0,))
            best_fallback_angle = gpu_fallback.get("angle_degrees", 0)
    else:
        if use_gpu:
            print("WARNING: GPU requested but CuPy not available. Falling back to NumPy.")
        print(f"\n--- Searching {total_combos} extension combinations ({len(ext_range_values)} values x {num_pairs} pairs) [numpy-accelerated] ---")
        (
            all_valid_results,
            best_fallback,
            best_fallback_worst_gap,
            best_fallback_extensions,
            best_fallback_angle,
            combo_count,
        ) = _search_combo_space_cpu(
            horizontal_strands,
            pairs,
            pair_directions,
            pair_originals,
            ext_range_values,
            angle_step_degrees,
            max_extension,
            strand_width,
            custom_angle_min if use_custom_h else None,
            custom_angle_max if use_custom_h else None,
            angle_mode,
            on_config_callback=on_config_callback,
            direction_type="horizontal",
        )

    best_result = _select_best_result(all_valid_results)
    if best_result:
        best_pair_extensions = best_result.get("pair_extensions", (0,))
        print(f"\n=== Best Solution Found ===")
        print(f"Pair extensions: {best_pair_extensions}")
        print(f"Angle: {best_result['angle_degrees']:.2f}°")
        print(f"Gap variance: {best_result['gap_variance']:.4f}")
        print(f"Average gap: {best_result['average_gap']:.2f}")
        print(f"First-last distance: {best_result.get('first_last_distance', 'N/A')}")

        return {
            "success": True,
            "angle": best_result["angle"],
            "angle_degrees": best_result["angle_degrees"],
            "configurations": best_result["configurations"],
            "average_gap": best_result["average_gap"],
            "gap_variance": best_result["gap_variance"],
            "first_last_distance": best_result.get("first_last_distance"),
            "pair_extension": best_pair_extensions[0] if best_pair_extensions else 0,
            "pair_extensions": best_pair_extensions,
            "min_gap": best_result.get("min_gap", strand_width),
            "max_gap": best_result.get("max_gap", strand_width * 1.5),
            "message": f"Found parallel configuration at {best_result['angle_degrees']:.2f}° (pair exts: {best_pair_extensions})"
        }
    elif best_fallback:
        # Return best fallback candidate (max-min: the one with maximum worst gap)
        print(f"\n=== Best Fallback Candidate (no valid solution) ===")
        print(f"Pair extensions: {best_fallback_extensions}")
        print(f"Angle: {best_fallback_angle:.2f}°")
        print(f"Worst gap (min): {best_fallback_worst_gap:.2f}px")
        print(f"Average gap: {best_fallback['average_gap']:.2f}px")
        print(f"All gaps: {[f'{g:.1f}' for g in best_fallback['gaps']]}")

        return {
            "success": False,
            "is_fallback": True,
            "angle": best_fallback["angle"],
            "angle_degrees": best_fallback_angle,
            "configurations": best_fallback["configurations"],
            "average_gap": best_fallback["average_gap"],
            "gap_variance": best_fallback["gap_variance"],
            "worst_gap": best_fallback_worst_gap,
            "gaps": best_fallback["gaps"],
            "pair_extension": best_fallback_extensions[0] if best_fallback_extensions else 0,
            "pair_extensions": best_fallback_extensions,
            "min_gap": best_fallback.get("min_gap", strand_width),
            "max_gap": best_fallback.get("max_gap", strand_width * 1.5),
            "message": f"Fallback: best candidate at {best_fallback_angle:.2f}° (worst gap: {best_fallback_worst_gap:.1f}px)"
        }
    else:
        print(f"\n=== No Solution Found ===")
        print(f"Tried {combo_count} extension combinations (0 to {max_pair_extension}px, step {pair_extension_step})")
        return {
            "success": False,
            "message": f"Could not find any valid configuration or fallback ({combo_count} extension combos tried)"
        }


def align_vertical_strands_parallel(all_strands, n, m,
                                     angle_step_degrees=0.5,
                                     max_extension=100.0, strand_width=46,
                                     custom_angle_min=None, custom_angle_max=None,
                                     on_config_callback=None,
                                     max_pair_extension=200,
                                     pair_extension_step=10,
                                     k=0, direction="cw",
                                     use_gpu=False,
                                     angle_mode="first_strand"):
    """
    Parallel alignment of vertical _4/_5 strands using first-last pair approach.

    Algorithm:
    1. Calculate angle range from the selected auto mode (or use custom range)
    2. LAST strand should use angle + 180° (opposite direction)
    3. For each angle in range, check if first and last can reach their targets
    4. Then check if MIDDLE strands can adapt (with extensions if needed)
    5. Validate gaps are within strand_width to strand_width*1.5

    Args:
        all_strands: List of all strand dictionaries
        n: Number of horizontal strand sets
        m: Number of vertical strand sets (vertical sets are n+1 to n+m)
        angle_step_degrees: Step size for angle search (default 0.5°)
        max_extension: Maximum allowed extension for _2/_3 strands
        strand_width: Width of strands for gap calculation (default 46)
        custom_angle_min: Optional custom minimum angle (degrees)
        custom_angle_max: Optional custom maximum angle (degrees)
        on_config_callback: Optional callback(angle_deg, extension, result) called for each config

    Returns:
        dict: {
            "success": bool,
            "angle": float (radians),
            "configurations": list of strand configurations,
            "average_gap": float,
            "gap_variance": float,
            "message": str
        }
    """

    # Build k-based vertical strand set
    if k != 0:
        _, _, v_names_set, v_order_list = _build_k_based_strand_sets(m, n, k, direction)
    else:
        v_names_set = None
        v_order_list = None

    # Collect ALL _2/_3 strands (needed for structural pairing regardless of group)
    strands_2 = []
    strands_3 = []
    # Collect vertical _4/_5 strands (filtered by k-based group)
    strands_4 = []
    strands_5 = []

    for strand in all_strands:
        if strand["type"] != "AttachedStrand":
            continue

        layer_name = strand["layer_name"]
        set_num = strand["set_number"]

        if layer_name.endswith("_2"):
            strands_2.append(strand)
        elif layer_name.endswith("_3"):
            strands_3.append(strand)
        elif layer_name.endswith("_4"):
            if v_names_set is not None:
                if layer_name in v_names_set:
                    strands_4.append(strand)
            else:
                if n < set_num <= n + m:
                    strands_4.append(strand)
        elif layer_name.endswith("_5"):
            if v_names_set is not None:
                if layer_name in v_names_set:
                    strands_5.append(strand)
            else:
                if n < set_num <= n + m:
                    strands_5.append(strand)

    if not strands_4 and not strands_5:
        return {
            "success": False,
            "message": "No vertical _4/_5 strands found"
        }

    # Collect all vertical _4/_5 strands with their target positions
    vertical_strands = []

    for s4 in strands_4:
        set_num = s4["set_number"]
        # Find corresponding _2 strand
        s2 = next((s for s in strands_2 if s["set_number"] == set_num), None)
        if s2:
            vertical_strands.append({
                "strand_4_5": s4,
                "strand_2_3": s2,
                "type": "_4",
                "set_number": set_num,
                "original_start": {"x": s4["start"]["x"], "y": s4["start"]["y"]},
                "target_position": {"x": s4["end"]["x"], "y": s4["end"]["y"]},
            })

    for s5 in strands_5:
        set_num = s5["set_number"]
        # Find corresponding _3 strand
        s3 = next((s for s in strands_3 if s["set_number"] == set_num), None)
        if s3:
            vertical_strands.append({
                "strand_4_5": s5,
                "strand_2_3": s3,
                "type": "_5",
                "set_number": set_num,
                "original_start": {"x": s5["start"]["x"], "y": s5["start"]["y"]},
                "target_position": {"x": s5["end"]["x"], "y": s5["end"]["y"]},
            })

    # Sort by k-based order if available, otherwise by set_number
    if v_order_list is not None:
        v_order_index = {name: i for i, name in enumerate(v_order_list)}
        vertical_strands.sort(key=lambda v: v_order_index.get(v["strand_4_5"]["layer_name"], 999))
    else:
        vertical_strands.sort(key=lambda v: (v["set_number"], v["type"]))

    num_strands = len(vertical_strands)
    if num_strands < 2:
        return {
            "success": False,
            "message": "Need at least 2 vertical strands for parallel alignment"
        }

    # Build outside-in pairs: (1st, last), (2nd, one-before-last), etc.
    pairs = [(vertical_strands[i], vertical_strands[num_strands - 1 - i])
             for i in range(num_strands // 2)]
    # If odd number of strands, middle strand gets a solo pair entry
    if num_strands % 2 == 1:
        mid = num_strands // 2
        pairs.append((vertical_strands[mid], None))

    # Compute _2/_3 extension directions and store originals for ALL pair members
    pair_directions = []  # [(left_nx, left_ny, right_nx, right_ny), ...]
    pair_originals = []   # [(left_orig, right_orig), ...]

    for left_strand, right_strand in pairs:
        # Left strand direction
        l_s23 = left_strand["strand_2_3"]
        l_dx = l_s23["end"]["x"] - l_s23["start"]["x"]
        l_dy = l_s23["end"]["y"] - l_s23["start"]["y"]
        l_len = math.sqrt(l_dx**2 + l_dy**2)
        l_nx = l_dx / l_len if l_len > 0.001 else 0
        l_ny = l_dy / l_len if l_len > 0.001 else 0

        # Right strand direction (if exists)
        if right_strand is not None:
            r_s23 = right_strand["strand_2_3"]
            r_dx = r_s23["end"]["x"] - r_s23["start"]["x"]
            r_dy = r_s23["end"]["y"] - r_s23["start"]["y"]
            r_len = math.sqrt(r_dx**2 + r_dy**2)
            r_nx = r_dx / r_len if r_len > 0.001 else 0
            r_ny = r_dy / r_len if r_len > 0.001 else 0
        else:
            r_nx, r_ny = 0, 0

        pair_directions.append((l_nx, l_ny, r_nx, r_ny))
        left_orig = {"x": left_strand["original_start"]["x"], "y": left_strand["original_start"]["y"]}
        right_orig = {"x": right_strand["original_start"]["x"], "y": right_strand["original_start"]["y"]} if right_strand else None
        pair_originals.append((left_orig, right_orig))

    print(f"\n=== Vertical Parallel Alignment (Per-Pair Independent Extension) ===")
    print(f"Found {num_strands} vertical _4/_5 strands, {len(pairs)} pairs")
    print(f"Max extension: {max_extension}")
    print(f"Strand width: {strand_width}")
    print(f"Per-pair extension: 0 to {max_pair_extension} px (step {pair_extension_step})")

    # Debug: Print details of each strand and pair membership
    print(f"\n--- Vertical Strand Details ---")
    for i, v in enumerate(vertical_strands):
        dx = v['target_position']['x'] - v['original_start']['x']
        dy = v['target_position']['y'] - v['original_start']['y']
        angle = math.degrees(math.atan2(dy, dx))
        # Find which pair this strand belongs to
        pair_label = ""
        for pi, (left, right) in enumerate(pairs):
            if v is left:
                pair_label = f" [Pair {pi+1} LEFT]"
            elif v is right:
                pair_label = f" [Pair {pi+1} RIGHT]"
        print(f"  {i+1}. {v['strand_4_5']['layer_name']}{pair_label} angle={angle:.1f}°")

    # Use first strand for angle calculation reference
    first_strand = vertical_strands[0]

    # Calculate the initial angle of the FIRST strand (from start to target)
    first_dx = first_strand["target_position"]["x"] - first_strand["original_start"]["x"]
    first_dy = first_strand["target_position"]["y"] - first_strand["original_start"]["y"]
    first_initial_angle = math.degrees(math.atan2(first_dy, first_dx))

    # Use custom angle range if provided, otherwise compute from angle_mode
    use_custom_v = custom_angle_min is not None and custom_angle_max is not None
    if use_custom_v:
        base_angle_min = custom_angle_min
        base_angle_max = custom_angle_max
        print(f"\n--- Using CUSTOM Vertical Angle Range ---")
        print(f"    Custom range: {base_angle_min:.2f}° to {base_angle_max:.2f}°")
    else:
        _adapted = [{"strand": v["strand_4_5"], "start": v["original_start"], "target": v["target_position"]}
                     for v in vertical_strands]
        _, base_angle_min, base_angle_max, _pair_dbg = _compute_pair_angle_range(_adapted, angle_mode)
        print(f"\n--- Angle Range (mode={angle_mode}) ---")
        print(f"    First strand initial angle: {first_initial_angle:.2f}°")
        print(f"    Computed range: {base_angle_min:.2f}° to {base_angle_max:.2f}°")
        for ln, rn, pa in _pair_dbg:
            print(f"      Pair ({ln}, {rn}): {pa:.1f}°")

    # Nested loops: one extension range per pair (via itertools.product)
    all_valid_results = []

    # Track best fallback candidate (max-min optimization: maximize the worst gap)
    best_fallback = None
    best_fallback_worst_gap = -float('inf')
    best_fallback_extensions = tuple(0 for _ in pairs)
    best_fallback_angle = 0

    ext_range_values = list(range(0, max_pair_extension + pair_extension_step, pair_extension_step))
    num_pairs = len(pairs)
    total_combos = len(ext_range_values) ** num_pairs
    combo_count = total_combos
    can_use_gpu = use_gpu and _check_cupy_available()
    combo_guard = get_alignment_combo_guard(
        total_combos,
        num_pairs,
        max_pair_extension,
        pair_extension_step,
        use_gpu=can_use_gpu,
    )

    if combo_guard:
        print(f"\n=== Search Skipped ===")
        print(combo_guard["message"])
        return {
            "success": False,
            "message": combo_guard["message"],
        }

    # === GPU or CPU combo search ===
    if can_use_gpu:
        print(f"\n--- GPU search (vertical): {total_combos} extension combinations ({len(ext_range_values)} values x {num_pairs} pairs) ---")
        all_valid_results, gpu_fallback = _cupy_search_combo_chunks(
            vertical_strands, pairs, pair_directions, pair_originals,
            first_strand, ext_range_values, angle_step_degrees,
            max_extension, strand_width,
            custom_angle_min if use_custom_v else None,
            custom_angle_max if use_custom_v else None,
            angle_mode=angle_mode,
            on_config_callback=on_config_callback,
            chunk_size=2048,
            direction_type="vertical",
            allow_inner_extensions=False,
        )
        if gpu_fallback:
            best_fallback = gpu_fallback
            best_fallback_worst_gap = gpu_fallback.get("worst_gap", 0)
            best_fallback_extensions = gpu_fallback.get("pair_extensions", (0,))
            best_fallback_angle = gpu_fallback.get("angle_degrees", 0)
    else:
        if use_gpu:
            print("WARNING: GPU requested but CuPy not available. Falling back to NumPy.")
        print(f"\n--- Searching {total_combos} extension combinations ({len(ext_range_values)} values x {num_pairs} pairs) [numpy-accelerated] ---")
        (
            all_valid_results,
            best_fallback,
            best_fallback_worst_gap,
            best_fallback_extensions,
            best_fallback_angle,
            combo_count,
        ) = _search_combo_space_cpu(
            vertical_strands,
            pairs,
            pair_directions,
            pair_originals,
            ext_range_values,
            angle_step_degrees,
            max_extension,
            strand_width,
            custom_angle_min if use_custom_v else None,
            custom_angle_max if use_custom_v else None,
            angle_mode,
            on_config_callback=on_config_callback,
            direction_type="vertical",
        )

    best_result = _select_best_result(all_valid_results)
    if best_result:
        best_pair_extensions = best_result.get("pair_extensions", (0,))
        print(f"\n=== Best Vertical Solution Found ===")
        print(f"Pair extensions: {best_pair_extensions}")
        print(f"Angle: {best_result['angle_degrees']:.2f}°")
        print(f"Gap variance: {best_result['gap_variance']:.4f}")
        print(f"Average gap: {best_result['average_gap']:.2f}")
        print(f"First-last distance: {best_result.get('first_last_distance', 'N/A')}")

        return {
            "success": True,
            "angle": best_result["angle"],
            "angle_degrees": best_result["angle_degrees"],
            "configurations": best_result["configurations"],
            "average_gap": best_result["average_gap"],
            "gap_variance": best_result["gap_variance"],
            "first_last_distance": best_result.get("first_last_distance"),
            "pair_extension": best_pair_extensions[0] if best_pair_extensions else 0,
            "pair_extensions": best_pair_extensions,
            "min_gap": best_result.get("min_gap", strand_width),
            "max_gap": best_result.get("max_gap", strand_width * 1.5),
            "message": f"Found vertical parallel configuration at {best_result['angle_degrees']:.2f}° (pair exts: {best_pair_extensions})"
        }
    elif best_fallback:
        # Return best fallback candidate (max-min: the one with maximum worst gap)
        print(f"\n=== Best Vertical Fallback Candidate (no valid solution) ===")
        print(f"Pair extensions: {best_fallback_extensions}")
        print(f"Angle: {best_fallback_angle:.2f}°")
        print(f"Worst gap (min): {best_fallback_worst_gap:.2f}px")
        print(f"Average gap: {best_fallback['average_gap']:.2f}px")
        print(f"All gaps: {[f'{g:.1f}' for g in best_fallback['gaps']]}")

        return {
            "success": False,
            "is_fallback": True,
            "angle": best_fallback["angle"],
            "angle_degrees": best_fallback_angle,
            "configurations": best_fallback["configurations"],
            "average_gap": best_fallback["average_gap"],
            "gap_variance": best_fallback["gap_variance"],
            "worst_gap": best_fallback_worst_gap,
            "gaps": best_fallback["gaps"],
            "pair_extension": best_fallback_extensions[0] if best_fallback_extensions else 0,
            "pair_extensions": best_fallback_extensions,
            "min_gap": best_fallback.get("min_gap", strand_width),
            "max_gap": best_fallback.get("max_gap", strand_width * 1.5),
            "message": f"Fallback: best candidate at {best_fallback_angle:.2f}° (worst gap: {best_fallback_worst_gap:.1f}px)"
        }
    else:
        print(f"\n=== No Solution Found ===")
        print(f"Tried {combo_count} extension combinations (0 to {max_pair_extension}px, step {pair_extension_step})")
        return {
            "success": False,
            "message": f"Could not find any valid configuration or fallback ({combo_count} extension combos tried)"
        }


def try_angle_configuration_first_last(
    strands_list,
    angle_rad,
    max_extension,
    strand_width,
    verbose=False,
    allow_inner_extensions=True,
):
    """
    Try a specific angle using the FIRST-LAST pair approach.

    Algorithm:
    1. FIRST strand projects to target at angle θ (or θ+180° if going left)
    2. LAST strand projects at opposite angle
    3. For 2 strands: search extension combinations to find valid gap
    4. For 3+ strands: MIDDLE strands adapt with extensions
    5. Validate gaps are within [strand_width+10, strand_width*1.5]

    Returns:
        dict with "valid", "configurations", "gaps", "gap_variance", "average_gap"
    """
    min_gap = strand_width + 10     # 56 px for width 46
    max_gap = strand_width * 1.5    # 69 px

    if len(strands_list) < 2:
        return {"valid": False, "reason": "Need at least 2 strands"}

    angle_deg = math.degrees(angle_rad)

    # Helper function to compute strand config for a given extension
    def compute_strand_config(h_strand, extension):
        original_start = h_strand["original_start"]
        target_position = h_strand["target_position"]

        dx_to_target = target_position["x"] - original_start["x"]
        dy_to_target = target_position["y"] - original_start["y"]
        distance_to_target = math.sqrt(dx_to_target**2 + dy_to_target**2)

        if distance_to_target < 0.001:
            return None

        # Use dot product with the search angle to determine direction alignment.
        # This correctly handles all angle quadrants (the old dy>=0/dx>=0 heuristic
        # fails for angles like ~-57° where cos>0 but sin<0).
        goes_positive = (dx_to_target * math.cos(angle_rad) + dy_to_target * math.sin(angle_rad)) >= 0

        strand_angle = angle_rad if goes_positive else angle_rad + math.pi
        cos_a = math.cos(strand_angle)
        sin_a = math.sin(strand_angle)

        s2_3 = h_strand["strand_2_3"]
        s2_3_dx = s2_3["end"]["x"] - s2_3["start"]["x"]
        s2_3_dy = s2_3["end"]["y"] - s2_3["start"]["y"]
        s2_3_len = math.sqrt(s2_3_dx**2 + s2_3_dy**2)

        if s2_3_len < 0.001:
            return None

        s2_3_nx = s2_3_dx / s2_3_len
        s2_3_ny = s2_3_dy / s2_3_len

        extended_start_x = original_start["x"] + extension * s2_3_nx
        extended_start_y = original_start["y"] + extension * s2_3_ny

        dx = target_position["x"] - extended_start_x
        dy = target_position["y"] - extended_start_y
        length = dx * cos_a + dy * sin_a

        if length <= 10:
            return None

        end_x = extended_start_x + length * cos_a
        end_y = extended_start_y + length * sin_a

        return {
            "strand": h_strand,
            "extended_start": {"x": extended_start_x, "y": extended_start_y},
            "end": {"x": end_x, "y": end_y},
            "length": length,
            "extension": extension,
            "angle": strand_angle,
            "goes_positive": goes_positive,
        }

    extension_values = (
        range(0, int(max_extension) + 1, 5)
        if allow_inner_extensions
        else (0,)
    )

    # Special case: exactly 2 strands - search for extension combo with valid gap
    if len(strands_list) == 2:
        first_strand = strands_list[0]
        last_strand = strands_list[1]

        best_config_pair = None
        best_gap_diff = float('inf')  # How close to ideal gap (center of range)
        ideal_gap = (min_gap + max_gap) / 2  # 57.5 px

        # Search extension combinations
        for ext1 in extension_values:
            config1 = compute_strand_config(first_strand, ext1)
            if not config1:
                continue

            # Precompute line params for config1 (reused for all ext2 iterations)
            line_params1 = precompute_line_params(config1["extended_start"], config1["end"])

            for ext2 in extension_values:
                config2 = compute_strand_config(last_strand, ext2)
                if not config2:
                    continue

                # Calculate gap using fast precomputed method
                px, py = config2["extended_start"]["x"], config2["extended_start"]["y"]
                gap = fast_perpendicular_distance(line_params1, px, py)
                abs_gap = abs(gap)

                # Check if gap is in valid range
                if min_gap <= abs_gap <= max_gap:
                    gap_diff = abs(abs_gap - ideal_gap)
                    if gap_diff < best_gap_diff:
                        best_gap_diff = gap_diff
                        best_config_pair = (config1, config2, abs_gap, gap)

        if best_config_pair:
            config1, config2, abs_gap, signed_gap = best_config_pair
            return {
                "valid": True,
                "configurations": [config1, config2],
                "gaps": [abs_gap],
                "signed_gaps": [signed_gap],
                "gap_variance": 0,
                "average_gap": abs_gap,
                "worst_gap": abs_gap,
                "angle": angle_rad,
                "min_gap": min_gap,
                "max_gap": max_gap,
            }
        else:
            # No valid gap found - return fallback info
            # Try to find best available gap
            config1 = compute_strand_config(first_strand, 0)
            config2 = compute_strand_config(last_strand, 0)
            if config1 and config2:
                line_params1 = precompute_line_params(config1["extended_start"], config1["end"])
                px, py = config2["extended_start"]["x"], config2["extended_start"]["y"]
                gap = fast_perpendicular_distance(line_params1, px, py)
                abs_gap = abs(gap)
                fallback_data = {
                    "configurations": [config1, config2],
                    "gaps": [abs_gap],
                    "signed_gaps": [gap],
                    "gap_variance": 0,
                    "average_gap": abs_gap,
                    "worst_gap": abs_gap,
                    "angle": angle_rad,
                    "min_gap": min_gap,
                    "max_gap": max_gap,
                }
                if abs_gap < min_gap:
                    return {"valid": False, "reason": f"Gap too small ({abs_gap:.1f} < {min_gap})", "fallback": fallback_data, "directions_valid": True}
                else:
                    return {"valid": False, "reason": f"Gap too large ({abs_gap:.1f} > {max_gap})", "fallback": fallback_data, "directions_valid": True}
            return {"valid": False, "reason": "Could not compute configs for 2-strand case"}

    # For 3+ strands: original logic
    configurations = []

    for idx, h_strand in enumerate(strands_list):
        best_config = None

        for extension in extension_values:
            config = compute_strand_config(h_strand, extension)
            if config:
                best_config = config
                break

        if not best_config:
            if verbose:
                print(f"    FAILED: {h_strand['strand_4_5']['layer_name']} - no valid length at angle {angle_deg:.2f}°")
            return {"valid": False, "reason": f"Strand {h_strand['strand_4_5']['layer_name']} no valid length"}

        configurations.append(best_config)

    # Calculate gaps between consecutive strands using fast precomputed method
    gaps = []
    signed_gaps = []

    # Precompute all line parameters for speed
    line_params_list = [
        precompute_line_params(cfg["extended_start"], cfg["end"])
        for cfg in configurations
    ]

    for i in range(len(configurations) - 1):
        config2 = configurations[i + 1]
        px, py = config2["extended_start"]["x"], config2["extended_start"]["y"]
        signed_gap = fast_perpendicular_distance(line_params_list[i], px, py)

        # Flip sign for odd-indexed gaps (where LINE strand is _5, which has 180° opposite direction)
        if i % 2 == 1:
            signed_gap = -signed_gap

        signed_gaps.append(signed_gap)
        gaps.append(abs(signed_gap))

    if not gaps:
        return {"valid": True, "configurations": configurations, "gaps": [], "gap_variance": 0, "average_gap": 0, "min_gap": min_gap, "max_gap": max_gap}

    # Calculate statistics for fallback tracking
    gap_sum = sum(gaps)
    average_gap = gap_sum / len(gaps)
    gap_variance = sum((g - average_gap)**2 for g in gaps) / len(gaps)
    worst_gap = min(gaps)  # The smallest gap is the "worst" for max-min optimization

    # Build fallback data (always available even if invalid)
    fallback_data = {
        "configurations": configurations,
        "gaps": gaps,
        "signed_gaps": signed_gaps,
        "gap_variance": gap_variance,
        "average_gap": average_gap,
        "worst_gap": worst_gap,
        "angle": angle_rad,
        "min_gap": min_gap,
        "max_gap": max_gap,
    }

    # Validate gaps
    # 1. Determine expected direction from first-to-last (using first strand's line as reference)
    last_config = configurations[-1]
    px, py = last_config["extended_start"]["x"], last_config["extended_start"]["y"]
    first_to_last_signed = fast_perpendicular_distance(line_params_list[0], px, py)
    expected_sign = 1 if first_to_last_signed >= 0 else -1

    # 2. Check each gap - track if directions are all correct
    directions_valid = True
    for i, sg in enumerate(signed_gaps):
        abs_gap = abs(sg)

        # Check direction (no crossing)
        if expected_sign > 0 and sg <= 0:
            directions_valid = False
            if verbose:
                print(f"    Gap {i} wrong direction: {sg:.2f}")
            return {"valid": False, "reason": f"Gap {i} wrong direction ({sg:.2f})", "fallback": fallback_data, "directions_valid": False}
        elif expected_sign < 0 and sg >= 0:
            directions_valid = False
            if verbose:
                print(f"    Gap {i} wrong direction: {sg:.2f}")
            return {"valid": False, "reason": f"Gap {i} wrong direction ({sg:.2f})", "fallback": fallback_data, "directions_valid": False}

        # Check gap range [strand_width, strand_width*1.5]
        if abs_gap < min_gap:
            if verbose:
                print(f"    Gap {i} too small: {abs_gap:.2f} < {min_gap}")
            return {"valid": False, "reason": f"Gap {i} too small ({abs_gap:.2f} < {min_gap})", "fallback": fallback_data, "directions_valid": directions_valid}

        if abs_gap > max_gap:
            if verbose:
                print(f"    Gap {i} too large: {abs_gap:.2f} > {max_gap}")
            return {"valid": False, "reason": f"Gap {i} too large ({abs_gap:.2f} > {max_gap})", "fallback": fallback_data, "directions_valid": directions_valid}

    return {
        "valid": True,
        "configurations": configurations,
        "gaps": gaps,
        "signed_gaps": signed_gaps,
        "gap_variance": gap_variance,
        "average_gap": average_gap,
        "worst_gap": worst_gap,
        "angle": angle_rad,
        "min_gap": min_gap,
        "max_gap": max_gap,
    }


def try_angle_configuration(horizontal_strands, angle_rad, emoji_area_radius, max_extension, verbose=False, strand_width=46):
    """
    Try a specific angle and check if all strands can be made parallel.

    For parallel strands going in OPPOSITE directions (like _4 going right, _5 going left),
    we use angle for one direction and angle+180° for the opposite direction.
    This ensures they have the same SLOPE (parallel) even though they go opposite ways.

    Gap constraints:
    - All gaps between consecutive strands should be between strand_width+10 and strand_width*1.5
    - Strands should maintain their relative order (not cross)

    For each strand:
    1. Determine its natural direction (left or right based on emoji target)
    2. Use angle or angle+180° based on direction
    3. Check if end point falls within emoji area
    4. Calculate required extension for _2/_3 (if any)

    Returns:
        dict with "valid", "configurations", "gaps", "gap_variance", "average_gap"
    """
    # Gap constraints: strand_width+10 to strand_width * 1.5
    min_gap = strand_width + 10     # 56 px for width 46
    max_gap = strand_width * 1.5    # 69 px for width 46
    configurations = []
    angle_deg = math.degrees(angle_rad)

    for h_strand in horizontal_strands:
        original_start = h_strand["original_start"]
        target_position = h_strand["target_position"]

        # Calculate direction to emoji target
        dx_to_target = target_position["x"] - original_start["x"]
        dy_to_target = target_position["y"] - original_start["y"]
        distance_to_target = math.sqrt(dx_to_target**2 + dy_to_target**2)

        if distance_to_target < 0.001:
            return {"valid": False, "reason": "Target at start"}

        # Determine if strand is predominantly horizontal or vertical
        is_vertical = abs(dy_to_target) > abs(dx_to_target)

        if is_vertical:
            # For vertical strands, check if going down (positive y)
            goes_positive = dy_to_target >= 0
        else:
            # For horizontal strands, check if going right (positive x)
            goes_positive = dx_to_target >= 0

        # For parallel strands: use angle for positive-going, angle+180° for negative-going
        # This ensures same slope (parallel) regardless of direction
        if goes_positive:
            strand_angle = angle_rad
        else:
            strand_angle = angle_rad + math.pi  # Add 180°

        cos_a = math.cos(strand_angle)
        sin_a = math.sin(strand_angle)

        # Try different extensions and lengths to find one that lands in emoji area
        best_length = None
        best_end = None
        best_extension = 0
        best_extended_start = None

        for extension in range(0, int(max_extension) + 1, 2):  # Finer extension steps
            # Extended start point (move along _2/_3 direction)
            s2_3 = h_strand["strand_2_3"]
            s2_3_dx = s2_3["end"]["x"] - s2_3["start"]["x"]
            s2_3_dy = s2_3["end"]["y"] - s2_3["start"]["y"]
            s2_3_len = math.sqrt(s2_3_dx**2 + s2_3_dy**2)

            if s2_3_len < 0.001:
                continue

            # Normalize _2/_3 direction
            s2_3_nx = s2_3_dx / s2_3_len
            s2_3_ny = s2_3_dy / s2_3_len

            # Extended start = original start + extension along _2/_3 direction
            extended_start_x = original_start["x"] + extension * s2_3_nx
            extended_start_y = original_start["y"] + extension * s2_3_ny

            # Try different lengths at the strand's angle
            for length in range(10, 400, 2):  # Finer length steps, longer max
                end_x = extended_start_x + length * cos_a
                end_y = extended_start_y + length * sin_a

                # Check if end is within emoji area
                dist_to_emoji = math.sqrt(
                    (end_x - target_position["x"])**2 +
                    (end_y - target_position["y"])**2
                )

                if dist_to_emoji <= emoji_area_radius:
                    best_length = length
                    best_end = {"x": end_x, "y": end_y}
                    best_extension = extension
                    best_extended_start = {"x": extended_start_x, "y": extended_start_y}
                    break

            if best_length is not None:
                break

        if best_length is None:
            if verbose:
                print(f"    FAILED: {h_strand['strand_4_5']['layer_name']} - Could not reach emoji area")
                print(f"            Start: ({original_start['x']:.1f}, {original_start['y']:.1f})")
                print(f"            Target: ({target_position['x']:.1f}, {target_position['y']:.1f})")
                print(f"            Goes positive: {goes_positive}, Strand angle: {math.degrees(strand_angle):.1f}°")
            return {"valid": False, "reason": f"Strand {h_strand['strand_4_5']['layer_name']} cannot reach emoji area"}

        configurations.append({
            "strand": h_strand,
            "extended_start": best_extended_start,
            "end": best_end,
            "length": best_length,
            "extension": best_extension,
            "angle": strand_angle,
            "goes_positive": goes_positive,
        })

    # Calculate gaps between consecutive parallel strands using SIGNED distance
    # This ensures we can verify strands maintain correct order
    gaps = []
    signed_gaps = []

    for i in range(len(configurations) - 1):
        config1 = configurations[i]
        config2 = configurations[i + 1]

        # Calculate signed perpendicular distance
        signed_gap = calculate_signed_perpendicular_distance(
            config1["extended_start"],
            config1["end"],
            config2["extended_start"]
        )
        signed_gaps.append(signed_gap)
        gaps.append(abs(signed_gap))

    if not gaps:
        return {"valid": True, "configurations": configurations, "gaps": [], "gap_variance": 0, "average_gap": 0}

    # Determine expected direction from first-to-last relationship
    # All gaps should have the same sign (direction)
    if len(configurations) >= 2:
        # Calculate direction from first to last strand
        first_config = configurations[0]
        last_config = configurations[-1]

        first_to_last_signed = calculate_signed_perpendicular_distance(
            first_config["extended_start"],
            first_config["end"],
            last_config["extended_start"]
        )

        # Expected direction: if first_to_last is positive, all gaps should be positive
        # if first_to_last is negative, all gaps should be negative
        expected_sign = 1 if first_to_last_signed >= 0 else -1

        # Validate all gaps:
        # 1. Same direction (same sign)
        # 2. Within valid range: min_gap (strand_width) to max_gap (strand_width*1.5)
        for i, sg in enumerate(signed_gaps):
            abs_gap = abs(sg)

            # Check if gap has correct sign (strands maintain order, don't cross)
            if expected_sign > 0 and sg <= 0:
                if verbose:
                    print(f"    Gap {i} direction mismatch: expected positive, got {sg:.2f} (strands crossing)")
                return {"valid": False, "reason": f"Gap {i} wrong direction - strands crossing ({sg:.2f})"}
            elif expected_sign < 0 and sg >= 0:
                if verbose:
                    print(f"    Gap {i} direction mismatch: expected negative, got {sg:.2f} (strands crossing)")
                return {"valid": False, "reason": f"Gap {i} wrong direction - strands crossing ({sg:.2f})"}

            # Check if gap is within valid range [min_gap, max_gap]
            if abs_gap < min_gap:
                if verbose:
                    print(f"    Gap {i} too small: {abs_gap:.2f} < {min_gap}")
                return {"valid": False, "reason": f"Gap {i} too small ({abs_gap:.2f} < {min_gap})"}

            if abs_gap > max_gap:
                if verbose:
                    print(f"    Gap {i} too large: {abs_gap:.2f} > {max_gap:.2f}")
                return {"valid": False, "reason": f"Gap {i} too large ({abs_gap:.2f} > {max_gap:.2f})"}

    # Calculate variance of gaps (lower = more equal)
    average_gap = sum(gaps) / len(gaps)
    gap_variance = sum((g - average_gap)**2 for g in gaps) / len(gaps)

    return {
        "valid": True,
        "configurations": configurations,
        "gaps": gaps,
        "signed_gaps": signed_gaps,
        "gap_variance": gap_variance,
        "average_gap": average_gap,
        "angle": angle_rad,
        "min_gap": min_gap,
        "max_gap": max_gap,
    }


def calculate_perpendicular_distance(line_start, line_end, point):
    """
    Calculate perpendicular distance from a point to a line defined by two points.

    Uses the formula: |((y2-y1)*px - (x2-x1)*py + x2*y1 - y2*x1)| / sqrt((y2-y1)^2 + (x2-x1)^2)
    """
    x1, y1 = line_start["x"], line_start["y"]
    x2, y2 = line_end["x"], line_end["y"]
    px, py = point["x"], point["y"]

    numerator = abs((y2 - y1) * px - (x2 - x1) * py + x2 * y1 - y2 * x1)
    denominator = math.sqrt((y2 - y1)**2 + (x2 - x1)**2)

    if denominator < 0.001:
        return 0

    return numerator / denominator


def precompute_line_params(line_start, line_end):
    """
    Precompute line parameters for fast repeated distance calculations.

    Returns tuple: (dx, dy, c, inv_length) where:
    - dx, dy: direction vector components
    - c: constant term (x2*y1 - y2*x1)
    - inv_length: 1/line_length (precomputed to avoid repeated sqrt and division)
    """
    x1, y1 = line_start["x"], line_start["y"]
    x2, y2 = line_end["x"], line_end["y"]

    dx = x2 - x1
    dy = y2 - y1
    c = x2 * y1 - y2 * x1

    length_sq = dx * dx + dy * dy
    if length_sq < 0.000001:
        return (dx, dy, c, 0.0)

    inv_length = 1.0 / math.sqrt(length_sq)
    return (dy, -dx, c, inv_length)  # Note: (dy, -dx) for perpendicular


def fast_perpendicular_distance(line_params, px, py):
    """
    Fast perpendicular distance using precomputed line parameters.

    Args:
        line_params: tuple from precompute_line_params()
        px, py: point coordinates (raw floats, not dict)

    Returns:
        Signed perpendicular distance
    """
    a, b, c, inv_length = line_params
    if inv_length == 0.0:
        return 0.0
    return (a * px + b * py + c) * inv_length


def calculate_signed_perpendicular_distance(line_start, line_end, point):
    """
    Calculate SIGNED perpendicular distance from a point to a line.

    Positive = point is on one side of the line
    Negative = point is on the other side

    This helps determine if strands maintain their relative order.

    Note: For multiple calculations to the same line, use precompute_line_params()
    and fast_perpendicular_distance() instead for better performance.
    """
    x1, y1 = line_start["x"], line_start["y"]
    x2, y2 = line_end["x"], line_end["y"]
    px, py = point["x"], point["y"]

    # Cross product gives signed distance
    numerator = (y2 - y1) * px - (x2 - x1) * py + x2 * y1 - y2 * x1
    denominator = math.sqrt((y2 - y1)**2 + (x2 - x1)**2)

    if denominator < 0.001:
        return 0

    return numerator / denominator


def apply_parallel_alignment(all_strands, alignment_result):
    """
    Apply the parallel alignment result to modify the strands.

    This function:
    1. Updates _4/_5 strand positions (start and end)
    2. Updates _2/_3 strand end positions (if extended)

    Args:
        all_strands: List of all strand dictionaries
        alignment_result: Result from align_horizontal_strands_parallel()

    Returns:
        List of modified strands
    """
    configurations = alignment_result.get("configurations") or []
    if not configurations:
        print("Cannot apply alignment: no configurations available")
        return all_strands

    # Build lookup for quick access
    strand_lookup = {s["layer_name"]: s for s in all_strands}

    for config in configurations:
        h_strand = config["strand"]
        strand_4_5 = h_strand["strand_4_5"]
        strand_2_3 = h_strand["strand_2_3"]

        # Update _4/_5 strand
        layer_name_4_5 = strand_4_5["layer_name"]
        if layer_name_4_5 in strand_lookup:
            strand_lookup[layer_name_4_5]["start"] = config["extended_start"].copy()
            strand_lookup[layer_name_4_5]["end"] = config["end"].copy()

            # Update control points
            strand_lookup[layer_name_4_5]["control_points"] = [
                config["extended_start"].copy(),
                config["end"].copy()
            ]
            strand_lookup[layer_name_4_5]["control_point_center"] = {
                "x": (config["extended_start"]["x"] + config["end"]["x"]) / 2,
                "y": (config["extended_start"]["y"] + config["end"]["y"]) / 2,
            }

        # Always update _2/_3 strand end to match _4/_5 start (ensures connection)
        layer_name_2_3 = strand_2_3["layer_name"]
        if layer_name_2_3 in strand_lookup:
            strand_lookup[layer_name_2_3]["end"] = config["extended_start"].copy()

            # Update control points
            if strand_lookup[layer_name_2_3].get("control_points") and len(strand_lookup[layer_name_2_3]["control_points"]) > 1:
                strand_lookup[layer_name_2_3]["control_points"][1] = config["extended_start"].copy()
            strand_lookup[layer_name_2_3]["control_point_center"] = {
                "x": (strand_lookup[layer_name_2_3]["start"]["x"] + config["extended_start"]["x"]) / 2,
                "y": (strand_lookup[layer_name_2_3]["start"]["y"] + config["extended_start"]["y"]) / 2,
            }

    print(f"\nApplied parallel alignment to {len(configurations)} strands")

    return list(strand_lookup.values())


def print_alignment_debug(alignment_result):
    """Print detailed debug information about the alignment result."""
    if not alignment_result["success"]:
        print(f"Alignment failed: {alignment_result['message']}")
        return

    print(f"\n{'='*60}")
    print(f"PARALLEL ALIGNMENT RESULT")
    print(f"{'='*60}")
    print(f"Angle: {alignment_result['angle_degrees']:.2f}° ({alignment_result['angle']:.4f} rad)")
    print(f"Average gap: {alignment_result['average_gap']:.2f} px")
    print(f"Gap variance: {alignment_result['gap_variance']:.4f}")

    # Print gap constraints
    min_gap = alignment_result.get("min_gap", 46)
    max_gap = alignment_result.get("max_gap", 69)
    print(f"Gap constraints: {min_gap:.1f} to {max_gap:.1f} px (strand_width to strand_width*1.5)")

    # Print gaps between strands
    gaps = alignment_result.get("gaps", [])
    signed_gaps = alignment_result.get("signed_gaps", [])
    if gaps:
        print(f"\nGaps between consecutive strands:")
        for i, (gap, sg) in enumerate(zip(gaps, signed_gaps)):
            in_range = "OK" if min_gap <= gap <= max_gap else "OUT OF RANGE"
            print(f"  Gap {i+1}-{i+2}: {gap:.2f} px (signed: {sg:+.2f}) [{in_range}]")

    print(f"\nStrand configurations:")

    for i, config in enumerate(alignment_result["configurations"]):
        h = config["strand"]
        print(f"\n  {i+1}. {h['strand_4_5']['layer_name']} (set {h['set_number']})")
        print(f"     Original start: ({h['original_start']['x']:.1f}, {h['original_start']['y']:.1f})")
        print(f"     Extended start: ({config['extended_start']['x']:.1f}, {config['extended_start']['y']:.1f})")
        print(f"     End:            ({config['end']['x']:.1f}, {config['end']['y']:.1f})")
        print(f"     Extension: {config['extension']:.1f} px")
        print(f"     Length: {config['length']:.1f} px")

    print(f"\n{'='*60}")
