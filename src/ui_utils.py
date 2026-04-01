"""Constants and helper functions shared across MxN CAD UI modules."""

import os


EMOJI_SET_ITEMS = [
    ("Default (System)", "default"),
    ("Twemoji (Twitter)", "twemoji"),
    ("OpenMoji", "openmoji"),
    ("JoyPixels", "joypixels"),
    ("Fluent 3D (Microsoft)", "fluent"),
]


def _get_active_history_state(data):
    """Return the current-step history state dict, or None for plain documents."""
    if not isinstance(data, dict) or data.get("type") != "OpenStrandStudioHistory":
        return None

    current_step = data.get("current_step", 1)
    for state in data.get("states", []):
        if isinstance(state, dict) and state.get("step") == current_step:
            state_data = state.get("data")
            if isinstance(state_data, dict):
                return state
    return None


def _get_active_strands(data):
    """Return the strands list for the active history step or plain document."""
    state = _get_active_history_state(data)
    if state is not None:
        return state.get("data", {}).get("strands", [])
    return data.get("strands", []) if isinstance(data, dict) else []


def _set_active_strands(data, strands):
    """Write strands back only to the active history step or plain document."""
    state = _get_active_history_state(data)
    if state is not None:
        state.setdefault("data", {})["strands"] = strands
    elif isinstance(data, dict):
        data["strands"] = strands


def _get_alignment_base_output_dir(script_dir, m, n, k, direction, pattern_type):
    """Return the output root used by Align Parallel exports."""
    diagram_name = f"{m}x{n}"
    return os.path.join(
        script_dir,
        "mxn", "mxn_output", diagram_name, f"k_{k}_{direction}_{pattern_type}"
    )


def _get_alignment_attempt_basename(
    pattern_type,
    m,
    n,
    k,
    direction,
    direction_type,
    extension,
    angle_deg,
    is_valid,
):
    """Return the attempt_options basename used by Align Parallel exports."""
    status = "valid" if is_valid else "invalid"
    return (
        f"{pattern_type}_{m}x{n}_k{k}_{direction}_{direction_type}_"
        f"ext{extension}_ang{angle_deg:.1f}_{status}"
    )


def _get_alignment_final_output_info(
    base_output_dir,
    pattern_type,
    m,
    n,
    k,
    direction,
    h_success,
    h_angle,
    v_success,
    v_angle,
):
    """Return folder and basename for the final Align Parallel export."""
    is_valid_solution = h_success and v_success
    output_subdir = os.path.join(
        base_output_dir,
        "best_solution" if is_valid_solution else "partial_options",
    )
    h_status = f"h{h_angle:.1f}" if h_success and h_angle is not None else "h_fail"
    v_status = f"v{v_angle:.1f}" if v_success and v_angle is not None else "v_fail"
    filename_base = f"mxn_{pattern_type}_{m}x{n}_k{k}_{direction}_{h_status}_{v_status}"
    return {
        "is_valid_solution": is_valid_solution,
        "output_subdir": output_subdir,
        "filename_base": filename_base,
    }


def _build_alignment_summary_text(
    pattern_type,
    m,
    n,
    k,
    direction,
    h_success,
    h_angle,
    h_gap,
    h_result,
    v_success,
    v_angle,
    v_gap,
    v_result,
    parameters,
):
    """Build the final alignment summary text saved next to the PNG/JSON."""
    is_valid_solution = h_success and v_success
    lines = [
        f"Pattern: {pattern_type.upper()} {m}x{n} k={k} {direction}",
        f"Result: {'SOLUTION' if is_valid_solution else 'INVALID'}",
        "=" * 60,
        "",
        "HORIZONTAL ALIGNMENT",
        "-" * 40,
    ]

    if h_success:
        lines.extend([
            "Status: SUCCESS",
            f"Angle: {h_angle:.2f}\N{DEGREE SIGN}",
            f"Average gap: {h_gap:.2f} px",
            f"Gap variance: {h_result.get('gap_variance', 'N/A')}",
            f"First-last distance: {h_result.get('first_last_distance', 'N/A')}",
            f"Pair extensions: {h_result.get('pair_extensions', 'N/A')}",
        ])
        for i, cfg in enumerate(h_result.get("configurations", [])):
            name = cfg.get("strand", {}).get("strand_4_5", {}).get("layer_name", f"strand_{i}")
            ext = cfg.get("extension", 0)
            length = cfg.get("length", 0)
            lines.append(f"  {name}: extension={ext:.1f}px, length={length:.1f}px")
    else:
        lines.extend([
            "Status: FAILED",
            f"Message: {h_result.get('message', 'Unknown')}",
        ])

    lines.extend([
        "",
        "VERTICAL ALIGNMENT",
        "-" * 40,
    ])

    if v_success:
        lines.extend([
            "Status: SUCCESS",
            f"Angle: {v_angle:.2f}\N{DEGREE SIGN}",
            f"Average gap: {v_gap:.2f} px",
            f"Gap variance: {v_result.get('gap_variance', 'N/A')}",
            f"First-last distance: {v_result.get('first_last_distance', 'N/A')}",
            f"Pair extensions: {v_result.get('pair_extensions', 'N/A')}",
        ])
        for i, cfg in enumerate(v_result.get("configurations", [])):
            name = cfg.get("strand", {}).get("strand_4_5", {}).get("layer_name", f"strand_{i}")
            ext = cfg.get("extension", 0)
            length = cfg.get("length", 0)
            lines.append(f"  {name}: extension={ext:.1f}px, length={length:.1f}px")
    else:
        lines.extend([
            "Status: FAILED",
            f"Message: {v_result.get('message', 'Unknown')}",
        ])

    lines.extend([
        "",
        "HORIZONTAL REFERENCE (for vertical context)",
        "-" * 40,
        f"H angle: {h_angle:.2f}\N{DEGREE SIGN}" if h_angle is not None else "H angle: N/A",
        f"H gap: {h_gap:.2f} px" if h_gap is not None else "H gap: N/A",
        f"H success: {h_success}",
        "",
        "PARAMETERS",
        "-" * 40,
        f"H angle range: {parameters.get('h_angle_range_text', 'N/A')}",
        f"V angle range: {parameters.get('v_angle_range_text', 'N/A')}",
        f"Custom angles: {parameters.get('custom_angles', False)}",
        f"Pair ext max: {parameters.get('pair_ext_max', 'N/A')}px",
        f"Pair ext step: {parameters.get('pair_ext_step', 'N/A')}px",
        f"Max extension: {parameters.get('max_extension', 'N/A')}px",
        f"Angle step: {parameters.get('angle_step', 'N/A')}\N{DEGREE SIGN}",
        f"Strand width: {parameters.get('strand_width', 'N/A')}px",
    ])

    return "\n".join(lines) + "\n"


