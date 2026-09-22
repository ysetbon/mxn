"""Tests for the policy-guided pair-extension search."""

import contextlib
import io
import json
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))

import mxn_guided_search as G
import mxn_lh_continuation as LH
from ui_utils import _get_active_strands


VALUES = list(range(0, 210, 10))
TARGET = (80, 60)


def synthetic_evaluate(combo_indices, angle_fraction):
    """Stand-in for the chunk evaluator: exactly one valid combo, fallbacks that get better closer to it."""
    valid, best_gap, best_combo = [], -float("inf"), None
    for index in combo_indices:
        combo = LH._decode_combo_index(index, VALUES, len(TARGET))
        distance = sum(abs(a - b) for a, b in zip(combo, TARGET))
        if distance == 0:
            valid.append({
                "valid": True, "pair_extensions": combo, "combo_index": index,
                "first_last_distance": 1.0, "gap_variance": 0.1, "angle_degrees": 12.0,
                "configurations": [], "gaps": [60.0, 61.0],
            })
        elif 60.0 - distance / 10.0 > best_gap:
            best_gap, best_combo = 60.0 - distance / 10.0, combo
    return {
        "combos_evaluated": len(combo_indices), "valid_results": valid,
        "best_fallback": {"gaps": [best_gap, best_gap + 3], "average_gap": best_gap} if best_combo else None,
        "best_fallback_worst_gap": best_gap, "best_fallback_extensions": best_combo, "best_fallback_angle": 10.0,
    }


class _Choice:
    def __init__(self, probabilities):
        self.probabilities = probabilities
        self.choice = max(probabilities, key=probabilities.get)
        self.confidence = self.probabilities[self.choice]


class _Noul:
    def __init__(self, noul):
        self.noul = noul


class _Score:
    def __init__(self, score):
        self.score = score
        self.confidence = 0.8
        self.probabilities = {int(score): 1.0}
        self.legend = {}


class _Usage:
    input_tokens = 321
    output_tokens = 0


class _Response:
    def __init__(self, choices, nouls, scores):
        self.choices, self.nouls, self.scores, self.usage = choices, nouls, scores, _Usage()


class FakeJevClient:
    """Mimics TypeSafeClient.system_one with fixed preferences; records every request."""

    def __init__(self, prefer_band=1, prefer_angle="middle", stop=0.0,
                 strategy="refine", stop_when_valid=False, moves=None, step_levels=None):
        self.prefer_band, self.prefer_angle, self.stop = prefer_band, prefer_angle, stop
        self.strategy, self.stop_when_valid = strategy, stop_when_valid
        self.moves, self.step_levels = moves or {}, step_levels or {}
        self.requests = []

    def _favourite(self, name, labels, state):
        if name == "angle_third":
            return self.prefer_angle
        if name == "strategy":
            return "stop" if (self.stop_when_valid and state.get("best_valid")) else self.strategy
        if name.startswith("move_pair_"):
            return self.moves.get(int(name.rsplit("_", 1)[1]), "keep")
        return labels[min(self.prefer_band, len(labels) - 1)]

    def system_one(self, state, questions):
        json.dumps(state)
        json.dumps(questions)
        self.requests.append((state, questions))
        choices, scores = {}, {}
        for name, question in questions.items():
            if question["type"] == "choice":
                labels = list(question["criteria"])
                favourite = self._favourite(name, labels, state)
                if favourite not in labels:
                    favourite = labels[0]
                rest = 0.3 / max(len(labels) - 1, 1)
                choices[name] = _Choice({label: (0.7 if label == favourite else rest) for label in labels})
            elif question["type"] == "score":
                scores[name] = _Score(self.step_levels.get(int(name.rsplit("_", 1)[1]), 0))
        nouls = {"stop": _Noul(self.stop)} if "stop" in questions else {}
        return _Response(choices, nouls, scores)


