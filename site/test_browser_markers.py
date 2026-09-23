"""The browser markers (dist/markers.js) must place what src/mxn_emoji_renderer.py draws.

EmojiRenderer draws through a recording painter, over lightweight strands built from the
Python generators, and every draw call (animal, name box, rotation indicator part) is
compared with computeMarkerLayout for the same pattern. Qt's font measurements are handed
to the JS so only the placement logic is compared.

Run: python -m unittest test_browser_markers -v (from this directory). Needs node and PyQt5.
"""
import contextlib
import importlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'src'))
try:
    from PyQt5.QtCore import QPointF, QRectF
    from PyQt5.QtGui import QFont, QFontMetrics, QGuiApplication, QImage, QPainterPath, QPen
    import mxn_emoji_renderer
    from mxn_emoji_renderer import EmojiRenderer
    from mxn_dialog_render_mixin import RenderMixin
except ImportError:
    EmojiRenderer = None

MODULES = {('lh', False): 'mxn_lh', ('rh', False): 'mxn_rh', ('lh', True): 'mxn_lh_strech', ('rh', True): 'mxn_rh_stretch'}
KS = [-3, -2, -1, 0, 1, 2, 3, 7, -11, 50, 9999]
TOL = 1e-6


class FakeStrand:
    def __init__(self, s):
        self.start, self.end = QPointF(s['start']['x'], s['start']['y']), QPointF(s['end']['x'], s['end']['y'])
        cps = (s.get('control_points') or []) + [None, None]
        self.control_point1, self.control_point2 = [QPointF(p['x'], p['y']) if p else None for p in cps[:2]]
        self.layer_name, self.width, self.set_number = s['layer_name'], s['width'], s['set_number']


class FakeCanvas:
    def __init__(self, strands):
        self.strands = strands


class Bounds(RenderMixin):
    BOUNDS_PADDING = 100


class RecordingPainter:
    """Stands in for QPainter: records the geometry of every draw call."""
    def __init__(self, renderer):
        self.renderer, self.ops, self.font, self.pen = renderer, [], QFont(), None

    def __getattr__(self, name):
        return lambda *args: None

    def setFont(self, font):
        self.font = font

    def fontMetrics(self):
        return QFontMetrics(self.font)

    def setPen(self, pen):
        self.pen = pen if isinstance(pen, QPen) else None

    def translate(self, *a):
        self.ops.append(('translate', a[0], a[1]))

    def scale(self, sx, sy):
        self.ops.append(('scale', sx, sy))

    def drawImage(self, rect, _image):
        self.ops.append(('emoji', self.renderer.last_txt, rect.x(), rect.y(), rect.width(), rect.height()))

    def drawRoundedRect(self, rect, *_):
        self.ops.append(('namebox', rect.x() + 1, rect.y() + 1, rect.width() - 2, rect.height() - 2))

    def drawText(self, rect, _flags, txt):
        self.ops.append(('text', txt, rect.x(), rect.y(), rect.width(), rect.height()))

    def drawArc(self, rect, start, span):
        self.ops.append(('arc', self.pen.widthF(), (rect.x(), rect.y(), rect.width(), rect.height()), start, span))

    def drawPath(self, path):
        if getattr(path, 'text', None) is not None:
            c = path.boundingRect().center()
            self.ops.append(('ktext', path.text, c.x(), c.y(), self.pen and self.pen.widthF()))
        else:
            pts = [(path.elementAt(i).x, path.elementAt(i).y) for i in range(path.elementCount() - 1)]
            self.ops.append(('path', pts, self.pen and self.pen.widthF()))


class TextPath(QPainterPath):
    text = None

    def addText(self, x, y, font, text):
        self.text = text
        super().addText(x, y, font, text)


class Recorder(EmojiRenderer):
    last_txt = None
    extents = {}  # the pixel-scan measurement is slow; share it between renderers

    def __init__(self):
        super().__init__()
        self._emoji_visual_extents_cache = self.extents

    def _get_emoji_glyph_image(self, txt, *_args, **_kw):
        self.last_txt = txt
        return QImage(1, 1, QImage.Format_ARGB32_Premultiplied)

    def _analyze_glyph_halo(self, _img):
        return {'status': 'OK'}


