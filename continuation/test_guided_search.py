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
        "best_fallback": {"gaps": [best_gap, best_gap], "average_gap": best_gap} if best_combo else None,
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


class _Usage:
    input_tokens = 321
    output_tokens = 0


class _Response:
    def __init__(self, choices, nouls):
        self.choices, self.nouls, self.usage = choices, nouls, _Usage()


class FakeJevClient:
    """Mimics TypeSafeClient.system_one with fixed preferences; records every request."""

    def __init__(self, prefer_band=1, prefer_angle="middle", stop=0.0):
        self.prefer_band, self.prefer_angle, self.stop, self.requests = prefer_band, prefer_angle, stop, []

    def system_one(self, state, questions):
        json.dumps(state)
        json.dumps(questions)
        self.requests.append((state, questions))
        choices = {}
        for name, question in questions.items():
            if question["type"] != "choice":
                continue
            labels = list(question["criteria"])
            favourite = self.prefer_angle if name == "angle_third" else labels[min(self.prefer_band, len(labels) - 1)]
            rest = 0.3 / max(len(labels) - 1, 1)
            choices[name] = _Choice({label: (0.7 if label == favourite else rest) for label in labels})
        nouls = {"stop": _Noul(self.stop)} if "stop" in questions else {}
        return _Response(choices, nouls)


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


class GuidedLoopTests(unittest.TestCase):
    def test_heuristic_policy_finds_the_valid_combo_with_a_partial_budget(self):
        summary = G.guided_combo_search(synthetic_evaluate, VALUES, 2, G.HeuristicPolicy(),
                                        budget_fraction=0.6)
        self.assertEqual(len(summary["valid_results"]), 1)
        self.assertEqual(tuple(summary["valid_results"][0]["pair_extensions"]), TARGET)
        self.assertLess(summary["combos_evaluated"], len(VALUES) ** 2)
        self.assertIn(summary["stopped"], ("policy_stop", "patience"))
        self.assertEqual(summary["info"]["policy"], "heuristic")

    def test_jev_policy_asks_one_band_question_per_pair_plus_angle_and_stop(self):
        client = FakeJevClient(prefer_band=1, prefer_angle="middle", stop=0.9)
        policy = G.JevPolicy(client=client)
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
        self.assertEqual(first_state["search"]["combos_evaluated"], 0)

        second_state, second_questions = client.requests[1]
        self.assertIn("stop", second_questions)
        self.assertEqual(second_questions["stop"]["type"], "noul")
        self.assertEqual(second_state["best_valid"]["pair_extensions"], [80.0, 60.0])
        self.assertEqual(len(second_state["explored_cells"]), 1)
        self.assertEqual(second_state["explored_cells"][0]["valid"], 1)

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
