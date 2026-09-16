"""Adapter for the desktop MxN RenderMixin, with no replacement drawing code."""
import base64
import contextlib
import importlib
import io
import json
import os
from pathlib import Path
import re
import sys
import types
from functools import lru_cache

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parent.parent
OSS = Path(os.environ.get('OPENSTRANDSTUDIO_DIR', str(ROOT.parent / 'openstrandstudio'))).resolve()
if not (OSS / 'src' / 'main_window.py').is_file():
    raise RuntimeError('OpenStrandStudio source is missing. Set OPENSTRANDSTUDIO_DIR to its checkout.')
sys.path[:0] = [str(ROOT / 'src'), str(OSS.parent), str(OSS / 'src')]
# The GitHub checkout is commonly named OpenStrandStudio, while the MxN
# renderer imports the lower-case package. Bind its real source directory.
if 'openstrandstudio' not in sys.modules:
    package = types.ModuleType('openstrandstudio')
    package.__path__ = [str(OSS)]
    sys.modules['openstrandstudio'] = package

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QBuffer, QIODevice
from PyQt5.QtGui import QFontDatabase, QFont, QRawFont
from PyQt5 import sip
# The desktop's global proxy styles can outlive QApplication during Python
# shutdown. Avoid destructing Qt wrappers after their C++ owners have gone.
sip.setdestroyonexit(False)
from mxn_dialog_render_mixin import RenderMixin
from mxn_emoji_renderer import EmojiRenderer


class Value:
    def __init__(self, value):
        self.current = value

    def isChecked(self):
        return bool(self.current)

    def value(self):
        return self.current


@lru_cache(maxsize=16)
def generated_document(name, m, n, k, direction):
    """Keep a pattern stable when only its display options change."""
    generator = importlib.import_module(name).generate_json
    kwargs = {'k': k, 'direction': direction} if name.endswith('_continuation') else {}
    return generator(m, n, **kwargs)


def validate(request):
    if not isinstance(request, dict):
        raise ValueError('Expected a settings object')
    result = {}
    for key, low, high, default in [('m', 1, 10, 2), ('n', 1, 10, 2), ('k', -9999, 9999, 0), ('scale', 1, 4, 1)]:
        v = request.get(key, default)
        if type(v) is not int or not low <= v <= high:
            raise ValueError(f'{key} must be an integer between {low} and {high}')
        result[key] = v
    result['hand'] = request.get('hand', 'lh')
    if result['hand'] not in ('lh', 'rh'):
        raise ValueError('Invalid handedness')
    for key, default in [('stretch', False), ('continuation', False), ('animals', True), ('names', False), ('transparent', True)]:
        value = request.get(key, default)
        if type(value) is not bool:
            raise ValueError(f'{key} must be true or false')
        result[key] = value
    if result['continuation'] and not result['stretch']:
        raise ValueError('Continuation requires stretch')
    result['emojiSet'] = request.get('emojiSet', 'fluent')
    if result['emojiSet'] not in ('default', 'fluent', 'twemoji', 'openmoji', 'joypixels'):
        raise ValueError('Unknown animal artwork set')
    result['colors'] = request.get('colors', [])
    if not isinstance(result['colors'], list) or len(result['colors']) != result['m'] + result['n']:
        raise ValueError('Supply one color for each strand set')
    if not all(isinstance(c, str) and re.fullmatch(r'#[0-9a-fA-F]{6}', c) for c in result['colors']):
        raise ValueError('Colors must use #RRGGBB format')
    return result


