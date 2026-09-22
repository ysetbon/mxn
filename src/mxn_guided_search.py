"""
Policy-guided search over the pair-extension x angle grid.

The exhaustive aligner evaluates every pair-extension combo against every
angle. Here a decision policy picks which region of that grid to evaluate
next, the region is evaluated with the exact same validity math, and what it
produced feeds the next decision.

Two kinds of round:
  * explore  one cell (one extension band per opposite pair x one third of
             each combo's angle window), chosen by ranking unexplored cells
             with the policy's band / angle probabilities;
  * move     a small neighbourhood around the best (or closest) configuration
             so far, shifted per pair by the policy's proposed move.

Policies:
  * JevPolicy       TypeSafe's System One model (Jev) sees the group's geometry
                    and each round picks a strategy (refine / explore / stop),
                    per-pair moves and the angle third.
  * JevBandPolicy   the first, band-only Jev policy, kept for comparison.
  * HeuristicPolicy deterministic offline baseline (explore rounds only).

Enable from the environment with MXN_ALIGNMENT_GUIDED=jev|jev-bands|heuristic,
or pass `guided_search=` to the align functions.
"""

import itertools
import math
import os

ANGLE_THIRDS = (
    ("low", (0.0, 1.0 / 3.0)),
    ("middle", (1.0 / 3.0, 2.0 / 3.0)),
    ("high", (2.0 / 3.0, 1.0)),
)
_ANGLE_TIE_ORDER = {"middle": 0, "low": 1, "high": 2, "full": 0}

DEFAULT_BANDS = 4
DEFAULT_BUDGET_FRACTION = 0.35
DEFAULT_MAX_ROUNDS = 40
DEFAULT_STOP_THRESHOLD = 0.6
DEFAULT_PATIENCE = 3
DEFAULT_NEIGHBOURHOOD = 1
MIN_COMBOS_FOR_GUIDED = 64
HISTORY_CAP = 40
PROPOSAL_HISTORY_CAP = 12


def make_policy(spec):
    """Resolve a policy name, policy object, or falsy value into a policy (or None)."""
    if spec is None or spec is False:
        return None
    if hasattr(spec, "propose"):
        return spec
    name = str(spec).strip().lower()
    if name in ("", "0", "off", "false", "none", "exhaustive"):
        return None
    if name == "heuristic":
        return HeuristicPolicy()
    if name == "jev":
        return JevPolicy()
    if name in ("jev-bands", "jev_bands"):
        return JevBandPolicy()
    raise ValueError(f"Unknown guided search policy {spec!r} (use 'jev', 'jev-bands' or 'heuristic')")


def options_from_env(env=None):
    env = os.environ if env is None else env

    def number(name, default, cast):
        raw = env.get(name, "").strip()
        if not raw:
            return default
        try:
            return cast(raw)
        except ValueError:
            return default

    return {
        "bands": max(1, number("MXN_ALIGNMENT_GUIDED_BANDS", DEFAULT_BANDS, int)),
        "budget_fraction": min(1.0, max(0.01, number("MXN_ALIGNMENT_GUIDED_BUDGET", DEFAULT_BUDGET_FRACTION, float))),
        "max_rounds": max(1, number("MXN_ALIGNMENT_GUIDED_ROUNDS", DEFAULT_MAX_ROUNDS, int)),
        "stop_threshold": number("MXN_ALIGNMENT_GUIDED_STOP", DEFAULT_STOP_THRESHOLD, float),
        "patience": max(1, number("MXN_ALIGNMENT_GUIDED_PATIENCE", DEFAULT_PATIENCE, int)),
    }


def split_bands(values, bands):
    """Split an ascending grid into up to `bands` contiguous, near-equal bands."""
    count = max(1, min(bands, len(values)))
    out = []
    for b in range(count):
        lo = (b * len(values)) // count
        hi = ((b + 1) * len(values)) // count
        if hi > lo:
            out.append(list(values[lo:hi]))
    return out


def band_label(band):
    return f"ext_{int(band[0])}_to_{int(band[-1])}"