class SearchSpaceTests(unittest.TestCase):
    def test_bands_partition_the_grid_in_order(self):
        space = G.SearchSpace(VALUES, 2, bands=4)
        flat = [v for band in space.bands for v in band]
        self.assertEqual(flat, VALUES)
        self.assertEqual(len(space.bands), 4)
        self.assertEqual(len(space.cells), 4 ** 2 * 3)
        self.assertEqual(space.band_of(80), space.band_of(60))
        self.assertEqual(space.band_of(0), 0)
        self.assertEqual(space.band_of(200), 3)
        self.assertEqual(space.step_px, 10)

    def test_cell_indices_decode_to_extensions_inside_their_bands(self):
        space = G.SearchSpace(VALUES, 3, bands=4)
        band_tuple = (1, 3, 0)
        indices = space.cell_combo_indices(band_tuple)
        self.assertEqual(len(indices), len(set(indices)))
        self.assertEqual(len(indices), 5 * 6 * 5)
        for index in indices:
            combo = LH._decode_combo_index(index, VALUES, 3)
            for pair, ext in enumerate(combo):
                lo, hi = space.band_range(band_tuple[pair])
                self.assertTrue(lo <= ext <= hi, (combo, band_tuple))

    def test_neighbourhood_indices_surround_the_centre_and_clamp_at_the_edges(self):
        space = G.SearchSpace(VALUES, 2, bands=4)
        combos = {LH._decode_combo_index(i, VALUES, 2) for i in space.neighbourhood_combo_indices([90, 70], 1)}
        self.assertEqual(combos, {(a, b) for a in (80, 90, 100) for b in (60, 70, 80)})
        edge = {LH._decode_combo_index(i, VALUES, 2) for i in space.neighbourhood_combo_indices([0, 200], 1)}
        self.assertEqual(edge, {(a, b) for a in (0, 10) for b in (190, 200)})

    def test_ranking_uses_joint_probability_and_skips_explored(self):
        space = G.SearchSpace(VALUES, 2, bands=4)
        labels = space.band_labels
        proposal = {
            "pair_bands": [{labels[2]: 0.9, labels[0]: 0.1}, {labels[1]: 0.8, labels[3]: 0.2}],
            "angle": {"high": 0.7, "middle": 0.3},
        }
        self.assertEqual(G.rank_cells(space, proposal, {}), ((2, 1), "high"))
        explored = {((2, 1), "high"): {}}
        self.assertEqual(G.rank_cells(space, proposal, explored), ((2, 1), "middle"))


class GeometryTests(unittest.TestCase):
    @staticmethod
    def adapter(name, start, target, direction):
        return {
            "strand_4_5": {"layer_name": name},
            "strand_2_3": {"start": {"x": 0, "y": 0}, "end": {"x": direction[0] * 5, "y": direction[1] * 5}},
            "original_start": {"x": start[0], "y": start[1]},
            "target_position": {"x": target[0], "y": target[1]},
            "type": "_4", "set_number": 1,
        }

    def test_geometry_names_pairs_and_the_gaps_they_touch(self):
        a = self.adapter("1_4", (0, 0), (100, 0), (3, 4))
        b = self.adapter("2_5", (0, 60), (100, 60), (0, 1))
        c = self.adapter("3_4", (0, 120), (100, 120), (-1, 0))
        geometry = G.build_geometry([a, b, c], [(a, c), (b, None)], 56, 69)
        self.assertEqual(geometry["strand_order"], ["1_4", "2_5", "3_4"])
        self.assertEqual(geometry["strands"][0]["extension_direction"], [0.6, 0.8])
        self.assertEqual(geometry["strands"][0]["reach_px"], 100.0)
        self.assertEqual([s["pair"] for s in geometry["strands"]], [0, 1, 0])
        self.assertEqual(geometry["pairs"][0]["strands"], ["1_4", "3_4"])
        self.assertEqual(geometry["pairs"][0]["gaps_touched"], [0, 1])
        self.assertEqual(geometry["pairs"][1]["strands"], ["2_5"])
        self.assertEqual(geometry["pairs"][1]["gaps_touched"], [0, 1])
        self.assertEqual(geometry["gap_rule"]["min_px"], 56)

    def test_gap_descriptions_carry_status_and_neighbours(self):
        described = G.describe_gaps([48.2, -61.0, 75.5], ["1_4", "2_5", "3_4", "4_5"], 56, 69)
        self.assertEqual([g["status"] for g in described], ["too_tight", "ok", "too_wide"])
        self.assertEqual(described[1]["between"], ["2_5", "3_4"])
        self.assertEqual(described[1]["px"], 61.0)


