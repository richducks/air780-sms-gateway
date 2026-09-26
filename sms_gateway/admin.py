"""Small local admin session and scoped API key registry."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
import uuid

from .store import utc_now


class AdminAccess:
    def __init__(self, store, password: str):
        self.store = store
        self.password = password
        self.sessions: dict[str, float] = {}
        self.lock = threading.Lock()
        with store._connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS api_keys (
                id TEXT PRIMARY KEY, label TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE,
                scope TEXT NOT NULL, created_at TEXT NOT NULL)""")

    @staticmethod
    def digest(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def _verify_password(self, password: str) -> bool:
        record = self.store.get_setting('admin_password_hash')
        if record:
            try:
                scheme, iterations, salt, expected = record.split('$')
                if scheme != 'pbkdf2_sha256':
                    return False
                actual = hashlib.pbkdf2_hmac('sha256', password.encode(),
                                             bytes.fromhex(salt), int(iterations))
                return hmac.compare_digest(actual, bytes.fromhex(expected))
            except (ValueError, OverflowError):
                return False
        return bool(self.password) and hmac.compare_digest(password, self.password)

    def change_password(self, current: str, new: str) -> None:
        if not self._verify_password(current):
            raise PermissionError('当前密码不正确')
        if not 12 <= len(new) <= 128:
            raise ValueError('新密码须为 12–128 个字符')
        if hmac.compare_digest(current, new):
            raise ValueError('新密码不能与当前密码相同')
        salt = secrets.token_bytes(16)
        rounds = 400_000
        digest = hashlib.pbkdf2_hmac('sha256', new.encode(), salt, rounds)
        self.store.set_setting('admin_password_hash',
                               f'pbkdf2_sha256${rounds}${salt.hex()}${digest.hex()}')
        with self.lock:
            self.sessions.clear()

    def login(self, username: str, password: str) -> str | None:
        if username != 'admin' or not self._verify_password(password):
            return None
        token = secrets.token_urlsafe(32)
        with self.lock:
            self.sessions = {k: v for k, v in self.sessions.items() if v > time.time()}
            self.sessions[token] = time.time() + 8 * 3600
        return token

    def is_admin(self, token: str) -> bool:
        with self.lock:
            expiry = self.sessions.get(token, 0)
            if expiry <= time.time():
                self.sessions.pop(token, None)
                return False
            return True

    def scope(self, token: str) -> str | None:
        with self.store._connect() as conn:
            row = conn.execute('SELECT scope FROM api_keys WHERE token_hash=?', (self.digest(token),)).fetchone()
        return row['scope'] if row else None

    def list(self) -> list[dict]:
        with self.store._connect() as conn:
            rows = conn.execute('SELECT id,label,scope,created_at FROM api_keys ORDER BY created_at DESC').fetchall()
        return [dict(row) for row in rows]

    def create(self, label: str, scope: str) -> tuple[dict, str]:
        label = label.strip()
        if not label or len(label) > 80:
            raise ValueError('备注须为 1–80 个字符')
        if scope not in ('read', 'write'):
            raise ValueError('权限无效')
        token = 'sms_' + secrets.token_urlsafe(32)
        key_id = uuid.uuid4().hex
        with self.store._lock, self.store._connect() as conn:
            conn.execute('INSERT INTO api_keys VALUES (?,?,?,?,?)',
                         (key_id, label, self.digest(token), scope, utc_now()))
        return next(item for item in self.list() if item['id'] == key_id), token

    def update(self, key_id: str, label: str) -> bool:
        label = label.strip()
        if not label or len(label) > 80:
            raise ValueError('备注须为 1–80 个字符')
        with self.store._lock, self.store._connect() as conn:
            return conn.execute('UPDATE api_keys SET label=? WHERE id=?', (label, key_id)).rowcount > 0

    def delete(self, key_id: str) -> bool:
        with self.store._lock, self.store._connect() as conn:
            return conn.execute('DELETE FROM api_keys WHERE id=?', (key_id,)).rowcount > 0