class SearchSpace:
    """The cell grid over one group's pair-extension combos."""

    def __init__(self, ext_range_values, num_pairs, bands=DEFAULT_BANDS, use_angle_thirds=True):
        self.values = list(ext_range_values)
        self.num_pairs = num_pairs
        self.radix = len(self.values)
        self.step_px = (self.values[1] - self.values[0]) if self.radix > 1 else 0
        self.bands = split_bands(self.values, bands)
        self.band_labels = [band_label(b) for b in self.bands]
        self.band_offsets = []
        offset = 0
        for band in self.bands:
            self.band_offsets.append(offset)
            offset += len(band)
        self.angle_thirds = list(ANGLE_THIRDS) if use_angle_thirds else [("full", (0.0, 1.0))]
        self.angle_fraction = dict(self.angle_thirds)
        self.cells = [
            (band_tuple, angle_label)
            for band_tuple in itertools.product(range(len(self.bands)), repeat=num_pairs)
            for angle_label, _ in self.angle_thirds
        ]
        self.total_combos = self.radix ** num_pairs

    def band_range(self, b):
        return (self.bands[b][0], self.bands[b][-1])

    def band_of(self, extension):
        for b, band in enumerate(self.bands):
            if band[0] <= extension <= band[-1]:
                return b
        return 0 if extension < self.bands[0][0] else len(self.bands) - 1

    def value_index(self, extension):
        return min(range(self.radix), key=lambda i: abs(self.values[i] - extension))

    def _encode(self, value_index_ranges):
        out = []
        for value_indices in itertools.product(*value_index_ranges):
            index = 0
            for i in value_indices:
                index = index * self.radix + i
            out.append(index)
        return out

    def cell_combo_indices(self, band_tuple):
        """Combo indices in a cell, encoded like `_decode_combo_index` (pair 0 most significant)."""
        return self._encode([
            range(self.band_offsets[b], self.band_offsets[b] + len(self.bands[b]))
            for b in band_tuple
        ])

    def neighbourhood_combo_indices(self, centre_extensions, half_width=DEFAULT_NEIGHBOURHOOD):
        """Combo indices within `half_width` grid steps of a centre extension per pair."""
        ranges = []
        for extension in centre_extensions:
            centre = self.value_index(extension)
            ranges.append(range(max(0, centre - half_width), min(self.radix, centre + half_width + 1)))
        return self._encode(ranges)

    def clamp(self, extension):
        return min(self.values[-1], max(self.values[0], extension))


def _unit(dx, dy):
    length = math.hypot(dx, dy)
    return (dx / length, dy / length) if length > 1e-9 else (0.0, 0.0)


def build_geometry(strands_list, pairs, min_gap, max_gap):
    """Describe the group's strands, opposite pairs and gap rule for a policy."""
    index_of = {id(strand): i for i, strand in enumerate(strands_list)}
    pair_of = {}
    for p, (left, right) in enumerate(pairs):
        pair_of[index_of[id(left)]] = p
        if right is not None:
            pair_of[index_of[id(right)]] = p
    strands = []
    for i, strand in enumerate(strands_list):
        s23 = strand["strand_2_3"]
        ux, uy = _unit(s23["end"]["x"] - s23["start"]["x"], s23["end"]["y"] - s23["start"]["y"])
        start, target = strand["original_start"], strand["target_position"]
        strands.append({
            "name": strand["strand_4_5"]["layer_name"],
            "order": i,
            "pair": pair_of.get(i),
            "start_px": [round(start["x"], 1), round(start["y"], 1)],
            "target_px": [round(target["x"], 1), round(target["y"], 1)],
            "extension_direction": [round(ux, 3), round(uy, 3)],
            "reach_px": round(math.hypot(target["x"] - start["x"], target["y"] - start["y"]), 1),
        })
    count = len(strands_list)
    pair_desc = []
    for p, (left, right) in enumerate(pairs):
        members = [index_of[id(left)]] + ([index_of[id(right)]] if right is not None else [])
        gaps = sorted({g for i in members for g in (i - 1, i) if 0 <= g < count - 1})
        if right is None:
            position = "the middle strand, on its own"
        elif p == 0:
            position = "the outermost two strands"
        else:
            position = f"{p} in from the outside"
        pair_desc.append({
            "index": p,
            "strands": [strands[i]["name"] for i in members],
            "position": position,
            "gaps_touched": gaps,
        })
    return {
        "strand_order": [s["name"] for s in strands],
        "strands": strands,
        "pairs": pair_desc,
        "gap_rule": {
            "min_px": min_gap,
            "max_px": max_gap,
            "note": (
                "gap i is the perpendicular distance between strand_order[i] and strand_order[i+1] "
                "after alignment; every gap must be inside [min_px, max_px] and all on the same side. "
                "Extending a pair slides both of its strands' start points along extension_direction "
                "before the angle sweep, which mostly changes the gaps that pair touches."
            ),
        },
    }


