"""The browser continuation engine (dist/continuation-engine.js) must match Python.

Covers generate_json documents, the k orders/pairs, the alignment preview ranges
and the Workflow.run continuation actions including the exhaustive CPU alignment
search. Run: python -m unittest test_browser_continuation -v (from this
directory). Needs node and numpy; MXN_PARITY_TIMING=1 prints Python vs JS times,
MXN_PARITY_FULL=1 runs the full 1x1..3x3 alignment sweep.
"""
import contextlib
import importlib
import io
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import types
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'src'))
sys.path.insert(0, str(HERE))
for name in ('MXN_ALIGNMENT_CLEARANCE', 'MXN_ALIGNMENT_GUIDED', 'MXN_ALIGNMENT_MAX_CPU_COMBOS'):
    os.environ.pop(name, None)

try:
    import numpy  # noqa: F401  (the alignment search needs it)
except ImportError:
    numpy = None

HANDS = {'lh': 'cw', 'rh': 'ccw'}


def doc_cases():
    cases = []
    for m in range(1, 7):
        for n in range(1, 7):
            for k in sorted({-9, -2, -1, 0, 1, 2, 3, m + n, 4 * (m + n) + 3}):
                cases += [[m, n, k, hand] for hand in HANDS]
    for m, n, k in [(7, 3, 10), (10, 10, -1), (8, 9, 4), (3, 10, 13), (10, 1, 11)]:
        cases += [[m, n, k, hand] for hand in HANDS]
    return cases


def flow_cases(full=bool(os.environ.get('MXN_PARITY_FULL'))):
    """Every 1x1..3x3 at k -2..2 with MXN_PARITY_FULL=1 (~8 min of Python search), else a quicker spread."""
    cases = []
    sizes = [(m, n) for m in range(1, 4) for n in range(1, 4)] if full else [(1, 1), (1, 2), (2, 1), (2, 2)]
    for m, n in sizes:
        for k in (-2, -1, 0, 1, 2):
            cases += [dict(m=m, n=n, k=k, hand=hand, action='align', options={}) for hand in HANDS]
    if not full:
        # Three passes of the clearance re-check, a fallback, and a 3x3 search.
        cases += [dict(m=3, n=2, k=2, hand='lh', action='align', options={}),
                  dict(m=1, n=3, k=2, hand='rh', action='align', options={}),
                  dict(m=3, n=3, k=1, hand='rh', action='align', options={})]
    custom = dict(mode='custom', hMin=-170, hMax=-150, vMin=100, vMax=120, maximum=100, step=20)
    cases += [dict(m=2, n=2, k=1, hand='lh', action='align', options=custom),
              dict(m=2, n=3, k=-1, hand='rh', action='align', options=dict(mode='avg_gaussian')),
              dict(m=2, n=2, k=2, hand='rh', action='align', options=dict(extensions={'4_3|3_2': 24, '1_2|2_3': -12})),
              dict(m=3, n=2, k=1, hand='lh', action='preview', options=dict(mode='avg_gaussian', extensions={'3_2|5_3': 40, '1_3|2_2': -8.5})),
              dict(m=2, n=3, k=4, hand='lh', action='extend', options=dict(mode='custom', hMin=5, hMax=9, extensions={}))]
    return cases


def strip_colors(strands):
    return [{key: value for key, value in s.items() if key != 'color'} for s in strands]


def compact(doc):
    strands = doc['states'][0]['data']['strands']
    states = [{'step': st['step'], 'data': {k: v for k, v in st['data'].items() if k != 'strands'}} for st in doc['states']]
    for st in doc['states']:
        assert st['data']['strands'] == strands
    return dict(doc, strands=strip_colors(strands), states=states)


class FakeRenderer:
    """Stands in for NativeRenderer: returns the document without drawing it."""

    def __init__(self):
        self._emoji_renderer = types.SimpleNamespace(clear_cache=lambda: None, _frozen_endpoint_emojis=None,
                                                     freeze_emoji_assignments=lambda *a: None)
        self._main_window = types.SimpleNamespace(canvas=None)
        self._prepared_bounds = None

    def render(self, p, document=None):
        p = dict(p)
        if document is None:
            with contextlib.redirect_stdout(io.StringIO()):
                module = importlib.import_module('mxn_' + p['hand'] + '_continuation')
                document = json.loads(module.generate_json(p['m'], p['n'], p['k'], HANDS[p['hand']]))
        return {'document': json.loads(json.dumps(document)), 'settings': p}


