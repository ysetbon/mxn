import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from jev_settings import JevSettings
from workflow import search_report


class JevSettingsTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / 'mxn' / 'jev.json'
        env = mock.patch.dict(os.environ, {}, clear=False)
        env.start()
        os.environ.pop('TYPESAFE_API_KEY', None)
        self.addCleanup(env.stop)
        self.addCleanup(self.dir.cleanup)

    def test_session_key_is_not_written_or_returned(self):
        jev = JevSettings(self.path)
        status = jev.update({'apiKey': ' ts_secret_abcd1234 ', 'enabled': True})
        self.assertEqual((status['source'], status['hint'], status['enabled']), ('session', '1234', True))
        self.assertNotIn('ts_secret', json.dumps(status))
        self.assertFalse(self.path.exists())
        self.assertFalse(JevSettings(self.path).status()['configured'])

    def test_remember_saves_privately_and_forget_deletes(self):
        jev = JevSettings(self.path)
        jev.update({'apiKey': 'ts_secret_abcd1234', 'enabled': True, 'remember': True})
        self.assertEqual(json.loads(self.path.read_text())['api_key'], 'ts_secret_abcd1234')
        if os.name == 'posix':
            self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        again = JevSettings(self.path).status()
        self.assertEqual((again['source'], again['enabled'], again['remember']), ('saved', True, True))
        jev.update({'remember': False})
        self.assertFalse(self.path.exists())
        self.assertEqual(jev.status()['source'], 'session')
        jev.update({'remember': True})
        jev.update({'forget': True})
        self.assertFalse(self.path.exists())
        self.assertFalse(jev.status()['configured'])

    def test_environment_key_and_policy(self):
        jev = JevSettings(self.path)
        self.assertIsNone(jev.policy())
        os.environ['TYPESAFE_API_KEY'] = 'env_key_wxyz9876'
        self.assertEqual(jev.status()['source'], 'environment')
        self.assertIsNone(jev.policy())  # off until enabled
        jev.update({'enabled': True})
        with mock.patch('mxn_guided_search.JevPolicy') as policy:
            jev.policy()
        policy.assert_called_once_with(api_key='env_key_wxyz9876')

    def test_rejects_bad_requests(self):
        jev = JevSettings(self.path)
        for request in ({'apiKey': 'has space'}, {'apiKey': 5}, {'enabled': 'yes'}, {'other': 1}, [], {'apiKey': 'x' * 600}):
            with self.assertRaises(ValueError):
                jev.update(request)

    def test_search_report(self):
        self.assertEqual(search_report(None)['mode'], 'exhaustive')
        guided = search_report({'mode': 'guided', 'policy': 'jev', 'policy_calls': 3, 'policy_input_tokens': 900,
                                'combos_evaluated': 40, 'combos_total': 400})
        self.assertEqual((guided['calls'], guided['inputTokens'], guided['evaluated']), (3, 900, 40))
        fallback = search_report({'mode': 'exhaustive', 'guided_attempt': {'policy': 'jev', 'policy_calls': 2}})
        self.assertEqual((fallback['mode'], fallback['policy'], fallback['calls']), ('exhaustive', 'jev', 2))


if __name__ == '__main__':
    unittest.main()