def describe_gaps(gaps, order, min_gap, max_gap):
    out = []
    for i, gap in enumerate(gaps or []):
        gap = abs(float(gap))
        if min_gap is not None and gap < min_gap:
            status = "too_tight"
        elif max_gap is not None and gap > max_gap:
            status = "too_wide"
        else:
            status = "ok"
        between = [order[i], order[i + 1]] if order and i + 1 < len(order) else [i, i + 1]
        out.append({"gap": i, "between": between, "px": round(gap, 1), "status": status})
    return out


def _normalize(weights):
    total = sum(max(0.0, w) for w in weights.values())
    if total <= 0:
        return {k: 1.0 / len(weights) for k in weights} if weights else {}
    return {k: max(0.0, w) / total for k, w in weights.items()}


def _argmax(probabilities, default=None):
    return max(probabilities, key=probabilities.get) if probabilities else default


def rank_cells(space, proposal, explored):
    """Highest joint-probability unexplored cell; ties go to shorter arms, then the middle third."""
    pair_probs = proposal.get("pair_bands") or []
    angle_probs = proposal.get("angle") or {}
    best, best_key = None, None
    for cell in space.cells:
        if cell in explored:
            continue
        bands, angle = cell
        score = 1.0
        for p, b in enumerate(bands):
            probs = pair_probs[p] if p < len(pair_probs) else {}
            score *= max(float(probs.get(space.band_labels[b], 0.0)), 1e-9)
        score *= max(float(angle_probs.get(angle, 0.0)), 1e-9)
        key = (-score, sum(bands), _ANGLE_TIE_ORDER.get(angle, 9))
        if best_key is None or key < best_key:
            best, best_key = cell, key
    return best


def build_state(space, problem, geometry, explored, history, proposals, best_valid, closest,
                combos_evaluated, budget, round_no, rounds_since_improvement):
    remaining_pair = [{label: 0 for label in space.band_labels} for _ in range(space.num_pairs)]
    remaining_angle = {label: 0 for label, _ in space.angle_thirds}
    for cell in space.cells:
        if cell in explored:
            continue
        bands, angle = cell
        for p, b in enumerate(bands):
            remaining_pair[p][space.band_labels[b]] += 1
        remaining_angle[angle] += 1
    return {
        "problem": problem,
        "geometry": geometry,
        "search": {
            "round": round_no,
            "cells_total": len(space.cells),
            "cells_explored": len(explored),
            "combos_total": space.total_combos,
            "combos_evaluated": combos_evaluated,
            "combo_budget": budget,
            "grid_step_px": space.step_px,
            "rounds_since_improvement": rounds_since_improvement,
            "found_valid": best_valid is not None,
        },
        "extension_bands": [
            {"label": label, "extension_px": list(space.band_range(b))}
            for b, label in enumerate(space.band_labels)
        ],
        "angle_thirds": [label for label, _ in space.angle_thirds],
        "remaining_cells": {"per_pair_band": remaining_pair, "per_angle_third": remaining_angle},
        "best_valid": best_valid,
        "closest_invalid": closest,
        "explored_cells": history[-HISTORY_CAP:],
        "proposal_history": proposals[-PROPOSAL_HISTORY_CAP:],
    }