def close(test, actual, expected, path, tol=1e-6):
    """Deep compare with a float tolerance; `path` names the location on failure."""
    if isinstance(expected, dict):
        test.assertIsInstance(actual, dict, path)
        test.assertEqual(sorted(actual), sorted(expected), path)
        for key in expected:
            close(test, actual[key], expected[key], f'{path}.{key}', tol)
    elif isinstance(expected, (list, tuple)):
        test.assertEqual(len(actual), len(expected), path)
        for i, (a, e) in enumerate(zip(actual, expected)):
            close(test, a, e, f'{path}[{i}]', tol)
    elif isinstance(expected, float) and not isinstance(expected, bool):
        test.assertIsInstance(actual, (int, float), path)
        if math.isinf(expected):
            test.assertEqual(actual, expected, path)
        else:
            test.assertLessEqual(abs(actual - expected), tol, f'{path}: {actual} vs {expected}')
    else:
        test.assertEqual(actual, expected, path)


@unittest.skipUnless(shutil.which('node'), 'node is not installed')
@unittest.skipUnless(numpy, 'numpy is not installed')
class BrowserContinuationParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs, cls.flows = doc_cases(), flow_cases()
        run = subprocess.run(['node', str(HERE / 'tools' / 'dump_continuation.mjs')],
                             input=json.dumps({'docs': cls.docs, 'flows': cls.flows}), capture_output=True, text=True)
        if run.returncode:
            raise RuntimeError(run.stderr)
        cls.browser = json.loads(run.stdout)

    def test_documents_orders_and_previews(self):
        from workflow import Workflow
        for (m, n, k, hand), actual in zip(self.docs, self.browser['docs']):
            with self.subTest(m=m, n=n, k=k, hand=hand):
                module = importlib.import_module(f'mxn_{hand}_continuation')
                with contextlib.redirect_stdout(io.StringIO()):
                    doc = json.loads(module.generate_json(m, n, k, HANDS[hand]))
                    expected_pairs = Workflow.pairs(dict(m=m, n=n, k=k), module, HANDS[hand])
                    previews = {mode: module.get_parallel_alignment_preview(
                        doc['states'][-1]['data']['strands'], n, m, k=k, direction=HANDS[hand], angle_mode=mode)
                        for mode in ('first_strand', 'avg_gaussian')}
                self.assertEqual(dict(actual['document'], strands=strip_colors(actual['document']['strands'])), compact(doc))
                self.assertEqual(actual['pairs'], expected_pairs)
                close(self, actual['previews'], previews, 'previews', 1e-9)

    def test_workflow_actions(self):
        from workflow import Workflow
        timing = []
        for case, actual in zip(self.flows, self.browser['flows']):
            with self.subTest(**{k: v for k, v in case.items() if k != 'options'}, options=json.dumps(case['options'])):
                workflow = Workflow(FakeRenderer())
                settings = dict(m=case['m'], n=case['n'], k=case['k'], hand=case['hand'], stretch=True, continuation=False)
                base = workflow.run({'snapshot': workflow.start(settings)['snapshot'], 'action': 'continue'})
                started = time.perf_counter()
                expected = workflow.run({'snapshot': base['snapshot'], 'action': case['action'], 'options': case['options']})
                timing.append((case, time.perf_counter() - started, actual['seconds']))
                reports = actual['alignment']
                self.assertEqual(len(reports), len(expected['alignment']))
                for a, e in zip(reports, expected['alignment']):
                    self.assertEqual({k: a[k] for k in ('axis', 'success', 'fallback', 'message', 'passes', 'search')},
                                     {k: e[k] for k in ('axis', 'success', 'fallback', 'message', 'passes', 'search')})
                    close(self, a['angle'], e['angle'], 'angle', 1e-9)
                    close(self, a['gap'], e['gap'], 'gap')
                self.assertEqual(actual['pairs'], expected['pairs'])
                close(self, actual['ranges'], expected['ranges'], 'ranges', 1e-9)
                close(self, strip_colors(actual['strands']), strip_colors(expected['document']['states'][-1]['data']['strands']), 'strands')
        if os.environ.get('MXN_PARITY_TIMING'):
            python, js = sum(t[1] for t in timing), sum(t[2] for t in timing)
            print(f'\nPython {python:.2f}s vs JS {js:.2f}s over {len(timing)} workflow actions')
            for case, p, j in sorted(timing, key=lambda t: -t[1])[:8]:
                print(f"  {case['m']}x{case['n']} k={case['k']} {case['hand']} {case['action']}: Python {p:.2f}s, JS {j:.3f}s")


if __name__ == '__main__':
    unittest.main()
