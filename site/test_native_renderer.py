"""Regression checks for native rendering and independent PNG marker toggles."""
import base64
import contextlib
import io
import json
import unittest
from unittest.mock import patch
from PyQt5.QtGui import QImage
from native_renderer import NativeRenderer, validate


class NativeRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.renderer = NativeRenderer()
        cls.base = dict(m=2, n=2, k=0, hand='lh', stretch=False,
                        continuation=False, animals=False, names=False,
                        transparent=True, scale=1, emojiSet='fluent',
                        colors=['#db9279', '#458b88', '#efc56f', '#596d9c'])

    @classmethod
    def tearDownClass(cls):
        from PyQt5 import sip
        # Dispose widgets while QApplication and their Python callbacks still
        # exist, rather than relying on interpreter shutdown ordering on Windows.
        for widget in cls.renderer.app.topLevelWidgets():
            if not sip.isdeleted(widget):
                sip.delete(widget)
        cls.renderer._main_window = None
        cls.renderer.app.processEvents()
        sip.delete(cls.renderer.app)

    def test_animals_change_overlay_not_strand_document(self):
        off = self.renderer.render(self.base)
        on = self.renderer.render({**self.base, 'animals': True})
        self.assertEqual(off['document'], on['document'])
        a = QImage.fromData(base64.b64decode(off['png']))
        b = QImage.fromData(base64.b64decode(on['png']))
        self.assertEqual(a.size(), b.size())
        self.assertNotEqual(a, b)
        # Animals and rotation indicator live in the padding, not the weave.
        crop = (110, 110, a.width()-220, a.height()-220)
        self.assertEqual(a.copy(*crop), b.copy(*crop))

    def test_continuation_workflow_preserves_source_and_applies_extensions(self):
        from workflow import Workflow
        from ui_utils import _get_active_strands
        workflow = Workflow(self.renderer)
        start = workflow.start({**self.base, 'k': 1})
        before = json.dumps(start['document'], sort_keys=True)
        continuation = workflow.run(dict(action='continue', snapshot=start['snapshot']))
        self.assertEqual(continuation['settings']['colors'], start['settings']['colors'])
        self.assertEqual(continuation['settings']['k'], 1)
        self.assertTrue(continuation['preparedStretch'])
        self.assertTrue(continuation['pairs'])
        pair = continuation['pairs'][0]
        extended = workflow.run(dict(action='extend', snapshot=continuation['snapshot'],
                                    options={'extensions': {pair['key']: 20}}))
        old = {s['layer_name']: s for s in _get_active_strands(continuation['document'])}
        new = {s['layer_name']: s for s in _get_active_strands(extended['document'])}
        label = pair['labels'][0]
        self.assertNotEqual(old[label]['end'], new[label]['end'])
        self.assertEqual(before, json.dumps(workflow.snapshots[start['snapshot']]['document'], sort_keys=True))
        displayed = workflow.run(dict(action='display', snapshot=extended['snapshot'], options={'animals': True}))
        self.assertEqual(extended['document'], displayed['document'])
        with self.assertRaises(ValueError):
            workflow.run(dict(action='align', snapshot=continuation['snapshot'],options={'mode':'custom','hMin':40,'hMax':0}))

    def test_workflow_alignment_matches_original_solver(self):
        from workflow import Workflow
        from ui_utils import _get_active_strands
        import mxn_lh_continuation as original
        workflow = Workflow(self.renderer)
        start = workflow.start({**self.base, 'm':1, 'n':1, 'colors':self.base['colors'][:2], 'k':0})
        continuation = workflow.run(dict(action='continue', snapshot=start['snapshot']))
        aligned = workflow.run(dict(action='align', snapshot=continuation['snapshot'], options={'maximum':0,'step':10}))
        strands = json.loads(json.dumps(_get_active_strands(continuation['document'])))
        with contextlib.redirect_stdout(io.StringIO()):
            h = original.align_horizontal_strands_parallel(strands,1,m=1,k=0,direction='cw',max_pair_extension=0,pair_extension_step=10,use_gpu=False)
            if h.get('success') or h.get('is_fallback'):
                strands = original.apply_parallel_alignment(strands,h)
            v = original.align_vertical_strands_parallel(strands,1,1,k=0,direction='cw',max_pair_extension=0,pair_extension_step=10,use_gpu=False)
            if v.get('success') or v.get('is_fallback'):
                strands = original.apply_parallel_alignment(strands,v)
        self.assertEqual(strands,_get_active_strands(aligned['document']))
        self.assertEqual(len(aligned['alignment']),2)

    def test_all_generator_variants_use_native_classes(self):
        for hand in ['lh', 'rh']:
            for stretch, continuation in [(False, False), (True, False), (True, True)]:
                with self.subTest(hand=hand, stretch=stretch, continuation=continuation):
                    result = self.renderer.render({**self.base, 'hand': hand, 'stretch': stretch, 'continuation': continuation})
                    classes = {type(s).__name__ for s in self.renderer._main_window.canvas.strands}
                    self.assertTrue({'Strand', 'AttachedStrand', 'MaskedStrand'} <= classes)
                    self.assertGreater(result['width'], 0)
                    self.assertTrue(base64.b64decode(result['png']).startswith(b'\x89PNG'))

    def test_matches_desktop_dialog_render_pixels(self):
        from mxn_cad_ui import MxNGeneratorDialog
        from PyQt5.QtCore import QBuffer, QIODevice
        # The original dialog's QProxyStyle wrappers take shared application
        # styles into ownership and crash Qt teardown on Windows. Skip only
        # checkbox/radio cosmetics in this headless test, never render methods.
        with patch.object(MxNGeneratorDialog, '_initialize_toggle_checkboxes', lambda self: None), patch.object(MxNGeneratorDialog, '_initialize_radio_buttons', lambda self: None), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            dialog = MxNGeneratorDialog()
        for animals in [False, True]:
            result = self.renderer.render({**self.base, 'animals': animals, 'names': True})
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                # Match the web request while avoiding user settings writes.
                dialog.save_color_settings = lambda: None
                for control, value in [(dialog.m_spinner,2),(dialog.n_spinner,2),(dialog.emoji_k_spinner,0)]:
                    control.blockSignals(True)
                    control.setValue(value)
                for control, checked in [(dialog.show_emojis_checkbox,animals),(dialog.show_strand_names_checkbox,True),(dialog.emoji_cw_radio,True),(dialog.transparent_checkbox,True)]:
                    control.blockSignals(True)
                    control.setChecked(checked)
                dialog._emoji_renderer.set_emoji_set('fluent')
                image = dialog._generate_image_in_memory(json.dumps(result['document']), 1)
                output = QBuffer()
                output.open(QIODevice.WriteOnly)
                self.assertTrue(image.save(output, 'PNG'))
                self.assertEqual(bytes(output.data()), base64.b64decode(result['png']))
        dialog.close()

    def test_invalid_requests_rejected(self):
        for change in [dict(m=0), dict(n=11), dict(m=2.5), dict(colors=['oops']), dict(emojiSet='../'), dict(scale=20),dict(continuation=True,stretch=False)]:
            with self.assertRaises(ValueError):
                validate({**self.base, **change})

    def test_rotation_digits_and_arrow_direction(self):
        from PyQt5.QtCore import QRectF, Qt
        from PyQt5.QtGui import QPainter

        def indicator(k, direction):
            image = QImage(160, 160, QImage.Format_ARGB32_Premultiplied)
            image.fill(Qt.transparent)
            painter = QPainter(image)
            painter.setRenderHint(QPainter.Antialiasing)
            self.renderer._emoji_renderer.draw_rotation_indicator(
                painter, QRectF(0, 0, 160, 160),
                dict(show=True, k=k, direction=direction, transparent=True))
            painter.end()
            return image

        # Same-length strings previously produced identical missing-glyph boxes.
        self.assertNotEqual(indicator(12, 'cw'), indicator(21, 'cw'))
        self.assertNotEqual(indicator(1, 'cw'), indicator(-1, 'cw'))
        clockwise, counterclockwise = indicator(1, 'cw'), indicator(1, 'ccw')
        self.assertNotEqual(clockwise, counterclockwise)
        # Mirroring the arrow must not mirror the number inside it.
        self.assertEqual(clockwise.copy(75, 57, 34, 22), counterclockwise.copy(75, 57, 34, 22))

    def test_signed_k_settings_and_endpoint_shift(self):
        labels = ['A', 'B', 'C', 'D']
        rotate = self.renderer._emoji_renderer.rotate_labels
        self.assertEqual(rotate(labels, 1, 'cw'), ['D', 'A', 'B', 'C'])
        self.assertEqual(rotate(labels, 1, 'ccw'), ['B', 'C', 'D', 'A'])
        self.assertEqual(rotate(labels, -1, 'cw'), rotate(labels, 1, 'ccw'))
        for hand, direction in [('lh', 'cw'), ('rh', 'ccw')]:
            for k in [-2, 3]:
                self.renderer.render({**self.base, 'hand': hand, 'k': k, 'animals': True})
                options = self.renderer._build_emoji_settings()
                self.assertEqual(options['k'], k)
                self.assertEqual(options['direction'], direction)


if __name__ == '__main__':
    unittest.main()