class HeuristicPolicy:
    """Deterministic stand-in for a decision model: explore rounds only."""

    name = "heuristic"

    def propose(self, state, space):
        anchor = state.get("best_valid") or state.get("closest_invalid")
        remaining = state["remaining_cells"]["per_pair_band"]
        pair_bands = []
        for p in range(space.num_pairs):
            weights = {}
            centre = space.band_of(anchor["pair_extensions"][p]) if anchor else None
            for b, label in enumerate(space.band_labels):
                if centre is None:
                    weight = 1.0 / (1 + b)
                else:
                    weight = {0: 0.5, 1: 0.2}.get(abs(b - centre), 0.05)
                if remaining[p].get(label, 0) == 0:
                    weight = 0.0
                weights[label] = weight
            pair_bands.append(_normalize(weights))
        angle = {}
        for label, _ in space.angle_thirds:
            if anchor and anchor.get("angle_third") in space.angle_fraction:
                angle[label] = 0.6 if label == anchor["angle_third"] else 0.2
            else:
                angle[label] = 0.5 if label in ("middle", "full") else 0.25
        stop = None
        if state.get("best_valid"):
            stop = 0.9 if state["search"]["rounds_since_improvement"] >= 2 else 0.1
        return {"kind": "explore", "pair_bands": pair_bands, "angle": _normalize(angle), "stop": stop}


class _JevClientMixin:
    def __init__(self, client=None, model=None, timeout=30.0):
        if client is None:
            from typesafe_sdk import TypeSafeClient
            client = TypeSafeClient(model=model, timeout=timeout)
        self.client = client
        self.calls = 0
        self.input_tokens = 0

    def _ask(self, state, questions):
        response = self.client.system_one(state=state, questions=questions)
        self.calls += 1
        usage = getattr(response, "usage", None)
        if usage is not None and getattr(usage, "input_tokens", None):
            self.input_tokens += usage.input_tokens
        return response

    def _band_questions(self, state, space):
        remaining = state["remaining_cells"]["per_pair_band"]
        pairs_desc = {p["index"]: p for p in (state.get("geometry") or {}).get("pairs", [])}
        questions = {}
        for p in range(space.num_pairs):
            criteria = {}
            for b, label in enumerate(space.band_labels):
                lo, hi = space.band_range(b)
                criteria[label] = (
                    f"Extend both strands of pair {p} by {lo:g} to {hi:g} px; "
                    f"{remaining[p][label]} unexplored cells remain in this band."
                )
            pd = pairs_desc.get(p, {})
            questions[f"pair_{p}_band"] = {
                "type": "choice",
                "instructions": {
                    "question": f"Which extension band should an exploring round evaluate next for opposite pair {p}?",
                    "pair": {
                        "strands": pd.get("strands"),
                        "position": pd.get("position"),
                        "gaps_touched": pd.get("gaps_touched"),
                    },
                    "context": (
                        "Opposite pairs are numbered outside-in from 0. Extending a pair slides both strands' "
                        "start points along their extension_direction by the same amount before the angle "
                        "sweep. A cell is one band per pair plus one third of the angle window; every combo "
                        "in the chosen cell is evaluated exactly."
                    ),
                    "goal": (
                        "Find a valid parallel alignment with as few evaluated combos as possible. Valid means "
                        "every gap is inside geometry.gap_rule and all gaps lie on the same side. Bands whose "
                        "explored_cells produced valid results, or the largest closest_worst_gap_px, are the "
                        "most promising; a band with 0 remaining cells is exhausted. Prefer the shorter "
                        "extension when bands look equally promising."
                    ),
                },
                "criteria": criteria,
            }
        questions["angle_third"] = {
            "type": "choice",
            "instructions": {
                "question": "Which third of the angle window should the next round evaluate?",
                "context": (
                    "Each combo's angle window is recomputed from the first strand's direction "
                    "(problem.angle_window_deg is the window at zero extension). low is the first third "
                    "of that window, middle the central third, high the last third. explored_cells, "
                    "best_valid and closest_invalid record which third produced them."
                ),
                "goal": "Pick the third most likely to contain a valid alignment for the next round.",
            },
            "criteria": {
                label: f"The {label} third of each combo's angle window; {state['remaining_cells']['per_angle_third'][label]} unexplored cells remain."
                for label, _ in space.angle_thirds
            },
        }
        return questions