def _build_alignment_attempt_text(
    pattern_type,
    m,
    n,
    k,
    direction,
    angle_deg,
    extension,
    result,
    direction_type,
    attempt_num,
    h_result_info=None,
):
    """Build a concise attempt report for attempt_options exports."""
    configs = result.get("configurations")
    if not configs and result.get("fallback"):
        configs = result["fallback"].get("configurations")

    data_source = result if result.get("configurations") else result.get("fallback", result)
    gaps = data_source.get("gaps", [])
    signed_gaps = data_source.get("signed_gaps", [])
    is_valid = bool(result.get("valid", False))
    dir_label = "HORIZONTAL" if direction_type == "horizontal" else "VERTICAL"

    lines = [
        "=" * 80,
        "                    PARALLEL ALIGNMENT ANALYSIS",
        "=" * 80,
        f"Pattern: {pattern_type.upper()} {m}x{n} | K: {k} | Direction: {direction.upper()}",
        (
            f"Attempt: #{attempt_num} | Angle: {angle_deg:.1f}\N{DEGREE SIGN} | "
            f"Extension: {extension}px | Status: {'VALID' if is_valid else 'INVALID'}"
        ),
        f"Direction: {dir_label}",
        "",
        f"Reason: {result.get('reason') or result.get('message') or 'N/A'}",
        f"Average gap: {data_source.get('average_gap', 'N/A')}",
        f"Gap variance: {data_source.get('gap_variance', 'N/A')}",
        f"Min gap: {data_source.get('min_gap', 'N/A')}",
        f"Max gap: {data_source.get('max_gap', 'N/A')}",
        f"Gaps: {gaps if gaps else '[]'}",
        f"Signed gaps: {signed_gaps if signed_gaps else '[]'}",
        "",
        "CONFIGURATIONS",
        "-" * 40,
    ]

    if configs:
        for i, cfg in enumerate(configs):
            name = cfg.get("strand", {}).get("strand_4_5", {}).get("layer_name", f"strand_{i}")
            ext = cfg.get("extension", 0)
            length = cfg.get("length", 0)
            start = cfg.get("extended_start", {})
            end = cfg.get("end", {})
            lines.append(
                f"{name}: extension={ext:.1f}px, length={length:.1f}px, "
                f"start=({start.get('x', 'N/A')}, {start.get('y', 'N/A')}), "
                f"end=({end.get('x', 'N/A')}, {end.get('y', 'N/A')})"
            )
    else:
        lines.append("No configurations available.")

    if direction_type == "vertical" and h_result_info is not None:
        lines.extend([
            "",
            "HORIZONTAL RESULT USED (Best from horizontal phase)",
            "-" * 40,
            f"Status: {'SUCCESS' if h_result_info.get('success') else 'FAILED/FALLBACK'}",
            f"Angle: {h_result_info.get('angle', 'N/A')}",
            f"Average Gap: {h_result_info.get('avg_gap', 'N/A')}",
            f"Gap Variance: {h_result_info.get('gap_variance', 'N/A')}",
            f"First-Last Distance: {h_result_info.get('first_last_distance', 'N/A')}",
            f"Pair Extensions: {h_result_info.get('pair_extensions', 'N/A')}",
        ])

    lines.extend([
        "",
        "=" * 80,
        f"Overall: {'VALID SOLUTION' if is_valid else 'INVALID'}",
        "=" * 80,
    ])
    return "\n".join(lines) + "\n"