@unittest.skipUnless(shutil.which('node'), 'node is not installed')
@unittest.skipUnless(EmojiRenderer is not None, 'PyQt5 is not installed')
class BrowserMarkerParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])
        mxn_emoji_renderer.QPainterPath = TextPath
        cls.docs = {}
        cases = []
        for hand in ('lh', 'rh'):
            for stretch in (False, True):
                for m in range(1, 7):
                    for n in range(1, 7):
                        for k in KS:
                            cases.append(dict(m=m, n=n, k=k, hand=hand, stretch=stretch, animals=True, names=True, transparent=True))
                        cases.append(dict(m=m, n=n, k=2, hand=hand, stretch=stretch, animals=False, names=True, transparent=True))
                        cases.append(dict(m=m, n=n, k=-1, hand=hand, stretch=stretch, animals=True, names=False, transparent=False))
                        # Markers frozen on the other variant, as Continuation does after the stitch moves.
                        cases.append(dict(m=m, n=n, k=0, hand=hand, stretch=stretch, animals=True, names=True, transparent=True,
                                          freeze=dict(stretch=not stretch, k=m - n + 1)))
        emoji_font = QFont('Segoe UI Emoji')
        emoji_font.setPointSize(20)
        name_font = QFont('Segoe UI')
        name_font.setPointSize(7)
        name_font.setBold(True)
        renderer, fm = Recorder(), QFontMetrics(name_font)
        # Qt measures fonts through the painter's device; QFontMetrics(font) uses the same 96 dpi here.
        extents = {txt: renderer._get_visual_text_extents(txt, emoji_font) for txt in renderer.make_labels(24)}
        names = {f'{i}_{j}': [fm.boundingRect(f'{i}_{j}').width(), fm.boundingRect(f'{i}_{j}').height()]
                 for i in range(1, 13) for j in (2, 3)}
        payload = dict(cases=cases, extents=extents, names=names, labels=dict(count=123, k=-7, direction='ccw'))
        output = subprocess.run(['node', str(HERE / 'tools' / 'marker_parity.mjs')], input=json.dumps(payload),
                                check=True, capture_output=True, text=True).stdout
        cls.cases, cls.browser = cases, json.loads(output)

    def canvas(self, m, n, hand, stretch):
        key = (m, n, hand, stretch)
        if key not in self.docs:
            doc = json.loads(importlib.import_module(MODULES[(hand, stretch)]).generate_json(m, n))
            state = next(s for s in doc['states'] if s['step'] == doc['current_step'])
            self.docs[key] = FakeCanvas([FakeStrand(s) for s in state['data']['strands']])
        return self.docs[key]

    def assertClose(self, a, b, msg=None):
        if isinstance(a, (list, tuple)):
            self.assertEqual(len(a), len(b), msg)
            for x, y in zip(a, b):
                self.assertClose(x, y, msg)
        elif isinstance(a, float) or isinstance(b, float):
            self.assertAlmostEqual(a, b, delta=TOL, msg=msg)
        else:
            self.assertEqual(a, b, msg)

    def python_ops(self, c):
        canvas = self.canvas(c['m'], c['n'], c['hand'], c['stretch'])
        bounds = Bounds()._calculate_strands_bounds(canvas)
        renderer = Recorder()
        direction = 'cw' if c['hand'] == 'lh' else 'ccw'
        frozen = None
        if c.get('freeze'):
            source = self.canvas(c['m'], c['n'], c['hand'], c['freeze']['stretch'])
            with contextlib.redirect_stdout(io.StringIO()):
                renderer.freeze_emoji_assignments(source, Bounds()._calculate_strands_bounds(source), c['m'], c['n'],
                                                  {'k': c['freeze']['k'], 'direction': direction})
            frozen = {f'{name}|{ep}': emoji for (name, ep), emoji in renderer._frozen_endpoint_emojis.items()}
        settings = {'show': c['animals'], 'show_strand_names': c['names'], 'show_rotation_indicator': c['animals'],
                    'k': c['k'], 'direction': direction, 'transparent': c['transparent']}
        painter = RecordingPainter(renderer)
        renderer.draw_endpoint_emojis(painter, canvas, bounds, c['m'], c['n'], settings)
        markers = list(painter.ops)
        painter.ops.clear()
        renderer.draw_rotation_indicator(painter, bounds, settings)
        slots = renderer.compute_slots_from_strands(canvas, bounds, c['m'], c['n'])
        return bounds, frozen, markers, painter.ops, slots

    @staticmethod
    def js_marker_ops(layout):
        ops = []
        for item in layout['items']:
            if 'emoji' in item:
                e = item['emoji']
                ops.append(('emoji', item['txt'], e['x'], e['y'], e['w'], e['h']))
            if 'name' in item:
                r = item['name']
                ops.append(('namebox', r['x'], r['y'], r['w'], r['h']))
                ops.append(('text', r['text'], r['x'], r['y'], r['w'], r['h']))
        return ops

    @staticmethod
    def js_indicator_ops(g):
        if g is None:
            return []
        ops = [('translate', *g['origin']), ('scale', g['scale'], g['scale'])]
        if g['mirrored']:
            ops += [('translate', 604.0, 0.0), ('scale', -1.0, 1.0)]
        arc = (tuple(float(v) for v in g['arc']['rect']), g['arc']['start16'], g['arc']['span16'])
        ops.append(('arc', g['arcOutlineWidth'], *arc))
        ops.append(('path', [tuple(p) for p in g['cap']], None))
        ops.append(('arc', g['arcWidth'], *arc))
        tri = [tuple(p) for p in g['arrowhead']]
        ops += [('path', tri, g['arrowheadOutlineWidth']), ('path', tri, None)]
        ops += [('ktext', g['text'], *g['center'], g['textOutlineWidth']), ('ktext', g['text'], *g['center'], None)]
        return ops

    def test_labels_and_rotation(self):
        r = EmojiRenderer()
        self.assertEqual(self.browser['labels'], r.make_labels(123))
        self.assertEqual(self.browser['rotated'], r.rotate_labels(r.make_labels(123), -7, 'ccw'))

    def test_every_case_matches(self):
        for c, js in zip(self.cases, self.browser['results']):
            with self.subTest(**{k: v for k, v in c.items()}):
                bounds, frozen, markers, indicator, slots = self.python_ops(c)
                self.assertClose([js['bounds'][k] for k in ('x', 'y', 'width', 'height')],
                                 [bounds.x(), bounds.y(), bounds.width(), bounds.height()])
                self.assertEqual(js['frozen'], frozen)
                if frozen is not None:
                    self.assertEqual(list(js['frozen']), list(frozen), 'frozen insertion order')
                self.assertTrue(markers or not (c['animals'] or c['names']))
                self.assertClose(self.js_marker_ops(js['layout']), markers)
                self.assertClose(self.js_indicator_ops(js['layout']['indicator']), indicator)
                self.assertClose([[s[k] for k in ('id', 'side', 'side_index', 'x', 'y', 'nx', 'ny')] for s in js['slots']],
                                 [[s[k] for k in ('id', 'side', 'side_index', 'x', 'y', 'nx', 'ny')] for s in slots])


if __name__ == '__main__':
    unittest.main()