class JevBandPolicy(_JevClientMixin):
    """The first Jev policy: band per pair, angle third, and a stop Noul."""

    name = "jev-bands"

    def questions(self, state, space):
        questions = self._band_questions(state, space)
        if state.get("best_valid"):
            questions["stop"] = {
                "type": "noul",
                "instructions": {
                    "statement": "Searching the remaining unexplored cells is unlikely to find a valid alignment better than best_valid.",
                    "better_means": "smaller first_last_px; if equal, lower gap_variance; if equal, shorter total_extension_px",
                    "context": (
                        "search.rounds_since_improvement counts rounds since best_valid last improved; "
                        "search.combos_evaluated of search.combo_budget is spent."
                    ),
                },
                "criteria": {
                    "true": "Stop searching and keep best_valid.",
                    "false": "Keep searching; a better valid alignment is plausible.",
                },
            }
        return questions

    def propose(self, state, space):
        response = self._ask(state, self.questions(state, space))
        choices = response.choices
        pair_bands = [dict(choices[f"pair_{p}_band"].probabilities) for p in range(space.num_pairs)]
        angle = dict(choices["angle_third"].probabilities)
        stop = response.nouls["stop"].noul if "stop" in response.nouls else None
        return {"kind": "explore", "pair_bands": pair_bands, "angle": angle, "stop": stop}


class JevPolicy(_JevClientMixin):
    """
    Jev as the loop's strategist: it sees the group's geometry and the gaps at
    the best or closest configuration, and each round chooses a strategy
    (refine / explore / stop), a move per pair, a step size and the angle third.
    """

    name = "jev"
    STEP_LEVELS = (1, 3, 5)
    MOVE_DIRECTION = {"shorter": -1, "keep": 0, "longer": 1}

    def questions(self, state, space):
        questions = self._band_questions(state, space)
        anchor = state.get("best_valid") or state.get("closest_invalid")
        if anchor is None:
            return questions

        anchor_name = "best_valid" if state.get("best_valid") else "closest_invalid"
        pairs_desc = {p["index"]: p for p in (state.get("geometry") or {}).get("pairs", [])}
        step = state["search"].get("grid_step_px") or 10
        gap_text = [
            f"gap {g['gap']} between {g['between'][0]} and {g['between'][1]}: {g['px']} px, {g['status']}"
            for g in anchor.get("gaps", [])
        ]

        strategies = {
            "refine": (
                f"Move a small step away from {anchor_name} as the move_pair answers say and evaluate the "
                f"neighbourhood (one grid step around each pair). Best when {anchor_name} is nearly valid or "
                "valid and a nearby change should fix or improve the gaps."
            ),
            "explore": (
                "Leave the anchor and evaluate the most promising unexplored band cell (pair_*_band and "
                "angle_third answers). Best when recent refine rounds stopped improving or the anchor's "
                "gaps are far outside the rule."
            ),
        }
        if state.get("best_valid"):
            strategies["stop"] = (
                "Stop now and keep best_valid: the remaining budget is unlikely to find a valid alignment "
                "with a smaller first_last_px (then lower gap_variance, then shorter total extension)."
            )
        questions["strategy"] = {
            "type": "choice",
            "instructions": {
                "question": "What should the next search round do?",
                "anchor": anchor_name,
                "anchor_gaps": gap_text,
                "context": (
                    "proposal_history lists earlier rounds with what they proposed and what came of it; "
                    "search.rounds_since_improvement counts rounds since best_valid last improved; "
                    "search.combos_evaluated of search.combo_budget is spent."
                ),
            },
            "criteria": strategies,
        }
        for p in range(space.num_pairs):
            pd = pairs_desc.get(p, {})
            questions[f"move_pair_{p}"] = {
                "type": "choice",
                "instructions": {
                    "question": (
                        f"If the next round refines around {anchor_name}, should opposite pair {p} be "
                        "extended less, kept, or extended more?"
                    ),
                    "pair": {
                        "strands": pd.get("strands"),
                        "position": pd.get("position"),
                        "gaps_touched": pd.get("gaps_touched"),
                        "anchor_extension_px": anchor["pair_extensions"][p],
                        "grid_px": [space.values[0], space.values[-1]],
                    },
                    "anchor_gaps": gap_text,
                    "context": (
                        "Extending a pair slides its strands' start points along their extension_direction "
                        "(see geometry.strands), which mostly changes the gaps in gaps_touched. A too_tight "
                        "gap needs the two strands further apart; a too_wide gap needs them closer."
                    ),
                },
                "criteria": {
                    "shorter": f"Reduce pair {p}'s extension.",
                    "keep": f"Leave pair {p}'s extension as in {anchor_name}.",
                    "longer": f"Increase pair {p}'s extension.",
                },
            }
            questions[f"step_pair_{p}"] = {
                "type": "score",
                "instructions": {
                    "question": f"If pair {p} moves, how far should it move?",
                    "anchor_gaps": gap_text,
                },
                "criteria": [
                    f"one grid step ({step:g} px): fine adjustment when the gaps are nearly right",
                    f"three grid steps ({3 * step:g} px): the gaps are off by a moderate amount",
                    f"five grid steps ({5 * step:g} px): a large correction, the gaps are far outside the rule",
                ],
            }
        return questions

    def propose(self, state, space):
        response = self._ask(state, self.questions(state, space))
        choices = response.choices
        scores = getattr(response, "scores", {}) or {}
        pair_bands = [dict(choices[f"pair_{p}_band"].probabilities) for p in range(space.num_pairs)]
        angle = dict(choices["angle_third"].probabilities)
        proposal = {"pair_bands": pair_bands, "angle": angle, "angle_third": _argmax(angle)}
        if "strategy" not in choices:
            proposal["kind"] = "start"
            return proposal

        strategy = choices["strategy"]
        proposal["strategy_probs"] = dict(strategy.probabilities)
        proposal["stop"] = strategy.probabilities.get("stop")
        proposal["kind"] = {"refine": "move", "explore": "explore", "stop": "stop"}.get(strategy.choice, "explore")
        moves = []
        for p in range(space.num_pairs):
            move = choices[f"move_pair_{p}"]
            score = scores.get(f"step_pair_{p}")
            level = int(round(score.score)) if score is not None else 0
            moves.append({
                "direction": self.MOVE_DIRECTION.get(move.choice, 0),
                "steps": self.STEP_LEVELS[max(0, min(len(self.STEP_LEVELS) - 1, level))],
                "choice": move.choice,
                "probabilities": dict(move.probabilities),
            })
        proposal["moves"] = moves
        return proposal