class GuidedLoopTests(unittest.TestCase):
    def test_heuristic_policy_finds_the_valid_combo_with_a_partial_budget(self):
        summary = G.guided_combo_search(synthetic_evaluate, VALUES, 2, G.HeuristicPolicy(),
                                        budget_fraction=0.6)
        self.assertEqual(len(summary["valid_results"]), 1)
        self.assertEqual(tuple(summary["valid_results"][0]["pair_extensions"]), TARGET)
        self.assertLess(summary["combos_evaluated"], len(VALUES) ** 2)
        self.assertIn(summary["stopped"], ("policy_stop", "patience"))
        self.assertEqual(summary["info"]["policy"], "heuristic")

    def test_band_policy_asks_one_band_question_per_pair_plus_angle_and_stop(self):
        client = FakeJevClient(prefer_band=1, prefer_angle="middle", stop=0.9)
        policy = G.JevBandPolicy(client=client)
        summary = G.guided_combo_search(synthetic_evaluate, VALUES, 2, policy,
                                        problem={"axis": "horizontal", "m": 2, "n": 2, "k": 1})
        self.assertEqual(tuple(summary["valid_results"][0]["pair_extensions"]), TARGET)
        self.assertEqual(summary["stopped"], "policy_stop")
        self.assertEqual(policy.calls, 2)
        self.assertEqual(summary["info"]["policy_input_tokens"], 2 * _Usage.input_tokens)

        first_state, first_questions = client.requests[0]
        self.assertEqual(set(first_questions), {"pair_0_band", "pair_1_band", "angle_third"})
        self.assertEqual(first_state["problem"]["k"], 1)
        self.assertIsNone(first_state["best_valid"])

        second_state, second_questions = client.requests[1]
        self.assertIn("stop", second_questions)
        self.assertEqual(second_state["best_valid"]["pair_extensions"], [80.0, 60.0])
        self.assertEqual(len(second_state["explored_cells"]), 1)

    def test_proposal_policy_refines_from_the_closest_configuration(self):
        # Round 1 starts in the 0-40 bands; the closest invalid combo there is (40, 40).
        # Round 2 should refine: pair 0 longer by five steps (-> 90), pair 1 longer by
        # three (-> 70); the neighbourhood around (90, 70) contains the valid (80, 60).
        client = FakeJevClient(prefer_band=0, prefer_angle="middle", strategy="refine", stop_when_valid=True,
                               moves={0: "longer", 1: "longer"}, step_levels={0: 2, 1: 1})
        policy = G.JevPolicy(client=client)
        outer = GeometryTests.adapter("1_4", (0, 0), (100, 0), (1, 0))
        inner = GeometryTests.adapter("2_5", (0, 60), (100, 60), (1, 0))
        geometry = G.build_geometry([outer, inner], [(outer, None), (inner, None)], 56, 69)
        summary = G.guided_combo_search(synthetic_evaluate, VALUES, 2, policy,
                                        problem={"axis": "horizontal"}, geometry=geometry)

        self.assertEqual(tuple(summary["valid_results"][0]["pair_extensions"]), TARGET)
        self.assertEqual(summary["stopped"], "policy_stop")
        self.assertEqual(policy.calls, 3)
        self.assertEqual([r["kind"] for r in summary["cells"]], ["start", "move"])
        self.assertEqual(summary["cells"][1]["centre_px"], [90, 70])
        self.assertEqual(summary["info"]["rounds_by_kind"]["move"], 1)

        first_state, first_questions = client.requests[0]
        self.assertNotIn("strategy", first_questions)
        self.assertEqual(first_state["geometry"]["strand_order"], ["1_4", "2_5"])

        second_state, second_questions = client.requests[1]
        self.assertEqual(
            {"strategy", "move_pair_0", "move_pair_1", "step_pair_0", "step_pair_1"} - set(second_questions), set())
        self.assertNotIn("stop", second_questions["strategy"]["criteria"])
        self.assertEqual(second_state["closest_invalid"]["pair_extensions"], [40.0, 40.0])
        self.assertEqual([g["status"] for g in second_state["closest_invalid"]["gaps"]], ["too_tight", "ok"])

        third_state, third_questions = client.requests[2]
        self.assertIn("stop", third_questions["strategy"]["criteria"])
        self.assertEqual(third_state["best_valid"]["pair_extensions"], [80.0, 60.0])
        self.assertEqual(third_state["proposal_history"][1]["kind"], "move")
        self.assertEqual(third_state["proposal_history"][1]["moves"], [{"direction": 1, "steps": 5}, {"direction": 1, "steps": 3}])

    def test_move_rounds_skip_combos_already_evaluated(self):
        client = FakeJevClient(prefer_band=0, strategy="refine", moves={0: "keep", 1: "keep"})
        summary = G.guided_combo_search(synthetic_evaluate, VALUES, 2, G.JevPolicy(client=client),
                                        max_rounds=2)
        self.assertEqual(summary["cells"][0]["combos"], 25)
        # The 30-50 x 30-50 neighbourhood of (40, 40) overlaps the 0-40 cell in four combos.
        self.assertEqual(summary["cells"][1]["kind"], "move")
        self.assertEqual(summary["cells"][1]["combos"], 5)

    def test_policy_error_ends_the_guided_phase_without_raising(self):
        class Broken:
            name = "broken"

            def propose(self, state, space):
                raise RuntimeError("no network")

        summary = G.guided_combo_search(synthetic_evaluate, VALUES, 2, Broken())
        self.assertEqual(summary["stopped"], "policy_error")
        self.assertEqual(summary["valid_results"], [])

    def test_make_policy_names(self):
        self.assertIsNone(G.make_policy(None))
        self.assertIsNone(G.make_policy("off"))
        self.assertIsInstance(G.make_policy("heuristic"), G.HeuristicPolicy)
        with self.assertRaises(ValueError):
            G.make_policy("magic")


