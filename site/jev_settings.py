"""The Jev (TypeSafe) key used by guided alignment, held by the local renderer.

The browser sends the key once; it is kept in this process and, only when
"remember" is on, in a file readable by the current user alone. The key is
never sent back to the browser — status only reports its last four characters.
"""
import json
import os
import threading
from pathlib import Path

CONFIG_PATH = Path(os.environ.get('MXN_JEV_CONFIG') or Path.home() / '.mxn' / 'jev.json')
MAX_KEY_LENGTH = 512


class JevSettings:
    def __init__(self, path=CONFIG_PATH):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.key = ''
        self.enabled = False
        self.remember = False
        try:
            saved = json.loads(self.path.read_text())
            self.key = str(saved.get('api_key', '')).strip()
            self.enabled = bool(saved.get('enabled')) and bool(self.key)
            self.remember = bool(self.key)
        except (OSError, ValueError, AttributeError):
            pass

    def _active_key(self):
        return self.key or os.environ.get('TYPESAFE_API_KEY', '').strip()

    def status(self):
        with self.lock:
            key = self._active_key()
            source = 'saved' if self.key and self.remember else 'session' if self.key else 'environment' if key else None
            try:
                import typesafe_sdk  # noqa: F401
                sdk = True
            except ImportError:
                sdk = False
            return {'configured': bool(key), 'source': source, 'hint': key[-4:] if len(key) >= 8 else '',
                    'enabled': self.enabled and bool(key), 'remember': self.remember, 'sdk': sdk}

    def update(self, request):
        if not isinstance(request, dict) or set(request) - {'apiKey', 'enabled', 'remember', 'forget'}:
            raise ValueError('Invalid Jev settings')
        with self.lock:
            if request.get('forget'):
                self.key, self.enabled, self.remember = '', False, False
            if 'apiKey' in request:
                key = request['apiKey']
                if not isinstance(key, str) or len(key) > MAX_KEY_LENGTH or any(c.isspace() for c in key.strip()):
                    raise ValueError('That does not look like a Jev API key')
                self.key = key.strip()
            for name in ('enabled', 'remember'):
                if name in request:
                    if not isinstance(request[name], bool):
                        raise ValueError(f'{name} must be true or false')
                    setattr(self, name, request[name])
            self._persist()
        return self.status()

    def _persist(self):
        if not (self.remember and self.key):
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix('.tmp')
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as handle:
            json.dump({'api_key': self.key, 'enabled': self.enabled}, handle)
        os.replace(tmp, self.path)

    def policy(self):
        """A fresh Jev policy when Jev is on and a key is available, else None (exhaustive search)."""
        with self.lock:
            key = self._active_key()
            if not (self.enabled and key):
                return None
        try:
            from mxn_guided_search import JevPolicy
            return JevPolicy(api_key=key)
        except Exception as error:
            print(f'Jev unavailable ({error}); using exhaustive search.', flush=True)
            return None
