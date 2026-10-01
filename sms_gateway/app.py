from __future__ import annotations

import json
import hmac
import logging
import mimetypes
import re
import signal
import socket
import threading
import uuid
from pathlib import Path
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from . import __version__
from .admin import AdminAccess
from .config import Settings
from .manager import DeviceManager
from .modem import ReceivedSms
from .store import MessageStore
from .ui import MOBILE_UI, openapi_document
from .webhook import deliver, deliver_feishu, deliver_dingtalk

log = logging.getLogger(__name__)
WEB_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


class Gateway:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.store = MessageStore(settings.database_path)
        self.admin = AdminAccess(self.store, settings.admin_password)
        self.manager = DeviceManager(self.store, settings.serial_baudrate, settings.poll_seconds,
                                     settings.serial_port, self._received, self._sent,
                                     self._device_state, settings.send_attempts)

    def start(self) -> None:
        self.manager.start()

    def stop(self) -> None:
        self.manager.stop()
        self.manager.join(timeout=3)

    def send(self, phone: str, body: str, device_id: str | None = None) -> dict:
        if not re.fullmatch(r"\+?[0-9]{5,20}", phone):
            raise ValueError("phone must contain 5-20 digits with optional leading +")
        if not body or len(body) > 134:
            raise ValueError("body must contain 1-134 characters")
        selected = self.manager.select(device_id)
        message_id = self.store.create("outbound", phone, body, "queued",
                                       device_id=selected.device_id)
        selected.worker.enqueue(message_id, phone, body, self._sent)
        return self.store.get(message_id) or {}

    def _sent(self, message_id: int, ok: bool, error: str | None) -> None:
        self.store.update(message_id, "sent" if ok else "failed", error)
        message = self.store.get(message_id)
        if message:
            event = {"event": "sms.sent", "device_id": message.get("device_id"),
                     "device_label": self._device_label(message.get("device_id")),
                     "message": message}
            threading.Thread(target=self._deliver_event, args=(event,), daemon=True,
                             name=f"webhook-sent-{message_id}").start()

    def _received(self, device_id: str, sms: ReceivedSms) -> None:
        blocked = self.store.is_blacklisted(sms.sender)
        ad_rule = None if blocked else self.store.match_advertisement(sms.sender, sms.body)
        advertisement = ad_rule is not None
        status = "blacklisted" if blocked else "advertisement" if advertisement else "received"
        message_id = self.store.create(
            "inbound", sms.sender, sms.body, status, sms.index, device_id=device_id,
            blacklisted=blocked, advertisement=advertisement
        )
        if blocked:
            log.info("stored SMS from blacklisted number %s without notifications", sms.sender)
            return
        if advertisement:
            log.info("stored advertisement SMS from %s matched rule %s without notifications",
                     sms.sender, ad_rule.get("id"))
            return
        event = {"event": "sms.received", "device_id": device_id,
                 "device_label": self._device_label(device_id),
                 "message": self.store.get(message_id)}
        threading.Thread(target=self._notify, args=(message_id, event), daemon=True,
                         name=f"webhook-{message_id}").start()

    def _notify(self, message_id: int, event: dict) -> None:
        ok = self._deliver_event(event)
        self.store.update(message_id, "delivered" if ok else "webhook_failed")

    def _deliver_event(self, event: dict) -> bool:
        generic_ok = deliver(self.settings.webhook_url, self.settings.webhook_secret, event)
        hooks = self.feishu_webhooks()
        feishu_ok = all([deliver_feishu(item["url"], event)
                         for item in hooks if item.get("enabled", True)])
        dingtalk_ok = all([deliver_dingtalk(item["url"], item.get("secret", ""), event)
                           for item in self.dingtalk_webhooks() if item.get("enabled", True)])
        return generic_ok and feishu_ok and dingtalk_ok

    def dingtalk_webhooks(self) -> list[dict]:
        stored = self.store.get_setting("dingtalk_webhooks")
        if not stored:
            return []
        try:
            value = json.loads(stored)
            return value if isinstance(value, list) else []
        except json.JSONDecodeError:
            return []

    def public_dingtalk_webhooks(self) -> list[dict]:
        return [{"id": item["id"], "label": item.get("label") or "未备注机器人",
                 "enabled": item.get("enabled", True), "signed": bool(item.get("secret")),
                 "masked": "••••••••" + item.get("url", "")[-8:]}
                for item in self.dingtalk_webhooks()]

    @staticmethod
    def _validate_dingtalk_url(value: str) -> str:
        value = value.strip()
        if not re.fullmatch(r"https://(?:oapi|api)\.dingtalk\.com/robot/send\?access_token=[A-Za-z0-9]+", value):
            raise ValueError("请输入有效的钉钉群机器人 Webhook 地址")
        return value

    def add_dingtalk_webhook(self, label: str, url: str, secret: str) -> dict:
        items = self.dingtalk_webhooks()
        secret = secret.strip()
        if secret and not re.fullmatch(r"SEC[0-9a-fA-F]+", secret):
            raise ValueError("加签密钥应以 SEC 开头")
        items.append({"id": uuid.uuid4().hex, "label": label.strip() or "未备注机器人",
                      "url": self._validate_dingtalk_url(url), "secret": secret, "enabled": True})
        self.store.set_setting("dingtalk_webhooks", json.dumps(items, ensure_ascii=False))
        return {"webhooks": self.public_dingtalk_webhooks()}

    def update_dingtalk_webhook(self, item_id: str, payload: dict) -> dict:
        items = self.dingtalk_webhooks()
        item = next((x for x in items if x["id"] == item_id), None)
        if not item:
            raise KeyError(item_id)
        if "label" in payload:
            item["label"] = str(payload["label"]).strip() or "未备注机器人"
        if "enabled" in payload:
            item["enabled"] = bool(payload["enabled"])
        if payload.get("webhook_url"):
            item["url"] = self._validate_dingtalk_url(str(payload["webhook_url"]))
        if "secret" in payload:
            secret = str(payload["secret"]).strip()
            if secret and not re.fullmatch(r"SEC[0-9a-fA-F]+", secret):
                raise ValueError("加签密钥应以 SEC 开头")
            item["secret"] = secret
        self.store.set_setting("dingtalk_webhooks", json.dumps(items, ensure_ascii=False))
        return {"webhooks": self.public_dingtalk_webhooks()}

    def delete_dingtalk_webhook(self, item_id: str) -> dict:
        items = self.dingtalk_webhooks()
        kept = [x for x in items if x["id"] != item_id]
        if len(kept) == len(items):
            raise KeyError(item_id)
        self.store.set_setting("dingtalk_webhooks", json.dumps(kept, ensure_ascii=False))
        return {"webhooks": self.public_dingtalk_webhooks()}

    def feishu_webhooks(self) -> list[dict]:
        stored = self.store.get_setting("feishu_webhooks")
        if stored is not None:
            try:
                value = json.loads(stored)
                return value if isinstance(value, list) else []
            except json.JSONDecodeError:
                return []
        legacy = self.store.get_setting("feishu_webhook_url")
        url = self.settings.feishu_webhook_url if legacy is None else legacy
        return ([{"id": "default", "label": "默认飞书群", "url": url, "enabled": True}]
                if url else [])

    def public_feishu_webhooks(self) -> list[dict]:
        return [{"id": item["id"], "label": item.get("label") or "未备注机器人",
                 "enabled": item.get("enabled", True),
                 "masked": "••••••••" + item.get("url", "")[-8:]}
                for item in self.feishu_webhooks()]

    @staticmethod
    def _validate_feishu_url(value: str) -> str:
        value = value.strip()
        if not re.fullmatch(
            r"https://open\.feishu\.cn/open-apis/bot/v2/hook/[A-Za-z0-9-]+", value
        ):
            raise ValueError("请输入有效的飞书群机器人 Hook 地址")
        return value

    def add_feishu_webhook(self, label: str, url: str) -> dict:
        items = self.feishu_webhooks()
        items.append({"id": uuid.uuid4().hex, "label": label.strip() or "未备注机器人",
                      "url": self._validate_feishu_url(url), "enabled": True})
        self.store.set_setting("feishu_webhooks", json.dumps(items, ensure_ascii=False))
        return {"webhooks": self.public_feishu_webhooks()}

    def update_feishu_webhook(self, item_id: str, payload: dict) -> dict:
        items = self.feishu_webhooks()
        item = next((x for x in items if x["id"] == item_id), None)
        if not item:
            raise KeyError(item_id)
        if "label" in payload:
            item["label"] = str(payload["label"]).strip() or "未备注机器人"
        if "enabled" in payload:
            item["enabled"] = bool(payload["enabled"])
        if payload.get("webhook_url"):
            item["url"] = self._validate_feishu_url(str(payload["webhook_url"]))
        self.store.set_setting("feishu_webhooks", json.dumps(items, ensure_ascii=False))
        return {"webhooks": self.public_feishu_webhooks()}

    def delete_feishu_webhook(self, item_id: str) -> dict:
        items = self.feishu_webhooks()
        kept = [x for x in items if x["id"] != item_id]
        if len(kept) == len(items):
            raise KeyError(item_id)
        self.store.set_setting("feishu_webhooks", json.dumps(kept, ensure_ascii=False))
        return {"webhooks": self.public_feishu_webhooks()}

    def _device_state(self, device_id: str, status: str, error: str | None) -> None:
        event = {"event": "device." + status, "device_id": device_id,
                 "device_label": self._device_label(device_id),
                 "status": status, "error": error}
        threading.Thread(target=self._deliver_event, args=(event,),
                         daemon=True, name=f"webhook-{status}-{device_id}").start()

    def _device_label(self, device_id: str | None) -> str:
        if not device_id:
            return ""
        device = next((d for d in self.store.list_devices()
                       if d["device_id"] == device_id), None)
        return str(device.get("label") or device.get("imei") or device_id) if device else device_id

    def health(self) -> dict:
        devices = self.store.list_devices()
        online = [d for d in devices if d["status"] == "online"]
        return {"ok": True, "version": __version__,
                "online_devices": len(online), "total_devices": len(devices),
                "modem_connected": bool(online),
                "serial_port": online[0]["serial_port"] if len(online) == 1 else None,
                "devices": devices}

    def portal_summary(self) -> dict:
        """Return a read-only, privacy-safe summary for embedded team portals."""
        devices = self.store.list_devices()
        messages = self.store.list(500)
        outbound = [item for item in messages if item.get("direction") == "outbound"]
        successful = [item for item in outbound if item.get("status") in {"sent", "delivered"}]
        failed = [item for item in messages if item.get("status") in {"failed", "webhook_failed"}]
        queued = [item for item in messages if item.get("status") == "queued"]
        recent = []
        for item in messages[:8]:
            recent.append({
                "direction": item.get("direction"),
                "status": item.get("status"),
                "device": self._device_label(item.get("device_id")) or "未分配设备",
                "created_at": item.get("created_at"),
            })
        safe_devices = [{
            "label": str(item.get("label") or "未命名设备"),
            "status": item.get("status") or "unknown",
            "firmware_version": item.get("firmware_version") or "",
            "last_seen_at": item.get("last_seen_at"),
            "has_error": bool(item.get("last_error")),
        } for item in devices]
        return {
            "ok": True,
            "version": __version__,
            "online_devices": sum(1 for item in devices if item.get("status") == "online"),
            "total_devices": len(devices),
            "messages": {
                "total": len(messages),
                "inbound": sum(1 for item in messages if item.get("direction") == "inbound"),
                "outbound": len(outbound),
                "failed": len(failed),
                "queued": len(queued),
                "success_rate": round(len(successful) * 100 / len(outbound), 1) if outbound else 100.0,
            },
            "integrations": {
                "feishu": sum(1 for item in self.public_feishu_webhooks() if item.get("enabled")),
                "dingtalk": sum(1 for item in self.public_dingtalk_webhooks() if item.get("enabled")),
            },
            "devices": safe_devices,
            "recent": recent,
        }

    def four_g(self, request: dict) -> dict:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(25)
                client.connect('/run/air780-4g/control.sock')
                client.sendall((json.dumps(request) + '\n').encode())
                data = b''
                while not data.endswith(b'\n') and len(data) < 8192:
                    chunk = client.recv(8192)
                    if not chunk:
                        break
                    data += chunk
            result = json.loads(data)
            if 'error' in result:
                raise ValueError(result['error'])
            devices = self.store.list_devices()
            for interface in result.get('interfaces', []):
                interface['device_id'] = next((d['device_id'] for d in devices
                    if d.get('serial_port') in interface.get('serial_ports', [])), None)
            if result.get('enabled') and not result.get('signal'):
                online = self.manager.online()
                signals = [item.worker.modem.device_info.get('signal') for item in online]
                result['signal'] = next((item for item in signals if isinstance(item, dict)), None)
                result['signal_supported'] = any(isinstance(item, dict) for item in signals)
            return result
        except (OSError, json.JSONDecodeError) as exc:
            if request.get('action') == 'status':
                return {'available': False, 'enabled': False, 'interfaces': [],
                        'error': f'4G 控制服务不可用：{exc}'}
            raise ValueError(f'4G 控制服务不可用：{exc}') from exc