class ClearanceRuleTests(unittest.TestCase):
    def test_start_clearance_measures_distance_to_the_first_crossing(self):
        import numpy as np
        p = np.array([[0.0, 0.0], [0.0, 50.0], [0.0, 150.0]])
        q = np.array([[100.0, 0.0], [100.0, 50.0], [100.0, 150.0]])
        r = np.array([[30.0, -100.0], [-20.0, 40.0], [10.0, 200.0]])
        s = np.array([[30.0, 100.0], [-20.0, 60.0], [90.0, 200.0]])
        clearances = LH._start_clearances(p, q, r, s)
        self.assertAlmostEqual(clearances[0], 30.0)      # crosses the vertical arm 30px in
        self.assertAlmostEqual(clearances[1], -20.0)     # the crossing lies behind the start
        self.assertEqual(clearances[2], float("inf"))    # parallel: no crossing
        self.assertEqual(G.start_clearance((0, 50), (100, 50), [((-20, 40), (-20, 60))]), -20.0)
        self.assertIsNone(G.start_clearance((0, 150), (100, 150), [((10, 200), (90, 200))]))

    def test_rule_off_reproduces_the_old_short_arm_result(self):
        with contextlib.redirect_stdout(io.StringIO()):
            strands = _get_active_strands(json.loads(LH.generate_json(1, 2, k=2, direction="cw")))
            with mock.patch.dict(os.environ, {"MXN_ALIGNMENT_GUIDED": "", "MXN_ALIGNMENT_CLEARANCE": "0"}):
                _, h_off, v_off, info_off = LH.align_level_parallel(strands, 2, 1, k=2, direction="cw")
            with mock.patch.dict(os.environ, {"MXN_ALIGNMENT_GUIDED": "", "MXN_ALIGNMENT_CLEARANCE": ""}):
                aligned, h_on, v_on, info_on = LH.align_level_parallel(strands, 2, 1, k=2, direction="cw")
        self.assertEqual(tuple(v_off["pair_extensions"]), (0,))
        self.assertEqual(info_off["clearance_rule_px"], 0.0)
        self.assertEqual(info_on["clearance_rule_px"], 23.0)
        self.assertGreater(v_on["pair_extensions"][0], 0)
        _, h_order, _, v_order = LH._build_k_based_strand_sets(1, 2, 2, "cw")
        self.assertGreaterEqual(LH._group_start_clearance(aligned, v_order, h_order), 23.0)
        self.assertGreaterEqual(LH._group_start_clearance(aligned, h_order, v_order), 23.0)

    def test_second_pass_resolves_h_against_the_final_v_arms(self):
        with contextlib.redirect_stdout(io.StringIO()):
            strands = _get_active_strands(json.loads(LH.generate_json(3, 2, k=2, direction="cw")))
            with mock.patch.dict(os.environ, {"MXN_ALIGNMENT_GUIDED": "", "MXN_ALIGNMENT_CLEARANCE": ""}):
                aligned, h_res, v_res, info = LH.align_level_parallel(strands, 2, 3, k=2, direction="cw")
        self.assertTrue(h_res["success"] and v_res["success"])
        _, h_order, _, v_order = LH._build_k_based_strand_sets(3, 2, 2, "cw")
        self.assertGreaterEqual(LH._group_start_clearance(aligned, h_order, v_order), 23.0)
        self.assertGreaterEqual(LH._group_start_clearance(aligned, v_order, h_order), 23.0)
        self.assertEqual(info["h_clearance_px"], round(LH._group_start_clearance(aligned, h_order, v_order), 1))
        self.assertGreaterEqual(info["passes"], 1)


class EngineIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with contextlib.redirect_stdout(io.StringIO()):
            cls.source = LH.generate_json(2, 2, k=1, direction="cw")

    def strands(self):
        return _get_active_strands(json.loads(self.source))

    def align(self, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return LH.align_horizontal_strands_parallel(
                self.strands(), 2, m=2, k=1, direction="cw",
                max_pair_extension=200, pair_extension_step=10, use_gpu=False, **kwargs)

    def test_exhaustive_search_is_the_default(self):
        with mock.patch.dict(os.environ, {"MXN_ALIGNMENT_GUIDED": ""}):
            result = self.align()
        self.assertTrue(result["success"])
        self.assertEqual(result["search"], {"mode": "exhaustive"})

    def test_guided_search_finds_a_valid_alignment_with_fewer_combos(self):
        with mock.patch.dict(os.environ, {"MXN_ALIGNMENT_GUIDED": ""}):
            exhaustive = self.align()
            guided = self.align(guided_search=G.HeuristicPolicy())
        self.assertTrue(exhaustive["success"])
        self.assertTrue(guided["success"], guided.get("message"))
        self.assertEqual(guided["search"]["mode"], "guided")
        self.assertLess(guided["search"]["combos_evaluated"], guided["search"]["combos_total"])
        self.assertTrue(guided["min_gap"] <= guided["average_gap"] <= guided["max_gap"])
        self.assertEqual(len(guided["configurations"]), len(exhaustive["configurations"]))

    def test_engine_passes_geometry_to_the_policy(self):
        seen = {}

        class Recorder(G.HeuristicPolicy):
            name = "recorder"

            def propose(self, state, space):
                seen.setdefault("geometry", state["geometry"])
                return super().propose(state, space)

        with mock.patch.dict(os.environ, {"MXN_ALIGNMENT_GUIDED": ""}):
            self.align(guided_search=Recorder())
        geometry = seen["geometry"]
        self.assertEqual(len(geometry["strand_order"]), 4)
        self.assertEqual(len(geometry["pairs"]), 2)
        self.assertEqual(geometry["pairs"][0]["position"], "the outermost two strands")
        self.assertEqual(geometry["gap_rule"]["min_px"], 56)
        for strand in geometry["strands"]:
            self.assertAlmostEqual(sum(c * c for c in strand["extension_direction"]), 1.0, places=2)

    def test_env_var_selects_the_policy_and_unavailable_jev_degrades_to_exhaustive(self):
        with mock.patch.dict(os.environ, {"MXN_ALIGNMENT_GUIDED": "heuristic"}):
            result = self.align()
        self.assertEqual(result["search"]["mode"], "guided")
        self.assertEqual(result["search"]["policy"], "heuristic")

        with mock.patch.dict(os.environ, {"MXN_ALIGNMENT_GUIDED": "jev", "TYPESAFE_API_KEY": ""}):
            result = self.align()
        self.assertTrue(result["success"])
        self.assertEqual(result["search"], {"mode": "exhaustive"})


if __name__ == "__main__":
    unittest.main()
