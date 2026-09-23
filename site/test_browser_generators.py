"""The browser generators (dist/generators.js) must match the Python ones exactly.

Run: python -m unittest test_browser_generators -v (from this directory). Needs node.
"""
import importlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'src'))
MODULES = {('lh', 'standard'): 'mxn_lh', ('rh', 'standard'): 'mxn_rh',
           ('lh', 'stretch'): 'mxn_lh_strech', ('rh', 'stretch'): 'mxn_rh_stretch'}


def without_colors(document):
    """Sets 3+ get random colors in Python; the site repaints every set anyway."""
    for state in document['states']:
        for strand in state['data']['strands']:
            strand.pop('color')
    return document


@unittest.skipUnless(shutil.which('node'), 'node is not installed')
class BrowserGeneratorParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        output = subprocess.run(['node', str(HERE / 'tools' / 'dump_generators.mjs')],
                                check=True, capture_output=True, text=True).stdout
        cls.browser = json.loads(output)

    def test_every_size_and_variant_matches(self):
        for (hand, variant), name in MODULES.items():
            generate = importlib.import_module(name).generate_json
            for m in range(1, 11):
                for n in range(1, 11):
                    with self.subTest(hand=hand, variant=variant, m=m, n=n):
                        expected = without_colors(json.loads(generate(m, n)))
                        actual = without_colors(self.browser[f'{hand}/{variant}/{m}/{n}'])
                        self.assertEqual(actual, expected)


if __name__ == '__main__':
    unittest.main()
