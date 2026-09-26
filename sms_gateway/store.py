from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class MessageStore:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    direction TEXT NOT NULL CHECK(direction IN ('inbound','outbound')),
                    phone TEXT NOT NULL,
                    body TEXT NOT NULL,
                    status TEXT NOT NULL,
                    modem_index INTEGER,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    device_id TEXT,
                    UNIQUE(device_id, direction, modem_index)
                )
            """)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(messages)")}
            if "device_id" not in columns:
                conn.execute("ALTER TABLE messages ADD COLUMN device_id TEXT")
            schema = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='messages'"
            ).fetchone()[0]
            if "unique(direction,modem_index)" in schema.lower().replace(" ", "").replace("\n", ""):
                conn.execute("ALTER TABLE messages RENAME TO messages_legacy")
                conn.execute("""
                    CREATE TABLE messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        direction TEXT NOT NULL CHECK(direction IN ('inbound','outbound')),
                        phone TEXT NOT NULL, body TEXT NOT NULL, status TEXT NOT NULL,
                        modem_index INTEGER, error TEXT, created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL, device_id TEXT,
                        UNIQUE(device_id, direction, modem_index)
                    )
                """)
                conn.execute("""
                    INSERT INTO messages(id,direction,phone,body,status,modem_index,error,
                                         created_at,updated_at,device_id)
                    SELECT id,direction,phone,body,status,modem_index,error,
                           created_at,updated_at,device_id FROM messages_legacy
                """)
                conn.execute("DROP TABLE messages_legacy")
            if "favorite" not in columns:
                conn.execute("ALTER TABLE messages ADD COLUMN favorite INTEGER NOT NULL DEFAULT 0")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS devices (
                    device_id TEXT PRIMARY KEY,
                    imei TEXT NOT NULL UNIQUE,
                    label TEXT,
                    firmware_version TEXT,
                    serial_port TEXT,
                    status TEXT NOT NULL,
                    last_error TEXT,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS contacts (
                    phone TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

    def create(self, direction: str, phone: str, body: str, status: str,
               modem_index: int | None = None, error: str | None = None,
               device_id: str | None = None) -> int:
        now = utc_now()
        with self._lock, self._connect() as conn:
            if modem_index is not None:
                existing = conn.execute(
                    "SELECT id FROM messages WHERE direction=? AND modem_index=? AND device_id IS ?",
                    (direction, modem_index, device_id),
                ).fetchone()
                if existing:
                    return int(existing["id"])
            cur = conn.execute(
                "INSERT OR IGNORE INTO messages(direction,phone,body,status,modem_index,error,created_at,updated_at,device_id) VALUES(?,?,?,?,?,?,?,?,?)",
                (direction, phone, body, status, modem_index, error, now, now, device_id),
            )
            if cur.lastrowid:
                return int(cur.lastrowid)
            row = conn.execute("SELECT id FROM messages WHERE direction=? AND modem_index=? "
                               "AND device_id IS ?", (direction, modem_index, device_id)).fetchone()
            return int(row["id"])

    def update(self, message_id: int, status: str, error: str | None = None) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE messages SET status=?,error=?,updated_at=? WHERE id=?",
                (status, error, utc_now(), message_id),
            )

    def set_favorite(self, message_id: int, favorite: bool) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            conn.execute("UPDATE messages SET favorite=? WHERE id=?", (int(favorite), message_id))
            row = conn.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
        return dict(row) if row else None

    def get(self, message_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
            return dict(row) if row else None

    def list(self, limit: int = 50, direction: str | None = None,
             device_id: str | None = None) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 500))
        where, values = [], []
        if direction:
            where.append("direction=?")
            values.append(direction)
        if device_id:
            where.append("device_id=?")
            values.append(device_id)
        sql = "SELECT * FROM messages"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id DESC LIMIT ?"
        values.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, values).fetchall()
        return [dict(row) for row in rows]

    def upsert_device(self, device_id: str, imei: str, status: str, serial_port: str | None,
                      firmware_version: str = "", error: str | None = None) -> None:
        now = utc_now()
        with self._lock, self._connect() as conn:
            conn.execute("""
                INSERT INTO devices(device_id,imei,firmware_version,serial_port,status,last_error,first_seen_at,last_seen_at)
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(device_id) DO UPDATE SET
                    imei=excluded.imei, firmware_version=excluded.firmware_version,
                    serial_port=excluded.serial_port, status=excluded.status,
                    last_error=excluded.last_error, last_seen_at=excluded.last_seen_at
            """, (device_id, imei, firmware_version, serial_port, status, error, now, now))

    def update_device_label(self, device_id: str, label: str) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute("UPDATE devices SET label=? WHERE device_id=?", (label, device_id))
            return cur.rowcount > 0

    def mark_all_devices_offline(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("UPDATE devices SET status='offline',serial_port=NULL "
                         "WHERE status='online'")

    def list_devices(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM devices ORDER BY first_seen_at").fetchall()
        return [dict(row) for row in rows]

    def list_contacts(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM contacts ORDER BY name COLLATE NOCASE, phone").fetchall()
        return [dict(row) for row in rows]

    def upsert_contact(self, phone: str, name: str, note: str = "") -> dict[str, Any]:
        now = utc_now()
        with self._lock, self._connect() as conn:
            conn.execute("""
                INSERT INTO contacts(phone,name,note,created_at,updated_at) VALUES(?,?,?,?,?)
                ON CONFLICT(phone) DO UPDATE SET
                    name=excluded.name,note=excluded.note,updated_at=excluded.updated_at
            """, (phone, name, note, now, now))
            row = conn.execute("SELECT * FROM contacts WHERE phone=?", (phone,)).fetchone()
        return dict(row)

    def delete_contact(self, phone: str) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM contacts WHERE phone=?", (phone,))
            return cur.rowcount > 0

    def get_setting(self, key: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
        return str(row["value"]) if row else None

    def set_setting(self, key: str, value: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("""
                INSERT INTO app_settings(key,value,updated_at) VALUES(?,?,?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at
            """, (key, value, utc_now()))