def handler_factory(gateway: Gateway):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Air780SMSGateway/2.0"

        def log_message(self, fmt: str, *args) -> None:
            log.info("http %s - %s", self.address_string(), fmt % args)

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, data: dict | list) -> None:
            self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")

        def _session_token(self) -> str:
            return self.headers.get('X-User-Session', '') or self.headers.get('X-Admin-Session', '')

        def _session_user(self) -> dict | None:
            return gateway.admin.session_user(self._session_token())

        def _scope(self) -> str | None:
            if self._session_user():
                return 'write'
            token = self.headers.get("Authorization", "").removeprefix("Bearer ")
            expected = gateway.settings.api_token
            if expected and token and hmac.compare_digest(token, expected):
                return 'write'
            return gateway.admin.scope(token) if token else None

        def _require_auth(self, write: bool = False) -> bool:
            scope = self._scope()
            if scope and (not write or scope == 'write'):
                return True
            self._json(HTTPStatus.FORBIDDEN if scope else HTTPStatus.UNAUTHORIZED,
                       {"error": "read-only API key" if scope else "login required"})
            return False

        def _require_admin(self) -> bool:
            user = self._session_user()
            if user and user.get('role') == 'admin':
                return True
            self._json(HTTPStatus.FORBIDDEN if user else HTTPStatus.UNAUTHORIZED,
                       {'error': 'administrator required' if user else 'login required'})
            return False

        def _payload(self) -> dict:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 65536:
                raise ValueError("request too large")
            value = json.loads(self.rfile.read(length))
            if not isinstance(value, dict):
                raise ValueError("JSON body must be an object")
            return value

        def _static(self, path: str) -> bool:
            relative = "index.html" if path == "/" else path.lstrip("/")
            target = (WEB_DIST / relative).resolve()
            try:
                target.relative_to(WEB_DIST.resolve())
            except ValueError:
                return False
            if not target.is_file():
                return False
            content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            if content_type.startswith("text/") or content_type in {
                "application/javascript", "application/json"
            }:
                content_type += "; charset=utf-8"
            self._send(HTTPStatus.OK, target.read_bytes(), content_type)
            return True

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/health":
                self._json(HTTPStatus.OK, gateway.health())
                return
            if parsed.path == "/api/v1/portal/summary":
                self._json(HTTPStatus.OK, gateway.portal_summary())
                return
            if parsed.path in {"/portal", "/portal/", "/portal.html"}:
                if self._static("/portal.html"):
                    return
            if parsed.path == "/" and self._static(parsed.path):
                return
            if parsed.path == "/":
                self._send(HTTPStatus.OK, MOBILE_UI.encode("utf-8"), "text/html; charset=utf-8")
                return
            if parsed.path.startswith("/assets/") and self._static(parsed.path):
                return
            if parsed.path == '/api/v1/auth/me':
                user = self._session_user()
                self._json(HTTPStatus.OK if user else HTTPStatus.UNAUTHORIZED,
                           {'user': user} if user else {'error': 'login required'})
                return
            if parsed.path == '/api/v1/admin/users':
                if self._require_admin():
                    self._json(HTTPStatus.OK, {'users': gateway.admin.list_users()})
                return
            if parsed.path == '/api/v1/admin/keys':
                if self._require_admin():
                    self._json(HTTPStatus.OK, {'keys': gateway.admin.list()})
                return
            if not self._require_auth():
                return
            if parsed.path == "/api/v1/openapi.json":
                self._json(HTTPStatus.OK,
                           openapi_document("http://" + self.headers.get("Host", "127.0.0.1:8787")))
                return
            if parsed.path == "/api/v1/devices":
                signals = {item.device_id: item.worker.modem.device_info.get('signal')
                           for item in gateway.manager.online()}
                devices = [{**item, 'signal': signals.get(item['device_id'])}
                           for item in gateway.store.list_devices()]
                self._json(HTTPStatus.OK, {"devices": devices})
                return
            if parsed.path == "/api/v1/contacts":
                self._json(HTTPStatus.OK, {"contacts": gateway.store.list_contacts()})
                return
            if parsed.path == "/api/v1/blacklist":
                query = parse_qs(parsed.query)
                try:
                    search = str(query.get("q", [""])[0]).strip()
                    match_type = str(query.get("match_type", [""])[0]).strip() or None
                    self._json(HTTPStatus.OK, {"blacklist": gateway.store.list_blacklist(search, match_type)})
                except ValueError as exc:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            if parsed.path == "/api/v1/ad-rules":
                query = parse_qs(parsed.query)
                search = str(query.get("q", [""])[0]).strip()
                enabled_value = str(query.get("enabled", [""])[0]).strip().lower()
                enabled = None if not enabled_value else enabled_value in {'1', 'true', 'yes', 'on'}
                self._json(HTTPStatus.OK, {"rules": gateway.store.list_ad_rules(search, enabled)})
                return
            if parsed.path == "/api/v1/network/4g":
                self._json(HTTPStatus.OK, gateway.four_g({'action': 'status'}))
                return
            if parsed.path == "/api/v1/integrations/feishu":
                self._json(HTTPStatus.OK, {"webhooks": gateway.public_feishu_webhooks()})
                return
            if parsed.path == "/api/v1/integrations/dingtalk":
                self._json(HTTPStatus.OK, {"webhooks": gateway.public_dingtalk_webhooks()})
                return
            if parsed.path == "/api/v1/messages":
                query = parse_qs(parsed.query)
                try:
                    limit = int(query.get("limit", ["50"])[0])
                except ValueError:
                    limit = 50
                direction = query.get("direction", [None])[0]
                if direction not in (None, "inbound", "outbound"):
                    self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid direction"})
                    return
                self._json(HTTPStatus.OK, {"messages": gateway.store.list(
                    limit, direction, query.get("device_id", [None])[0])})
                return
            match = re.fullmatch(r"/api/v1/messages/(\d+)", parsed.path)
            if match:
                item = gateway.store.get(int(match.group(1)))
                self._json(HTTPStatus.OK if item else HTTPStatus.NOT_FOUND,
                           item or {"error": "not found"})
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            if path in {'/api/v1/auth/login', '/api/v1/admin/login'}:
                try:
                    payload = self._payload()
                    session = gateway.admin.login(str(payload.get('username', '')),
                                                  str(payload.get('password', '')))
                    user = gateway.admin.session_user(session or '')
                    self._json(HTTPStatus.OK if session else HTTPStatus.UNAUTHORIZED,
                               {'session': session, 'user': user} if session
                               else {'error': '账号或密码错误或用户已禁用'})
                except (ValueError, json.JSONDecodeError) as exc:
                    self._json(HTTPStatus.BAD_REQUEST, {'error': str(exc)})
                return
            if path == '/api/v1/auth/logout':
                gateway.admin.logout(self._session_token())
                self._json(HTTPStatus.OK, {'ok': True})
                return
            if path == '/api/v1/admin/users':
                if not self._require_admin():
                    return
                try:
                    payload = self._payload()
                    item = gateway.admin.create_user(str(payload.get('username', '')),
                                                     str(payload.get('password', '')))
                    self._json(HTTPStatus.CREATED, {'user': item, 'users': gateway.admin.list_users()})
                except (ValueError, json.JSONDecodeError) as exc:
                    self._json(HTTPStatus.BAD_REQUEST, {'error': str(exc)})
                return
            if path == '/api/v1/admin/keys':
                if not self._require_admin():
                    return
                try:
                    payload = self._payload()
                    item, token = gateway.admin.create(str(payload.get('label', '')),
                                                       str(payload.get('scope', 'read')))
                    self._json(HTTPStatus.CREATED, {'key': item, 'token': token})
                except (ValueError, json.JSONDecodeError) as exc:
                    self._json(HTTPStatus.BAD_REQUEST, {'error': str(exc)})
                return
            if not self._require_auth(write=True):
                return
            if path == "/api/v1/ad-rules":
                try:
                    payload = self._payload()
                    item = gateway.store.create_ad_rule(
                        str(payload.get('pattern', '')), str(payload.get('match_type', 'contains')),
                        str(payload.get('field', 'body')), str(payload.get('label', '')),
                        bool(payload.get('enabled', True)))
                    self._json(HTTPStatus.CREATED, item)
                except (ValueError, json.JSONDecodeError, AttributeError) as exc:
                    self._json(HTTPStatus.BAD_REQUEST, {'error': str(exc)})
                return
            if path == "/api/v1/integrations/feishu":
                if not self._require_admin():
                    return
                try:
                    payload = self._payload()
                    self._json(HTTPStatus.CREATED, gateway.add_feishu_webhook(
                        str(payload.get("label", "")), str(payload.get("webhook_url", ""))))
                except (ValueError, json.JSONDecodeError, AttributeError) as exc:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            if path == "/api/v1/integrations/dingtalk":
                if not self._require_admin():
                    return
                try:
                    payload = self._payload()
                    self._json(HTTPStatus.CREATED, gateway.add_dingtalk_webhook(
                        str(payload.get("label", "")), str(payload.get("webhook_url", "")),
                        str(payload.get("secret", ""))))
                except (ValueError, json.JSONDecodeError, AttributeError) as exc:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            if path != "/api/v1/messages":
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return
            try:
                payload = self._payload()
                message = gateway.send(str(payload.get("phone", "")), str(payload.get("body", "")),
                                       str(payload["device_id"]) if payload.get("device_id") else None)
                self._json(HTTPStatus.ACCEPTED, message)
            except (ValueError, json.JSONDecodeError, AttributeError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

        def do_PATCH(self) -> None:
            path = urlparse(self.path).path
            user_match = re.fullmatch(r'/api/v1/admin/users/([^/]+)', path)
            if user_match:
                if not self._require_admin():
                    return
                try:
                    payload = self._payload()
                    if type(payload.get('enabled')) is not bool:
                        raise ValueError('enabled must be a boolean')
                    user = gateway.admin.update_user(unquote(user_match.group(1)), payload['enabled'])
                    self._json(HTTPStatus.OK, {'user': user, 'users': gateway.admin.list_users()})
                except KeyError:
                    self._json(HTTPStatus.NOT_FOUND, {'error': 'user not found'})
                except (ValueError, json.JSONDecodeError) as exc:
                    self._json(HTTPStatus.BAD_REQUEST, {'error': str(exc)})
                return
            admin_match = re.fullmatch(r'/api/v1/admin/keys/([a-f0-9]+)', path)
            if admin_match:
                if not self._require_admin():
                    return
                try:
                    label = str(self._payload().get('label', ''))
                    ok = gateway.admin.update(admin_match.group(1), label)
                    self._json(HTTPStatus.OK if ok else HTTPStatus.NOT_FOUND,
                               {'keys': gateway.admin.list()} if ok else {'error': 'key not found'})
                except (ValueError, json.JSONDecodeError) as exc:
                    self._json(HTTPStatus.BAD_REQUEST, {'error': str(exc)})
                return
            if not self._require_auth(write=True):
                return
            ad_match = re.fullmatch(r'/api/v1/ad-rules/(\d+)', path)
            if ad_match:
                try:
                    payload = self._payload()
                    item = gateway.store.update_ad_rule(
                        int(ad_match.group(1)), str(payload.get('pattern', '')),
                        str(payload.get('match_type', 'contains')), str(payload.get('field', 'body')),
                        str(payload.get('label', '')), bool(payload.get('enabled', True)))
                    self._json(HTTPStatus.OK if item else HTTPStatus.NOT_FOUND,
                               item or {'error': 'ad rule not found'})
                except (ValueError, json.JSONDecodeError, AttributeError) as exc:
                    self._json(HTTPStatus.BAD_REQUEST, {'error': str(exc)})
                return
            favorite_match = re.fullmatch(r"/api/v1/messages/(\d+)/favorite", path)
            if favorite_match:
                try:
                    payload = self._payload()
                    if not isinstance(payload.get("favorite"), bool):
                        raise ValueError("favorite must be a boolean")
                    item = gateway.store.set_favorite(int(favorite_match.group(1)), payload["favorite"])
                    self._json(HTTPStatus.OK if item else HTTPStatus.NOT_FOUND,
                               item or {"error": "message not found"})
                except (ValueError, json.JSONDecodeError, AttributeError) as exc:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            if path.startswith('/api/v1/integrations/') and not self._require_admin():
                return
            hook_match = re.fullmatch(r"/api/v1/integrations/feishu/([^/]+)", path)
            if hook_match:
                try:
                    self._json(HTTPStatus.OK, gateway.update_feishu_webhook(
                        hook_match.group(1), self._payload()))
                except KeyError:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "webhook not found"})
                except (ValueError, json.JSONDecodeError, AttributeError) as exc:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            hook_match = re.fullmatch(r"/api/v1/integrations/dingtalk/([^/]+)", path)
            if hook_match:
                try:
                    self._json(HTTPStatus.OK, gateway.update_dingtalk_webhook(
                        hook_match.group(1), self._payload()))
                except KeyError:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "webhook not found"})
                except (ValueError, json.JSONDecodeError, AttributeError) as exc:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            match = re.fullmatch(r"/api/v1/devices/([^/]+)", path)
            if not match:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return
            try:
                label = str(self._payload().get("label", "")).strip()
                if len(label) > 60:
                    raise ValueError("label must not exceed 60 characters")
                if not gateway.store.update_device_label(match.group(1), label):
                    self._json(HTTPStatus.NOT_FOUND, {"error": "device not found"})
                    return
                device = next(d for d in gateway.store.list_devices()
                              if d["device_id"] == match.group(1))
                self._json(HTTPStatus.OK, device)
            except (ValueError, json.JSONDecodeError, AttributeError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

        def do_PUT(self) -> None:
            path = urlparse(self.path).path
            if path in {'/api/v1/auth/password', '/api/v1/admin/password'}:
                if not self._require_auth(write=True):
                    return
                try:
                    payload = self._payload()
                    gateway.admin.change_own_password(
                        self._session_token(), str(payload.get('current_password', '')),
                        str(payload.get('new_password', '')))
                    self._json(HTTPStatus.OK, {'ok': True})
                except PermissionError as exc:
                    self._json(HTTPStatus.FORBIDDEN, {'error': str(exc)})
                except (ValueError, json.JSONDecodeError) as exc:
                    self._json(HTTPStatus.BAD_REQUEST, {'error': str(exc)})
                return
            password_match = re.fullmatch(r'/api/v1/admin/users/([^/]+)/password', path)
            if password_match:
                if not self._require_admin():
                    return
                try:
                    payload = self._payload()
                    gateway.admin.reset_user_password(unquote(password_match.group(1)),
                                                      str(payload.get('password', '')))
                    self._json(HTTPStatus.OK, {'ok': True})
                except KeyError:
                    self._json(HTTPStatus.NOT_FOUND, {'error': 'user not found'})
                except (ValueError, json.JSONDecodeError) as exc:
                    self._json(HTTPStatus.BAD_REQUEST, {'error': str(exc)})
                return
            if not self._require_auth(write=True):
                return
            if path == "/api/v1/network/4g":
                if not self._require_admin():
                    return
                try:
                    payload = self._payload()
                    if type(payload.get('enabled')) is not bool:
                        raise ValueError('enabled must be a boolean')
                    interface = payload.get('interface')
                    if interface is not None and not re.fullmatch(r'[A-Za-z0-9_.:-]{1,64}', str(interface)):
                        raise ValueError('interface is invalid')
                    self._json(HTTPStatus.OK, gateway.four_g({
                        'action': 'set', 'enabled': payload['enabled'],
                        'interface': interface}))
                except (ValueError, json.JSONDecodeError, AttributeError) as exc:
                    self._json(HTTPStatus.BAD_REQUEST, {'error': str(exc)})
                return
            blacklist_match = re.fullmatch(r"/api/v1/blacklist/([^/]+)", path)
            if blacklist_match:
                try:
                    pattern = unquote(blacklist_match.group(1))
                    payload = self._payload()
                    label = str(payload.get("label", "")).strip()
                    note = str(payload.get("note", "")).strip()
                    match_type = str(payload.get("match_type", "exact")).strip().lower() or "exact"
                    if len(label) > 80 or len(note) > 500:
                        raise ValueError("备注名称最多 80 个字符，详细备注最多 500 个字符")
                    self._json(HTTPStatus.OK, gateway.store.upsert_blacklist(
                        pattern, label, note, match_type))
                except (ValueError, json.JSONDecodeError, AttributeError) as exc:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            match = re.fullmatch(r"/api/v1/contacts/([^/]+)", path)
            if not match:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return
            try:
                phone = unquote(match.group(1))
                if not re.fullmatch(r"\+?[0-9]{5,20}", phone):
                    raise ValueError("号码须为 5–20 位数字，可带开头的 +")
                payload = self._payload()
                name = str(payload.get("name", "")).strip()
                note = str(payload.get("note", "")).strip()
                if not name or len(name) > 80:
                    raise ValueError("姓名或备注须为 1–80 个字符")
                if len(note) > 500:
                    raise ValueError("详细备注不能超过 500 个字符")
                self._json(HTTPStatus.OK, gateway.store.upsert_contact(phone, name, note))
            except (ValueError, json.JSONDecodeError, AttributeError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

        def do_DELETE(self) -> None:
            path = urlparse(self.path).path
            user_match = re.fullmatch(r'/api/v1/admin/users/([^/]+)', path)
            if user_match:
                if not self._require_admin():
                    return
                try:
                    if gateway.admin.delete_user(unquote(user_match.group(1))):
                        self._json(HTTPStatus.OK, {'users': gateway.admin.list_users()})
                    else:
                        self._json(HTTPStatus.NOT_FOUND, {'error': 'user not found'})
                except ValueError as exc:
                    self._json(HTTPStatus.BAD_REQUEST, {'error': str(exc)})
                return
            admin_match = re.fullmatch(r'/api/v1/admin/keys/([a-f0-9]+)', path)
            if admin_match:
                if not self._require_admin():
                    return
                ok = gateway.admin.delete(admin_match.group(1))
                self._json(HTTPStatus.OK if ok else HTTPStatus.NOT_FOUND,
                           {'keys': gateway.admin.list()} if ok else {'error': 'key not found'})
                return
            if not self._require_auth(write=True):
                return
            device_match = re.fullmatch(r'/api/v1/devices/([^/]+)', path)
            if device_match:
                if not self._require_admin():
                    return
                result = gateway.store.delete_device(unquote(device_match.group(1)))
                if result == 'deleted':
                    self._json(HTTPStatus.OK, {'ok': True})
                elif result == 'online':
                    self._json(HTTPStatus.CONFLICT, {'error': '在线设备不能删除，请先断开设备'})
                else:
                    self._json(HTTPStatus.NOT_FOUND, {'error': 'device not found'})
                return
            ad_match = re.fullmatch(r'/api/v1/ad-rules/(\d+)', path)
            if ad_match:
                if gateway.store.delete_ad_rule(int(ad_match.group(1))):
                    self._json(HTTPStatus.OK, {'ok': True})
                else:
                    self._json(HTTPStatus.NOT_FOUND, {'error': 'ad rule not found'})
                return
            contact_match = re.fullmatch(r"/api/v1/contacts/([^/]+)", path)
            if contact_match:
                if gateway.store.delete_contact(unquote(contact_match.group(1))):
                    self._json(HTTPStatus.OK, {"ok": True})
                else:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "contact not found"})
                return
            blacklist_match = re.fullmatch(r"/api/v1/blacklist/([^/]+)", path)
            if blacklist_match:
                if gateway.store.delete_blacklist(unquote(blacklist_match.group(1))):
                    self._json(HTTPStatus.OK, {"ok": True})
                else:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "blacklist entry not found"})
                return
            if path.startswith('/api/v1/integrations/') and not self._require_admin():
                return
            dingtalk_match = re.fullmatch(r"/api/v1/integrations/dingtalk/([^/]+)", path)
            if dingtalk_match:
                try:
                    self._json(HTTPStatus.OK, gateway.delete_dingtalk_webhook(dingtalk_match.group(1)))
                except KeyError:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "webhook not found"})
                return
            match = re.fullmatch(r"/api/v1/integrations/feishu/([^/]+)", path)
            if not match:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return
            try:
                self._json(HTTPStatus.OK, gateway.delete_feishu_webhook(match.group(1)))
            except KeyError:
                self._json(HTTPStatus.NOT_FOUND, {"error": "webhook not found"})

    return Handler


def run(settings: Settings | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = settings or Settings()
    if settings.bind_host not in ("127.0.0.1", "::1", "localhost") and settings.admin_password == "admin":
        log.warning("default admin password is still in use; change it immediately after login")
    gateway = Gateway(settings)
    gateway.start()
    server = ThreadingHTTPServer((settings.bind_host, settings.bind_port), handler_factory(gateway))
    signal.signal(signal.SIGTERM,
                  lambda *_: threading.Thread(target=server.shutdown, daemon=True).start())
    log.info("API and mobile UI listening on http://%s:%s", settings.bind_host, settings.bind_port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        gateway.stop()
        server.server_close()
