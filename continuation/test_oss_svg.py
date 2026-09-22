"""The Qt-free SVG renderer (src/oss_svg.py) must draw exactly like OpenStrandStudio.

The pixel comparison needs PyQt5, cairosvg, numpy, Pillow and an
`openstrandstudio/` checkout next to `src/`; it is skipped when any is missing.

    python3 -m unittest continuation/test_oss_svg.py
"""

import contextlib
import copy
import importlib.util
import io
import json
import os
import sys
import unittest


HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import mxn_continuation_next as NX
import oss_svg
from ui_utils import _get_active_strands


def _level_one(m, n, k, hand, align=True):
    direction = "cw" if hand == "lh" else "ccw"
    with contextlib.redirect_stdout(io.StringIO()):
        starting, strands, info = NX.build_level_one(m, n, k, hand, direction, verbose=False)
        if align:
            NX.align_continuation_level(strands, m, n, k, direction, hand, 1, info, verbose=False)
    return _get_active_strands(json.loads(starting)), strands


class LoaderRulesTests(unittest.TestCase):
    def setUp(self):
        _, self.strands = _level_one(2, 2, 1, "lh")

    def test_junction_ends_get_circles_as_after_loading(self):
        circles = oss_svg.effective_circles(self.strands)
        by_name = {s["layer_name"]: s for s in self.strands}
        for name, s in by_name.items():
            if s["type"] != "AttachedStrand" or not name.endswith("_2"):
                continue
            # The JSON leaves has_circles[1] off, but a `_4` starts at this end,
            # so OpenStrandStudio draws an end circle and no side line there.
            self.assertFalse(s["has_circles"][1])
            self.assertEqual(circles[name], [True, True], name)
            arm = by_name[name[:-2] + "_4"]
            self.assertEqual((arm["start"]["x"], arm["start"]["y"]),
                             (s["end"]["x"], s["end"]["y"]))
        for name, s in by_name.items():
            if name.endswith(("_4", "_5")) and s["type"] == "AttachedStrand":
                self.assertEqual(circles[name], [True, False], name)

    def test_layer_order_follows_index_slots(self):
        strands = copy.deepcopy(self.strands)
        for i, s in enumerate(strands):
            s["index"] = len(strands) - 1 - i
        order = [s["layer_name"] for s in oss_svg.layer_order(strands)]
        self.assertEqual(order, [s["layer_name"] for s in reversed(strands)])
        # a repeated index keeps only the last strand written to that slot
        strands[0]["index"] = strands[1]["index"]
        self.assertEqual(len(oss_svg.layer_order(strands)), len(strands) - 1)


def _missing_pixel_deps():
    for mod in ("PyQt5", "cairosvg", "numpy", "PIL"):
        if importlib.util.find_spec(mod) is None:
            return mod
    for base in (ROOT, os.path.dirname(ROOT)):
        if os.path.isfile(os.path.join(base, "openstrandstudio", "src", "strand.py")):
            return None
    return "openstrandstudio checkout"


@unittest.skipIf(_missing_pixel_deps(), f"needs {_missing_pixel_deps()}")
class MatchesOpenStrandStudioTests(unittest.TestCase):
    """Rasterise the SVG and OpenStrandStudio's own render; no solid difference."""

    @classmethod
    def setUpClass(cls):
        import mxn_continuation_render as RND
        cls.RND = RND
        cls.canvas, _ = RND.create_render_canvas()

    def _oss(self, strands, view):
        import numpy as np
        from PyQt5.QtCore import QRectF
        from PyQt5.QtGui import QImage
        self.RND.load_json_into_canvas(NX._history_json(strands), self.canvas)
        x0, y0, x1, y1 = view
        img = self.RND.render_canvas_image(self.canvas, QRectF(x0, y0, x1 - x0, y1 - y0), 1.0)
        img = img.convertToFormat(QImage.Format_RGBA8888)
        ptr = img.bits()
        ptr.setsize(img.byteCount())
        return np.frombuffer(ptr, np.uint8).reshape(img.height(), img.width(), 4)[..., :3].copy()

    def _svg(self, strands, view):
        import cairosvg
        import numpy as np
        from PIL import Image
        x0, y0, x1, y1 = view
        w, h = x1 - x0, y1 - y0
        defs, body = oss_svg.draw_strands(strands)
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
               f'viewBox="{x0} {y0} {w} {h}"><rect x="{x0}" y="{y0}" width="{w}" '
               f'height="{h}" fill="white"/><defs>{defs}</defs>{body}</svg>')
        png = cairosvg.svg2png(bytestring=svg.encode(), output_width=w, output_height=h)
        return np.array(Image.open(io.BytesIO(png)).convert("RGB"))

    def assertSameDrawing(self, strands, tag):
        import numpy as np
        x0, y0, x1, y1 = oss_svg.strand_bounds(strands)
        view = (int(x0) - 100, int(y0) - 100, int(x1) + 100, int(y1) + 100)
        d = np.abs(self._oss(strands, view).astype(int)
                   - self._svg(strands, view).astype(int)).max(axis=2)
        bad = d > 100
        # antialiasing differs on single edge pixels; a 2x2 block is a real miss
        solid = bad[:-1, :-1] & bad[1:, :-1] & bad[:-1, 1:] & bad[1:, 1:]
        self.assertEqual(int(solid.sum()), 0, f"{tag}: {int(bad.sum())} pixels differ")

    def test_starting_stitch_and_level_one(self):
        for m, n, k, hand in ((2, 2, 1, "lh"), (1, 2, -1, "rh"), (2, 3, 2, "lh")):
            starting, strands = _level_one(m, n, k, hand)
            # Before alignment the `_2` end caps show from under their `_4` arms.
            _, unaligned = _level_one(m, n, k, hand, align=False)
            for tag, doc in (("start", starting), ("level1", strands),
                             ("level1 unaligned", unaligned)):
                with self.subTest(m=m, n=n, k=k, hand=hand, stage=tag):
                    reindexed = [dict(s, index=i) for i, s in enumerate(doc)]
                    self.assertSameDrawing(reindexed, tag)
                    # stale indices: OpenStrandStudio's slot loading, reproduced
                    self.assertSameDrawing(copy.deepcopy(doc), tag + " stale")


if __name__ == "__main__":
    unittest.main()
