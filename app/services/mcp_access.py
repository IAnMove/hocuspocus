"""Private installation-level MCP switch. Environment credentials retain precedence."""
from __future__ import annotations

import json
import os
import secrets
import threading
from pathlib import Path


class McpAccess:
    def __init__(self, path, env_token=None):
        self.path = Path(path)
        self.env_token = env_token or (lambda: os.environ.get('HOCUS_MCP_TOKEN', '').strip())
        self.lock = threading.RLock()

    def _read(self):
        if not self.path.exists():
            return {}
        with self.path.open(encoding='utf-8') as handle:
            value = json.load(handle)
        if not isinstance(value, dict) or type(value.get('enabled')) is not bool:
            raise ValueError('Invalid MCP access settings')
        return value

    def token(self):
        with self.lock:
            config = self._read()
            if config.get('enabled') is False:
                return ''
            return self.env_token() or (config.get('token', '') if config.get('enabled') else '')

    def status(self):
        with self.lock:
            environment = bool(self.env_token())
            return {'enabled': bool(self.token()), 'managedByEnvironment': environment,
                    'endpoint': '/api/v1/mcp', 'transport': 'streamable-http',
                    'authentication': 'Bearer', 'protocolVersion': '2025-03-26'}

    def update(self, enabled: bool, rotate: bool = False):
        with self.lock:
            config = self._read()
            environment = bool(self.env_token())
            if rotate and environment:
                raise ValueError('HOCUS_MCP_TOKEN is managed by the environment; change it there.')
            token = config.get('token', '')
            issued = enabled and not environment and (rotate or not token)
            if issued:
                token = secrets.token_urlsafe(32)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(f'.{self.path.name}.{secrets.token_hex(6)}.tmp')
            try:
                with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as handle:
                    json.dump({'enabled': enabled, 'token': token}, handle)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, self.path)
            finally:
                temporary.unlink(missing_ok=True)
            result = self.status()
            if issued:
                result['token'] = token  # Only returned at issuance; never in status or logs.
            return result