def _valid_key(result):
    return (
        round(result.get("first_last_distance", math.inf), 3),
        round(result.get("gap_variance", math.inf), 6),
        sum(result.get("pair_extensions", ())),
    )


def _describe_valid(result, labels, angle_label, order, min_gap, max_gap):
    return {
        "pair_extensions": [float(e) for e in result.get("pair_extensions", ())],
        "pair_bands": labels,
        "angle_third": angle_label,
        "angle_deg": round(float(result.get("angle_degrees", 0.0)), 2),
        "first_last_px": round(float(result.get("first_last_distance", math.inf)), 2),
        "gap_variance": round(float(result.get("gap_variance", math.inf)), 4),
        "total_extension_px": float(sum(result.get("pair_extensions", ()))),
        "gaps": describe_gaps(result.get("gaps"), order, min_gap, max_gap),
    }


def _describe_move(moves):
    if not moves:
        return "-"
    words = {-1: "shorter", 0: "keep", 1: "longer"}
    return ", ".join(
        f"p{p} {words.get(m.get('direction', 0), '?')}" + (f"x{m.get('steps', 1)}" if m.get("direction") else "")
        for p, m in enumerate(moves)
    )


def guided_combo_search(evaluate_cell, ext_range_values, num_pairs, policy, problem=None, geometry=None,
                        bands=DEFAULT_BANDS, use_angle_thirds=True,
                        budget_fraction=DEFAULT_BUDGET_FRACTION, max_rounds=DEFAULT_MAX_ROUNDS,
                        stop_threshold=DEFAULT_STOP_THRESHOLD, patience=DEFAULT_PATIENCE,
                        neighbourhood=DEFAULT_NEIGHBOURHOOD, log=None):
    """
    Let `policy` steer which combos `evaluate_cell(combo_indices, angle_fraction)`
    evaluates. Returns the valid results found (sorted by combo index), the best
    fallback seen, and an `info` dict describing the run. Finding nothing is a
    normal outcome; the caller then runs the exhaustive search.
    """
    space = SearchSpace(ext_range_values, num_pairs, bands=bands, use_angle_thirds=use_angle_thirds)
    budget = max(1, int(math.ceil(space.total_combos * budget_fraction)))
    log = log or (lambda line: None)
    problem = problem or {}
    geometry = geometry or {}
    order = geometry.get("strand_order")
    gap_rule = geometry.get("gap_rule") or {}
    min_gap = gap_rule.get("min_px", (problem.get("valid_gap_px") or [None, None])[0])
    max_gap = gap_rule.get("max_px", (problem.get("valid_gap_px") or [None, None])[1])

    explored = {}
    evaluated = set()
    history = []
    proposals = []
    valid_results = []
    best_valid = None
    best_key = None
    rounds_since_improvement = 0
    best_fallback = None
    best_fallback_worst_gap = -math.inf
    best_fallback_extensions = tuple(0 for _ in range(num_pairs))
    best_fallback_angle = 0.0
    closest = None
    combos_evaluated = 0
    stopped = None
    rounds = 0
    kinds = {"start": 0, "explore": 0, "move": 0}

    for round_no in range(1, max_rounds + 1):
        if combos_evaluated >= budget:
            stopped = "budget"
            break
        if best_valid is not None and rounds_since_improvement >= patience:
            stopped = "patience"
            break

        state = build_state(space, problem, geometry, explored, history, proposals, best_valid, closest,
                            combos_evaluated, budget, round_no, rounds_since_improvement)
        try:
            proposal = policy.propose(state, space)
        except Exception as error:
            log(f"policy error: {error}")
            stopped = "policy_error"
            break

        kind = proposal.get("kind") or "explore"
        stop = proposal.get("stop")
        if best_valid is not None and (kind == "stop" or (stop is not None and stop >= stop_threshold)):
            stopped = "policy_stop"
            break

        anchor = best_valid or closest
        indices = None
        cell = None
        centre = None
        angle_label = None
        if kind == "move" and anchor is not None:
            moves = proposal.get("moves") or []
            centre = []
            for p in range(num_pairs):
                move = moves[p] if p < len(moves) else {}
                delta = int(move.get("direction", 0)) * max(1, int(move.get("steps", 1))) * space.step_px
                centre.append(space.clamp(anchor["pair_extensions"][p] + delta))
            angle_label = proposal.get("angle_third") or anchor.get("angle_third") or space.angle_thirds[0][0]
            if angle_label not in space.angle_fraction:
                angle_label = space.angle_thirds[0][0]
            candidate = [i for i in space.neighbourhood_combo_indices(centre, neighbourhood)
                         if (i, angle_label) not in evaluated]
            if candidate:
                indices = candidate
            else:
                kind = "explore"
        if indices is None:
            while True:
                cell = rank_cells(space, proposal, explored)
                if cell is None:
                    break
                band_tuple, angle_label = cell
                candidate = [i for i in space.cell_combo_indices(band_tuple) if (i, angle_label) not in evaluated]
                if candidate:
                    indices = candidate
                    break
                explored[cell] = {"pair_bands": [space.band_labels[b] for b in band_tuple],
                                  "angle_third": angle_label, "combos": 0, "valid": 0, "covered_by_moves": True}
            if indices is None:
                stopped = "exhausted"
                break
            kind = "start" if anchor is None else "explore"
            centre = None

        chunk = evaluate_cell(indices, space.angle_fraction[angle_label])
        evaluated.update((i, angle_label) for i in indices)
        rounds = round_no
        kinds[kind] = kinds.get(kind, 0) + 1

        combos_evaluated += chunk.get("combos_evaluated", len(indices))
        cell_valid = chunk.get("valid_results", [])
        valid_results.extend(cell_valid)
        labels = ([space.band_labels[b] for b in cell[0]] if cell is not None
                  else [space.band_labels[space.band_of(e)] for e in centre])

        improved = False
        for result in cell_valid:
            key = _valid_key(result)
            if best_key is None or key < best_key:
                best_key = key
                best_valid = _describe_valid(result, labels, angle_label, order, min_gap, max_gap)
                improved = True
        if best_valid is not None:
            rounds_since_improvement = 0 if improved else rounds_since_improvement + 1

        fallback = chunk.get("best_fallback")
        fallback_gap = chunk.get("best_fallback_worst_gap", -math.inf)
        if fallback is not None and fallback_gap > best_fallback_worst_gap:
            best_fallback = fallback
            best_fallback_worst_gap = fallback_gap
            best_fallback_extensions = chunk.get("best_fallback_extensions", best_fallback_extensions)
            best_fallback_angle = chunk.get("best_fallback_angle", 0.0)
            closest = {
                "pair_extensions": [float(e) for e in best_fallback_extensions],
                "pair_bands": labels,
                "angle_third": angle_label,
                "angle_deg": round(float(best_fallback_angle), 2),
                "worst_gap_px": round(float(fallback_gap), 2),
                "gaps_px": [round(float(g), 1) for g in fallback.get("gaps", [])],
                "gaps": describe_gaps(fallback.get("gaps"), order, min_gap, max_gap),
            }

        record = {
            "round": round_no,
            "kind": kind,
            "pair_bands": labels,
            "angle_third": angle_label,
            "centre_px": centre,
            "combos": len(indices),
            "valid": len(cell_valid),
            "improved_best_valid": improved,
            "best_first_last_px": round(min(r.get("first_last_distance", math.inf) for r in cell_valid), 2) if cell_valid else None,
            "best_gap_variance": round(min(r.get("gap_variance", math.inf) for r in cell_valid), 4) if cell_valid else None,
            "best_total_extension_px": float(min(sum(r.get("pair_extensions", ())) for r in cell_valid)) if cell_valid else None,
            "closest_worst_gap_px": round(float(fallback_gap), 2) if fallback is not None else None,
            "closest_pair_extensions": [float(e) for e in chunk.get("best_fallback_extensions", ())] if fallback is not None else None,
        }
        if cell is not None:
            explored[cell] = record
        history.append(record)
        proposals.append({
            "round": round_no,
            "kind": kind,
            "moves": [{"direction": m.get("direction", 0), "steps": m.get("steps", 1)} for m in (proposal.get("moves") or [])] if kind == "move" else None,
            "angle_third": angle_label,
            "outcome": {
                "combos": len(indices),
                "valid": len(cell_valid),
                "improved_best_valid": improved,
                "closest_worst_gap_px": record["closest_worst_gap_px"],
            },
        })
        where = (f"bands={tuple(space.band_of(e) for e in centre)} centre={tuple(int(e) for e in centre)} move: {_describe_move(proposal.get('moves'))}"
                 if kind == "move" else f"bands={tuple(cell[0])}")
        best_note = f", best dist {record['best_first_last_px']}px" if cell_valid else ""
        log(f"round {round_no} [{kind}]: {where} angle={angle_label} -> {len(indices)} combos, "
            f"{len(cell_valid)} valid{best_note} | {combos_evaluated}/{space.total_combos} combos evaluated")

    if stopped is None:
        stopped = "rounds"

    valid_results.sort(key=lambda result: result.get("combo_index", -1))
    info = {
        "policy": policy.name,
        "rounds": rounds,
        "rounds_by_kind": kinds,
        "cells_explored": len(explored),
        "cells_total": len(space.cells),
        "combos_evaluated": combos_evaluated,
        "combos_total": space.total_combos,
        "combo_budget": budget,
        "stopped": stopped,
        "valid_found": len(valid_results),
    }
    for attribute in ("calls", "input_tokens"):
        if hasattr(policy, attribute):
            info[f"policy_{attribute}"] = getattr(policy, attribute)
    log(f"done: {stopped}, {len(valid_results)} valid in {combos_evaluated}/{space.total_combos} combos over {rounds} rounds")

    return {
        "valid_results": valid_results,
        "best_fallback": best_fallback,
        "best_fallback_worst_gap": best_fallback_worst_gap,
        "best_fallback_extensions": best_fallback_extensions,
        "best_fallback_angle": best_fallback_angle,
        "combos_evaluated": combos_evaluated,
        "rounds": rounds,
        "stopped": stopped,
        "cells": history,
        "proposals": proposals,
        "info": info,
    }
