from __future__ import annotations

import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


BLACKLIST_MATCH_TYPES = {"exact", "contains", "regex"}


def validate_blacklist_rule(pattern: str, match_type: str = "exact") -> tuple[str, str]:
    pattern = pattern.strip()
    match_type = match_type.strip().lower() or "exact"
    if match_type not in BLACKLIST_MATCH_TYPES:
        raise ValueError("匹配方式须为 exact、contains 或 regex")
    if not pattern:
        raise ValueError("黑名单规则不能为空")
    if match_type == "exact":
        if not re.fullmatch(r"\+?[0-9]{5,20}", pattern):
            raise ValueError("精确匹配号码须为 5–20 位数字，可带开头的 +")
    elif len(pattern) > 160:
        raise ValueError("包含匹配或正则表达式最多 160 个字符")
    if match_type == "regex":
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"正则表达式无效：{exc}") from exc
    return pattern, match_type


def blacklist_rule_matches(pattern: str, match_type: str, phone: str) -> bool:
    match_type = match_type if match_type in BLACKLIST_MATCH_TYPES else "exact"
    if match_type == "exact":
        return phone == pattern
    if match_type == "contains":
        return pattern in phone
    try:
        return re.search(pattern, phone) is not None
    except re.error:
        return False

AD_MATCH_TYPES = {"contains", "regex"}
AD_FIELDS = {"body", "phone", "both"}


def validate_ad_rule(pattern: str, match_type: str = "contains", field: str = "body") -> tuple[str, str, str]:
    pattern = pattern.strip()
    match_type = match_type.strip().lower() or "contains"
    field = field.strip().lower() or "body"
    if not pattern or len(pattern) > 160:
        raise ValueError("广告过滤规则须为 1–160 个字符")
    if match_type not in AD_MATCH_TYPES:
        raise ValueError("广告匹配方式须为 contains 或 regex")
    if field not in AD_FIELDS:
        raise ValueError("广告过滤范围须为 body、phone 或 both")
    if match_type == "regex":
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"正则表达式无效：{exc}") from exc
    return pattern, match_type, field


def ad_rule_matches(rule: dict[str, Any], phone: str, body: str) -> bool:
    pattern = str(rule.get("pattern") or "")
    match_type = str(rule.get("match_type") or "contains")
    field = str(rule.get("field") or "body")
    values = ([body] if field == "body" else [phone] if field == "phone" else [phone, body])
    try:
        if match_type == "regex":
            return any(re.search(pattern, value, re.IGNORECASE) is not None for value in values)
        return any(pattern.casefold() in value.casefold() for value in values)
    except re.error:
        return False


