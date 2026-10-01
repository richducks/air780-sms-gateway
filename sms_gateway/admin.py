"""Local username/password sessions plus scoped machine API keys."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import threading
import time
import uuid

from .store import utc_now


class AdminAccess:
    SESSION_TTL = 8 * 3600

    def __init__(self, store, password: str):
        self.store = store
        self.bootstrap_password = password
        self.sessions: dict[str, tuple[float, str]] = {}
        self.lock = threading.Lock()
        with store._connection() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS api_keys (
                id TEXT PRIMARY KEY, label TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE,
                scope TEXT NOT NULL, created_at TEXT NOT NULL)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('admin','user')),
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL)""")
        self._ensure_admin()

    @staticmethod
    def digest(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    @staticmethod
    def _hash_password(password: str) -> str:
        salt = secrets.token_bytes(16)
        rounds = 400_000
        digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, rounds)
        return f'pbkdf2_sha256${rounds}${salt.hex()}${digest.hex()}'

    @staticmethod
    def _verify_hash(password: str, record: str) -> bool:
        try:
            scheme, iterations, salt, expected = record.split('$')
            if scheme != 'pbkdf2_sha256':
                return False
            actual = hashlib.pbkdf2_hmac('sha256', password.encode(),
                                         bytes.fromhex(salt), int(iterations))
            return hmac.compare_digest(actual, bytes.fromhex(expected))
        except (ValueError, OverflowError):
            return False

    @staticmethod
    def _validate_username(username: str) -> str:
        username = username.strip()
        if not re.fullmatch(r'[A-Za-z0-9_.-]{3,32}', username):
            raise ValueError('用户名须为 3–32 位字母、数字、点、下划线或连字符')
        return username

    @staticmethod
    def _validate_new_password(password: str) -> str:
        if not 8 <= len(password) <= 128:
            raise ValueError('密码须为 8–128 个字符')
        return password

    def _ensure_admin(self) -> None:
        with self.store._lock, self.store._connection() as conn:
            if conn.execute("SELECT 1 FROM users WHERE username='admin'").fetchone():
                return
            legacy = self.store.get_setting('admin_password_hash')
            if legacy and legacy.startswith('pbkdf2_sha256$'):
                password_hash = legacy
            else:
                password_hash = self._hash_password(self.bootstrap_password or 'admin')
            now = utc_now()
            conn.execute('INSERT INTO users(username,password_hash,role,enabled,created_at,updated_at) '
                         'VALUES(?,?,?,?,?,?)', ('admin', password_hash, 'admin', 1, now, now))

    def login(self, username: str, password: str) -> str | None:
        username = username.strip()
        with self.store._connection() as conn:
            row = conn.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
        if not row or not row['enabled'] or not self._verify_hash(password, row['password_hash']):
            return None
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self.lock:
            self.sessions = {k: v for k, v in self.sessions.items() if v[0] > now}
            self.sessions[token] = (now + self.SESSION_TTL, username)
        return token

    def logout(self, token: str) -> None:
        with self.lock:
            self.sessions.pop(token, None)

    def session_user(self, token: str) -> dict | None:
        if not token:
            return None
        with self.lock:
            session = self.sessions.get(token)
            if not session or session[0] <= time.time():
                self.sessions.pop(token, None)
                return None
            username = session[1]
        with self.store._connection() as conn:
            row = conn.execute('SELECT username,role,enabled,created_at,updated_at FROM users WHERE username=?',
                               (username,)).fetchone()
        if not row or not row['enabled']:
            self.logout(token)
            return None
        return dict(row)

    def is_admin(self, token: str) -> bool:
        user = self.session_user(token)
        return bool(user and user['role'] == 'admin')

    def change_own_password(self, token: str, current: str, new: str) -> None:
        user = self.session_user(token)
        if not user:
            raise PermissionError('登录已失效')
        self._validate_new_password(new)
        with self.store._lock, self.store._connection() as conn:
            row = conn.execute('SELECT password_hash FROM users WHERE username=?',
                               (user['username'],)).fetchone()
            if not row or not self._verify_hash(current, row['password_hash']):
                raise PermissionError('当前密码不正确')
            if self._verify_hash(new, row['password_hash']):
                raise ValueError('新密码不能与当前密码相同')
            conn.execute('UPDATE users SET password_hash=?,updated_at=? WHERE username=?',
                         (self._hash_password(new), utc_now(), user['username']))
        self._drop_user_sessions(user['username'])

    def change_password(self, current: str, new: str) -> None:
        """Legacy admin password helper kept for compatibility with older callers/tests."""
        with self.store._connection() as conn:
            row = conn.execute("SELECT password_hash FROM users WHERE username='admin'").fetchone()
        if not row or not self._verify_hash(current, row['password_hash']):
            raise PermissionError('当前密码不正确')
        self._validate_new_password(new)
        with self.store._lock, self.store._connection() as conn:
            conn.execute("UPDATE users SET password_hash=?,updated_at=? WHERE username='admin'",
                         (self._hash_password(new), utc_now()))
        self._drop_user_sessions('admin')

    def _drop_user_sessions(self, username: str) -> None:
        with self.lock:
            self.sessions = {token: value for token, value in self.sessions.items()
                             if value[1] != username}

    def list_users(self) -> list[dict]:
        with self.store._connection() as conn:
            rows = conn.execute('SELECT username,role,enabled,created_at,updated_at FROM users '
                                'ORDER BY CASE role WHEN "admin" THEN 0 ELSE 1 END, username').fetchall()
        return [dict(row) for row in rows]

    def create_user(self, username: str, password: str) -> dict:
        username = self._validate_username(username)
        self._validate_new_password(password)
        now = utc_now()
        try:
            with self.store._lock, self.store._connection() as conn:
                conn.execute('INSERT INTO users(username,password_hash,role,enabled,created_at,updated_at) '
                             'VALUES(?,?,?,?,?,?)',
                             (username, self._hash_password(password), 'user', 1, now, now))
        except Exception as exc:
            if 'UNIQUE constraint failed' in str(exc):
                raise ValueError('用户名已存在') from exc
            raise
        return next(item for item in self.list_users() if item['username'] == username)

    def update_user(self, username: str, enabled: bool) -> dict:
        username = self._validate_username(username)
        if username == 'admin' and not enabled:
            raise ValueError('不能禁用内置管理员')
        with self.store._lock, self.store._connection() as conn:
            cur = conn.execute('UPDATE users SET enabled=?,updated_at=? WHERE username=?',
                               (int(enabled), utc_now(), username))
        if not cur.rowcount:
            raise KeyError(username)
        if not enabled:
            self._drop_user_sessions(username)
        return next(item for item in self.list_users() if item['username'] == username)

    def reset_user_password(self, username: str, password: str) -> None:
        username = self._validate_username(username)
        self._validate_new_password(password)
        with self.store._lock, self.store._connection() as conn:
            cur = conn.execute('UPDATE users SET password_hash=?,updated_at=? WHERE username=?',
                               (self._hash_password(password), utc_now(), username))
        if not cur.rowcount:
            raise KeyError(username)
        self._drop_user_sessions(username)

    def delete_user(self, username: str) -> bool:
        username = self._validate_username(username)
        if username == 'admin':
            raise ValueError('不能删除内置管理员')
        with self.store._lock, self.store._connection() as conn:
            deleted = conn.execute('DELETE FROM users WHERE username=?', (username,)).rowcount > 0
        if deleted:
            self._drop_user_sessions(username)
        return deleted

    def scope(self, token: str) -> str | None:
        with self.store._connection() as conn:
            row = conn.execute('SELECT scope FROM api_keys WHERE token_hash=?', (self.digest(token),)).fetchone()
        return row['scope'] if row else None

    def list(self) -> list[dict]:
        with self.store._connection() as conn:
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
        with self.store._lock, self.store._connection() as conn:
            conn.execute('INSERT INTO api_keys VALUES (?,?,?,?,?)',
                         (key_id, label, self.digest(token), scope, utc_now()))
        return next(item for item in self.list() if item['id'] == key_id), token

    def update(self, key_id: str, label: str) -> bool:
        label = label.strip()
        if not label or len(label) > 80:
            raise ValueError('备注须为 1–80 个字符')
        with self.store._lock, self.store._connection() as conn:
            return conn.execute('UPDATE api_keys SET label=? WHERE id=?', (label, key_id)).rowcount > 0

    def delete(self, key_id: str) -> bool:
        with self.store._lock, self.store._connection() as conn:
            return conn.execute('DELETE FROM api_keys WHERE id=?', (key_id,)).rowcount > 0