class NativeRenderer(RenderMixin):
    BOUNDS_PADDING = 100

    def __init__(self):
        self.app = QApplication.instance() or QApplication([])
        self.app.setQuitOnLastWindowClosed(False)
        self._load_render_fonts()
        self._main_window = None
        self._prepared_canvas_key = None
        self._prepared_bounds = None
        self._cached_strand_layer = None
        self._cached_strand_layer_key = None
        self._emoji_renderer = EmojiRenderer()

    @staticmethod
    def _load_render_fonts():
        """Windows Qt offscreen has no system fonts until explicitly registered.

        Reuse the installed desktop fonts, including real bold glyphs, so the
        signed k value and strand labels are not rendered as missing-glyph boxes.
        Do not copy or distribute system font files with the hosted site.
        """
        if sys.platform == 'win32':
            directory = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
            for filename in ('segoeui.ttf', 'segoeuib.ttf', 'arial.ttf', 'arialbd.ttf'):
                path = directory / filename
                if path.is_file():
                    QFontDatabase.addApplicationFont(str(path))
        font = QFont('Segoe UI', 14)
        font.setBold(True)
        glyphs = QRawFont.fromFont(font).glyphIndexesForString('+0123456789-')
        if len(set(glyphs)) < 12 or 0 in glyphs:
            raise RuntimeError('No usable font for rotation numbers. Install a TrueType text font before starting the renderer.')

    def _get_main_window(self):
        if self._main_window is None:
            from openstrandstudio.src.main_window import MainWindow
            self._main_window = MainWindow()
            self._main_window.hide()
        return self._main_window

    def render(self, request, document=None):
        p = validate(request)
        if document is None:
            self._emoji_renderer.clear_cache()
        # All Qt calls are made on the process's main thread.
        # Desktop diagnostics must not pollute the HTTP response or logs.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            name = 'mxn_' + p['hand']
            if p['continuation']:
                name += '_continuation'
            elif p['stretch']:
                name += '_strech' if p['hand'] == 'lh' else '_stretch'
            data = json.loads(json.dumps(document)) if document is not None else json.loads(generated_document(name, p['m'], p['n'], p['k'], 'cw' if p['hand'] == 'lh' else 'ccw'))
            for state in data.get('states', [{'data': data}]):
                for strand in state['data'].get('strands', []):
                    i = strand.get('set_number', 0) - 1
                    if 0 <= i < len(p['colors']):
                        c = p['colors'][i]
                        strand['color'] = dict(r=int(c[1:3], 16), g=int(c[3:5], 16), b=int(c[5:7], 16), a=255)
            self.m_spinner, self.n_spinner = Value(p['m']), Value(p['n'])
            self.emoji_k_spinner = Value(p['k'])
            self.emoji_cw_radio = Value(p['hand'] == 'lh')
            self.show_emojis_checkbox = Value(p['animals'])
            self.show_strand_names_checkbox = Value(p['names'])
            self.transparent_checkbox = Value(p['transparent'])
            if self._emoji_renderer.get_emoji_set() != p['emojiSet']:
                self._emoji_renderer.set_emoji_set(p['emojiSet'])
            content = json.dumps(data)
            if not self._ensure_canvas_prepared(content):
                raise RuntimeError('OpenStrandStudio could not prepare the strand layers')
            b = self._prepared_bounds
            if b.width() * b.height() * p['scale'] ** 2 > 36_000_000:
                raise ValueError('Image is too large at this resolution. Choose a lower scale.')
            image = self._generate_image_in_memory(content, p['scale'])
            if image is None or image.isNull():
                raise RuntimeError('OpenStrandStudio rendering failed')
            output = QBuffer()
            output.open(QIODevice.WriteOnly)
            if not image.save(output, 'PNG'):
                raise RuntimeError('PNG encoding failed')
            png = bytes(output.data())
            strands = self._main_window.canvas.strands
            return {'png': base64.b64encode(png).decode('ascii'), 'document': data,
                    'width': image.width(), 'height': image.height(),
                    'strands': len([s for s in strands if type(s).__name__ != 'MaskedStrand']),
                    'crossings': len([s for s in strands if type(s).__name__ == 'MaskedStrand']),
                    'bounds': {'x': b.x(), 'y': b.y(), 'width': b.width(), 'height': b.height()},
                    'renderer': 'OpenStrandStudio / MxN RenderMixin', 'settings': p}
