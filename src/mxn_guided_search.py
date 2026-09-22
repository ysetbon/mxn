"""
Policy-guided search over the pair-extension x angle grid.

The exhaustive aligner evaluates every pair-extension combo against every
angle. Here a decision policy picks which region ("cell") of that grid to
evaluate next, the cell is evaluated with the exact same validity math, and
what it produced feeds the next decision. A cell is one extension band per
opposite pair plus one third of each combo's angle window.

Policies:
  * JevPolicy       asks TypeSafe's System One model (Jev) where to look next.
  * HeuristicPolicy deterministic stand-in: probe around the closest result
                    so far, shortest arms first. Also the offline baseline.

Enable from the environment with MXN_ALIGNMENT_GUIDED=jev|heuristic, or pass
`guided_search=` to the align functions.
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
MIN_COMBOS_FOR_GUIDED = 64
HISTORY_CAP = 40


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
    raise ValueError(f"Unknown guided search policy {spec!r} (use 'jev' or 'heuristic')")


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

    def cell_combo_indices(self, band_tuple):
        """Combo indices in a cell, encoded like `_decode_combo_index` (pair 0 most significant)."""
        ranges = [
            range(self.band_offsets[b], self.band_offsets[b] + len(self.bands[b]))
            for b in band_tuple
        ]
        out = []
        for value_indices in itertools.product(*ranges):
            index = 0
            for i in value_indices:
                index = index * self.radix + i
            out.append(index)
        return out


def _normalize(weights):
    total = sum(max(0.0, w) for w in weights.values())
    if total <= 0:
        return {k: 1.0 / len(weights) for k in weights} if weights else {}
    return {k: max(0.0, w) / total for k, w in weights.items()}


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


def build_state(space, problem, explored, history, best_valid, closest,
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
        "search": {
            "round": round_no,
            "cells_total": len(space.cells),
            "cells_explored": len(explored),
            "combos_total": space.total_combos,
            "combos_evaluated": combos_evaluated,
            "combo_budget": budget,
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
    }


class HeuristicPolicy:
    """Deterministic stand-in for a decision model."""

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
        return {"pair_bands": pair_bands, "angle": _normalize(angle), "stop": stop}


class JevPolicy:
    """Asks a TypeSafe System One model (Jev) where to search next."""

    name = "jev"

    def __init__(self, client=None, model=None, timeout=30.0):
        if client is None:
            from typesafe_sdk import TypeSafeClient
            client = TypeSafeClient(model=model, timeout=timeout)
        self.client = client
        self.calls = 0
        self.input_tokens = 0

    def questions(self, state, space):
        remaining = state["remaining_cells"]["per_pair_band"]
        questions = {}
        for p in range(space.num_pairs):
            criteria = {}
            for b, label in enumerate(space.band_labels):
                lo, hi = space.band_range(b)
                criteria[label] = (
                    f"Extend both strands of pair {p} by {lo:g} to {hi:g} px; "
                    f"{remaining[p][label]} unexplored cells remain in this band."
                )
            questions[f"pair_{p}_band"] = {
                "type": "choice",
                "instructions": {
                    "question": f"Which extension band should the alignment search evaluate next for opposite pair {p}?",
                    "context": (
                        "Opposite pairs are numbered outside-in from 0 (the outermost two strands). "
                        "Extending a pair slides both strands' start points along their _2/_3 direction "
                        "by the same amount before the angle sweep. A cell is one band per pair plus one "
                        "third of the angle window; every combo in the chosen cell is evaluated exactly."
                    ),
                    "goal": (
                        "Find a valid parallel alignment with as few evaluated combos as possible. Valid means "
                        "every gap between consecutive strands is within problem.valid_gap_px and all gaps lie "
                        "on the same side. Bands whose explored_cells produced valid results, or the largest "
                        "closest_worst_gap_px, are the most promising; a band with 0 remaining cells is "
                        "exhausted. Prefer the shorter extension when bands look equally promising."
                    ),
                },
                "criteria": criteria,
            }
        questions["angle_third"] = {
            "type": "choice",
            "instructions": {
                "question": "Which third of the angle window should the search evaluate next?",
                "context": (
                    "Each combo's angle window is recomputed from the first strand's direction "
                    "(problem.angle_window_deg is the window at zero extension). low is the first third "
                    "of that window, middle the central third, high the last third. explored_cells, "
                    "best_valid and closest_invalid record which third produced them."
                ),
                "goal": "Pick the third most likely to contain a valid alignment for the next cell.",
            },
            "criteria": {
                label: f"The {label} third of each combo's angle window; {state['remaining_cells']['per_angle_third'][label]} unexplored cells remain."
                for label, _ in space.angle_thirds
            },
        }
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
        response = self.client.system_one(state=state, questions=self.questions(state, space))
        self.calls += 1
        usage = getattr(response, "usage", None)
        if usage is not None and getattr(usage, "input_tokens", None):
            self.input_tokens += usage.input_tokens
        choices = response.choices
        pair_bands = [dict(choices[f"pair_{p}_band"].probabilities) for p in range(space.num_pairs)]
        angle = dict(choices["angle_third"].probabilities)
        stop = response.nouls["stop"].noul if "stop" in response.nouls else None
        return {"pair_bands": pair_bands, "angle": angle, "stop": stop}


def _valid_key(result):
    return (
        round(result.get("first_last_distance", math.inf), 3),
        round(result.get("gap_variance", math.inf), 6),
        sum(result.get("pair_extensions", ())),
    )


def _describe_valid(result, labels, angle_label):
    return {
        "pair_extensions": [float(e) for e in result.get("pair_extensions", ())],
        "pair_bands": labels,
        "angle_third": angle_label,
        "angle_deg": round(float(result.get("angle_degrees", 0.0)), 2),
        "first_last_px": round(float(result.get("first_last_distance", math.inf)), 2),
        "gap_variance": round(float(result.get("gap_variance", math.inf)), 4),
        "total_extension_px": float(sum(result.get("pair_extensions", ()))),
    }


def guided_combo_search(evaluate_cell, ext_range_values, num_pairs, policy, problem=None,
                        bands=DEFAULT_BANDS, use_angle_thirds=True,
                        budget_fraction=DEFAULT_BUDGET_FRACTION, max_rounds=DEFAULT_MAX_ROUNDS,
                        stop_threshold=DEFAULT_STOP_THRESHOLD, patience=DEFAULT_PATIENCE, log=None):
    """
    Let `policy` steer which cells `evaluate_cell(combo_indices, angle_fraction)`
    evaluates. Returns the valid results found (sorted by combo index), the best
    fallback seen, and an `info` dict describing the run. Finding nothing is a
    normal outcome; the caller then runs the exhaustive search.
    """
    space = SearchSpace(ext_range_values, num_pairs, bands=bands, use_angle_thirds=use_angle_thirds)
    budget = max(1, int(math.ceil(space.total_combos * budget_fraction)))
    log = log or (lambda line: None)

    explored = {}
    history = []
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

    for round_no in range(1, max_rounds + 1):
        if len(explored) >= len(space.cells):
            stopped = "exhausted"
            break
        if combos_evaluated >= budget:
            stopped = "budget"
            break
        if best_valid is not None and rounds_since_improvement >= patience:
            stopped = "patience"
            break

        state = build_state(space, problem or {}, explored, history, best_valid, closest,
                            combos_evaluated, budget, round_no, rounds_since_improvement)
        try:
            proposal = policy.propose(state, space)
        except Exception as error:
            log(f"policy error: {error}")
            stopped = "policy_error"
            break

        if best_valid is not None:
            stop = proposal.get("stop")
            if stop is not None and stop >= stop_threshold:
                stopped = "policy_stop"
                break

        cell = rank_cells(space, proposal, explored)
        if cell is None:
            stopped = "exhausted"
            break
        band_tuple, angle_label = cell
        labels = [space.band_labels[b] for b in band_tuple]
        indices = space.cell_combo_indices(band_tuple)
        chunk = evaluate_cell(indices, space.angle_fraction[angle_label])
        rounds = round_no

        combos_evaluated += chunk.get("combos_evaluated", len(indices))
        cell_valid = chunk.get("valid_results", [])
        valid_results.extend(cell_valid)

        improved = False
        for result in cell_valid:
            key = _valid_key(result)
            if best_key is None or key < best_key:
                best_key = key
                best_valid = _describe_valid(result, labels, angle_label)
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
            }

        record = {
            "pair_bands": labels,
            "angle_third": angle_label,
            "combos": len(indices),
            "valid": len(cell_valid),
            "best_first_last_px": round(min(r.get("first_last_distance", math.inf) for r in cell_valid), 2) if cell_valid else None,
            "best_gap_variance": round(min(r.get("gap_variance", math.inf) for r in cell_valid), 4) if cell_valid else None,
            "best_total_extension_px": float(min(sum(r.get("pair_extensions", ())) for r in cell_valid)) if cell_valid else None,
            "closest_worst_gap_px": round(float(fallback_gap), 2) if fallback is not None else None,
            "closest_pair_extensions": [float(e) for e in chunk.get("best_fallback_extensions", ())] if fallback is not None else None,
        }
        explored[cell] = record
        history.append(record)
        best_note = f", best dist {record['best_first_last_px']}px" if cell_valid else ""
        log(f"round {round_no}: bands={tuple(band_tuple)} angle={angle_label} -> {len(indices)} combos, "
            f"{len(cell_valid)} valid{best_note} | {combos_evaluated}/{space.total_combos} combos evaluated")

    if stopped is None:
        stopped = "rounds"

    valid_results.sort(key=lambda result: result.get("combo_index", -1))
    info = {
        "policy": policy.name,
        "rounds": rounds,
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
        "info": info,
    }
