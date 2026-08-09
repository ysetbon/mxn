"""Regression tests for the L0 -> L1 purple-crossing extension origin."""

import contextlib
import io
import json
import math
import os
import sys
import unittest


HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))

import mxn_continuation_next as NX
from ui_utils import _get_active_strands


class LevelOneAnchorTests(unittest.TestCase):
    def setUp(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.starting_json, self.strands, self.info = NX.build_level_one(
                2, 2, 1, "lh", "cw", verbose=False)

    def test_level_one_starts_at_each_l0_outermost_crossing(self):
        starting = _get_active_strands(json.loads(self.starting_json))
        before = {
            strand["layer_name"]: strand
            for strand in starting
            if strand.get("type") == "AttachedStrand"
            and strand.get("layer_name", "").endswith(("_2", "_3"))
        }
        expected = NX.crossing_anchors(before)
        after = {strand["layer_name"]: strand for strand in self.strands}

        self.assertEqual(set(expected), set(before))
        for name, distance in expected.items():
            old_end = before[name]["end"]
            purple = after[name]["end"]
            actual = math.hypot(
                old_end["x"] - purple["x"], old_end["y"] - purple["y"])
            self.assertAlmostEqual(actual, distance, places=6, msg=name)
            self.assertNotAlmostEqual(actual, NX.RETRACT, places=6, msg=name)

            children = [
                strand for strand in self.info["new_strands"]
                if strand.get("attached_to") == name
            ]
            self.assertEqual(len(children), 1, name)
            self.assertEqual(children[0]["start"], purple, name)

    def test_level_one_uses_generic_continuation_metadata(self):
        self.assertEqual(self.info["level"], 1)
        self.assertEqual(len(self.info["new_strands"]), 8)
        self.assertEqual(len(self.info["new_masks"]), 8)
        self.assertEqual(set(self.info["real_to_virtual"]), {
            "1_2", "1_3", "2_2", "2_3", "3_2", "3_3", "4_2", "4_3"
        })


if __name__ == "__main__":
    unittest.main()