class MessageStore:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _connection(self):
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init(self) -> None:
        with self._connection() as conn:
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
            if "blacklisted" not in columns:
                conn.execute("ALTER TABLE messages ADD COLUMN blacklisted INTEGER NOT NULL DEFAULT 0")
            if "advertisement" not in columns:
                conn.execute("ALTER TABLE messages ADD COLUMN advertisement INTEGER NOT NULL DEFAULT 0")
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
            conn.execute("""
                CREATE TABLE IF NOT EXISTS blacklist (
                    phone TEXT PRIMARY KEY,
                    label TEXT NOT NULL DEFAULT '',
                    note TEXT NOT NULL DEFAULT '',
                    match_type TEXT NOT NULL DEFAULT 'exact',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            blacklist_columns = {row[1] for row in conn.execute("PRAGMA table_info(blacklist)")}
            if "match_type" not in blacklist_columns:
                conn.execute("ALTER TABLE blacklist ADD COLUMN match_type TEXT NOT NULL DEFAULT 'exact'")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ad_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pattern TEXT NOT NULL,
                    match_type TEXT NOT NULL DEFAULT 'contains',
                    field TEXT NOT NULL DEFAULT 'body',
                    label TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            seeded = conn.execute("SELECT value FROM app_settings WHERE key='ad_rules_seeded'").fetchone()
            if not seeded:
                now = utc_now()
                for pattern, match_type, field, label in [
                    (r'(?:退订|拒收)(?:请)?(?:回复|回)[A-Za-z0-9]{1,4}\s*$',
                     'regex', 'body', '营销短信退订回复提示'),
                    (r'(?:回复|回)[A-Za-z0-9]{1,4}(?:退订|拒收)\s*$',
                     'regex', 'body', '营销短信回复退订提示'),
                ]:
                    conn.execute("INSERT INTO ad_rules(pattern,match_type,field,label,enabled,created_at,updated_at) "
                                 "VALUES(?,?,?,?,1,?,?)", (pattern, match_type, field, label, now, now))
                conn.execute("INSERT INTO app_settings(key,value,updated_at) VALUES('ad_rules_seeded','1',?)",
                             (now,))

    def create(self, direction: str, phone: str, body: str, status: str,
               modem_index: int | None = None, error: str | None = None,
               device_id: str | None = None, blacklisted: bool = False,
               advertisement: bool = False) -> int:
        now = utc_now()
        with self._lock, self._connection() as conn:
            if modem_index is not None:
                existing = conn.execute(
                    "SELECT id FROM messages WHERE direction=? AND modem_index=? AND device_id IS ?",
                    (direction, modem_index, device_id),
                ).fetchone()
                if existing:
                    return int(existing["id"])
            cur = conn.execute(
                "INSERT OR IGNORE INTO messages(direction,phone,body,status,modem_index,error,created_at,updated_at,device_id,blacklisted,advertisement) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (direction, phone, body, status, modem_index, error, now, now, device_id,
                 int(blacklisted), int(advertisement)),
            )
            if cur.lastrowid:
                return int(cur.lastrowid)
            row = conn.execute("SELECT id FROM messages WHERE direction=? AND modem_index=? "
                               "AND device_id IS ?", (direction, modem_index, device_id)).fetchone()
            return int(row["id"])

    def update(self, message_id: int, status: str, error: str | None = None) -> None:
        with self._lock, self._connection() as conn:
            conn.execute(
                "UPDATE messages SET status=?,error=?,updated_at=? WHERE id=?",
                (status, error, utc_now(), message_id),
            )

    def set_favorite(self, message_id: int, favorite: bool) -> dict[str, Any] | None:
        with self._lock, self._connection() as conn:
            conn.execute("UPDATE messages SET favorite=? WHERE id=?", (int(favorite), message_id))
            row = conn.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
        return dict(row) if row else None

    def get(self, message_id: int) -> dict[str, Any] | None:
        with self._connection() as conn:
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
        with self._connection() as conn:
            rows = conn.execute(sql, values).fetchall()
        return [dict(row) for row in rows]

    def upsert_device(self, device_id: str, imei: str, status: str, serial_port: str | None,
                      firmware_version: str = "", error: str | None = None) -> None:
        now = utc_now()
        with self._lock, self._connection() as conn:
            conn.execute("""
                INSERT INTO devices(device_id,imei,firmware_version,serial_port,status,last_error,first_seen_at,last_seen_at)
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(device_id) DO UPDATE SET
                    imei=excluded.imei, firmware_version=excluded.firmware_version,
                    serial_port=excluded.serial_port, status=excluded.status,
                    last_error=excluded.last_error, last_seen_at=excluded.last_seen_at
            """, (device_id, imei, firmware_version, serial_port, status, error, now, now))

    def update_device_label(self, device_id: str, label: str) -> bool:
        with self._lock, self._connection() as conn:
            cur = conn.execute("UPDATE devices SET label=? WHERE device_id=?", (label, device_id))
            return cur.rowcount > 0

    def delete_device(self, device_id: str) -> str:
        with self._lock, self._connection() as conn:
            row = conn.execute("SELECT status FROM devices WHERE device_id=?", (device_id,)).fetchone()
            if not row:
                return "not_found"
            if row["status"] == "online":
                return "online"
            conn.execute("DELETE FROM devices WHERE device_id=?", (device_id,))
            return "deleted"

    def mark_all_devices_offline(self) -> None:
        with self._lock, self._connection() as conn:
            conn.execute("UPDATE devices SET status='offline',serial_port=NULL "
                         "WHERE status='online'")

    def list_devices(self) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute("SELECT * FROM devices ORDER BY first_seen_at").fetchall()
        return [dict(row) for row in rows]

    def list_contacts(self) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute("SELECT * FROM contacts ORDER BY name COLLATE NOCASE, phone").fetchall()
        return [dict(row) for row in rows]

    def upsert_contact(self, phone: str, name: str, note: str = "") -> dict[str, Any]:
        now = utc_now()
        with self._lock, self._connection() as conn:
            conn.execute("""
                INSERT INTO contacts(phone,name,note,created_at,updated_at) VALUES(?,?,?,?,?)
                ON CONFLICT(phone) DO UPDATE SET
                    name=excluded.name,note=excluded.note,updated_at=excluded.updated_at
            """, (phone, name, note, now, now))
            row = conn.execute("SELECT * FROM contacts WHERE phone=?", (phone,)).fetchone()
        return dict(row)

    def delete_contact(self, phone: str) -> bool:
        with self._lock, self._connection() as conn:
            cur = conn.execute("DELETE FROM contacts WHERE phone=?", (phone,))
            return cur.rowcount > 0

    def is_blacklisted(self, phone: str) -> bool:
        with self._connection() as conn:
            rows = conn.execute("SELECT phone,match_type FROM blacklist").fetchall()
        return any(blacklist_rule_matches(row["phone"], row["match_type"], phone) for row in rows)

    def list_blacklist(self, search: str = "", match_type: str | None = None) -> list[dict[str, Any]]:
        search = search.strip().lower()
        if len(search) > 160:
            raise ValueError("搜索关键词最多 160 个字符")
        if match_type:
            match_type = match_type.strip().lower()
            if match_type not in BLACKLIST_MATCH_TYPES:
                raise ValueError("匹配方式须为 exact、contains 或 regex")
        with self._connection() as conn:
            rules = [dict(row) for row in conn.execute("SELECT * FROM blacklist").fetchall()]
            stats = [dict(row) for row in conn.execute(
                "SELECT phone,COUNT(*) AS message_count,MAX(created_at) AS last_message_at "
                "FROM messages WHERE blacklisted=1 GROUP BY phone"
            ).fetchall()]
        items: list[dict[str, Any]] = []
        for rule in rules:
            rule_type = rule.get("match_type") or "exact"
            if match_type and rule_type != match_type:
                continue
            if search and search not in " ".join(
                str(rule.get(key) or "").lower() for key in ("phone", "label", "note", "match_type")
            ):
                continue
            matched = [item for item in stats
                       if blacklist_rule_matches(str(rule["phone"]), str(rule_type), str(item["phone"]))]
            item = dict(rule)
            item["match_type"] = rule_type if rule_type in BLACKLIST_MATCH_TYPES else "exact"
            item["message_count"] = sum(int(entry["message_count"]) for entry in matched)
            item["last_message_at"] = max(
                (str(entry["last_message_at"]) for entry in matched if entry.get("last_message_at")),
                default=None,
            )
            item["matched_phones"] = [str(entry["phone"]) for entry in matched]
            items.append(item)
        items.sort(key=lambda item: item.get("last_message_at") or item.get("updated_at") or "", reverse=True)
        return items

    def upsert_blacklist(self, phone: str, label: str = "", note: str = "",
                         match_type: str = "exact") -> dict[str, Any]:
        phone, match_type = validate_blacklist_rule(phone, match_type)
        now = utc_now()
        with self._lock, self._connection() as conn:
            conn.execute("""
                INSERT INTO blacklist(phone,label,note,match_type,created_at,updated_at) VALUES(?,?,?,?,?,?)
                ON CONFLICT(phone) DO UPDATE SET
                    label=excluded.label,note=excluded.note,match_type=excluded.match_type,
                    updated_at=excluded.updated_at
            """, (phone, label, note, match_type, now, now))
            row = conn.execute("SELECT * FROM blacklist WHERE phone=?", (phone,)).fetchone()
        return dict(row)

    def delete_blacklist(self, phone: str) -> bool:
        with self._lock, self._connection() as conn:
            cur = conn.execute("DELETE FROM blacklist WHERE phone=?", (phone,))
            return cur.rowcount > 0

    def list_ad_rules(self, search: str = "", enabled: bool | None = None) -> list[dict[str, Any]]:
        search = search.strip().casefold()
        with self._connection() as conn:
            rows = [dict(row) for row in conn.execute("SELECT * FROM ad_rules ORDER BY id").fetchall()]
        result = []
        for item in rows:
            if enabled is not None and bool(item["enabled"]) != enabled:
                continue
            if search and search not in " ".join(str(item.get(key) or "").casefold()
                                                 for key in ("pattern", "label", "match_type", "field")):
                continue
            result.append(item)
        return result

    def match_advertisement(self, phone: str, body: str) -> dict[str, Any] | None:
        for rule in self.list_ad_rules(enabled=True):
            if ad_rule_matches(rule, phone, body):
                return rule
        return None

    def create_ad_rule(self, pattern: str, match_type: str = "contains", field: str = "body",
                       label: str = "", enabled: bool = True) -> dict[str, Any]:
        pattern, match_type, field = validate_ad_rule(pattern, match_type, field)
        label = label.strip()
        if len(label) > 80:
            raise ValueError("规则备注最多 80 个字符")
        now = utc_now()
        with self._lock, self._connection() as conn:
            cur = conn.execute("INSERT INTO ad_rules(pattern,match_type,field,label,enabled,created_at,updated_at) "
                               "VALUES(?,?,?,?,?,?,?)",
                               (pattern, match_type, field, label, int(enabled), now, now))
            row = conn.execute("SELECT * FROM ad_rules WHERE id=?", (cur.lastrowid,)).fetchone()
        return dict(row)

    def update_ad_rule(self, rule_id: int, pattern: str, match_type: str, field: str,
                       label: str, enabled: bool) -> dict[str, Any] | None:
        pattern, match_type, field = validate_ad_rule(pattern, match_type, field)
        label = label.strip()
        if len(label) > 80:
            raise ValueError("规则备注最多 80 个字符")
        with self._lock, self._connection() as conn:
            cur = conn.execute("UPDATE ad_rules SET pattern=?,match_type=?,field=?,label=?,enabled=?,updated_at=? "
                               "WHERE id=?", (pattern, match_type, field, label, int(enabled), utc_now(), rule_id))
            if not cur.rowcount:
                return None
            row = conn.execute("SELECT * FROM ad_rules WHERE id=?", (rule_id,)).fetchone()
        return dict(row)

    def delete_ad_rule(self, rule_id: int) -> bool:
        with self._lock, self._connection() as conn:
            return conn.execute("DELETE FROM ad_rules WHERE id=?", (rule_id,)).rowcount > 0

    def get_setting(self, key: str) -> str | None:
        with self._connection() as conn:
            row = conn.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
        return str(row["value"]) if row else None

    def set_setting(self, key: str, value: str) -> None:
        with self._lock, self._connection() as conn:
            conn.execute("""
                INSERT INTO app_settings(key,value,updated_at) VALUES(?,?,?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at
            """, (key, value, utc_now()))
