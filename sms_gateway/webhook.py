from __future__ import annotations

import hashlib
import hmac
import base64
import json
import logging
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl

log = logging.getLogger(__name__)


def deliver(url: str, secret: str, event: dict, attempts: int = 4) -> bool:
    if not url:
        return True
    body = json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(time.time()))
    signature = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    request = urllib.request.Request(
        url, data=body, method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "X-SMS-Timestamp": timestamp,
            "X-SMS-Signature": "sha256=" + signature,
        },
    )
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                if 200 <= response.status < 300:
                    return True
        except (urllib.error.URLError, TimeoutError) as exc:
            log.warning("webhook attempt %d failed: %s", attempt + 1, exc)
        time.sleep(min(2 ** attempt, 8))
    return False


def _feishu_text(event: dict) -> str:
    kind = event.get("event")
    device_id = str(event.get("device_label") or event.get("device_id") or "未知设备")
    if kind == "sms.received":
        message = event.get("message") or {}
        return ("📩 收到短信\n"
                f"设备：{device_id}\n"
                f"号码：{message.get('phone', '')}\n"
                f"内容：{message.get('body', '')}\n"
                f"时间：{message.get('created_at', '')}")
    if kind == "sms.sent":
        message = event.get("message") or {}
        icon = "✅" if message.get("status") == "sent" else "❌"
        return (f"{icon} 短信发送{('成功' if message.get('status') == 'sent' else '失败')}\n"
                f"设备：{device_id}\n号码：{message.get('phone', '')}\n"
                f"状态：{message.get('status', '')}"
                + (f"\n错误：{message.get('error')}" if message.get("error") else ""))
    if kind in ("device.online", "device.offline"):
        online = kind.endswith("online")
        return (("🟢 设备上线" if online else "🔴 设备掉线")
                + f"\n设备：{device_id}"
                + (f"\n原因：{event.get('error')}" if event.get("error") else ""))
    return "Air780 短信网关事件\n" + json.dumps(event, ensure_ascii=False)


def deliver_feishu(url: str, event: dict, attempts: int = 3) -> bool:
    """Deliver a gateway event to a Feishu custom bot webhook."""
    if not url:
        return True
    body = json.dumps({"msg_type": "text", "content": {"text": _feishu_text(event)}},
                      ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                result = json.loads(response.read().decode("utf-8") or "{}")
                code = result.get("code", result.get("StatusCode", 0))
                if 200 <= response.status < 300 and code == 0:
                    return True
                log.warning("Feishu bot rejected event: %s", result.get("msg") or
                            result.get("StatusMessage") or code)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            log.warning("Feishu webhook attempt %d failed: %s", attempt + 1, exc)
        time.sleep(min(2 ** attempt, 4))
    return False


def deliver_dingtalk(url: str, secret: str, event: dict, attempts: int = 3) -> bool:
    """Deliver an event to a DingTalk custom bot, with optional signed requests."""
    body = json.dumps({"msgtype": "text", "text": {"content": _feishu_text(event)}},
                      ensure_ascii=False).encode("utf-8")
    for attempt in range(attempts):
        target = url
        if secret:
            timestamp = str(int(time.time() * 1000))
            signature = base64.b64encode(hmac.new(
                secret.encode(), f"{timestamp}\n{secret}".encode(), hashlib.sha256
            ).digest()).decode()
            parts = urlsplit(url)
            query = parse_qsl(parts.query, keep_blank_values=True)
            target = urlunsplit(parts._replace(query=urlencode(query + [
                ("timestamp", timestamp), ("sign", signature)])))
        request = urllib.request.Request(target, data=body, method="POST",
                                         headers={"Content-Type": "application/json; charset=utf-8"})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                result = json.loads(response.read().decode("utf-8") or "{}")
                if 200 <= response.status < 300 and result.get("errcode") == 0:
                    return True
                log.warning("DingTalk bot rejected event: %s", result.get("errmsg") or result.get("errcode"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            log.warning("DingTalk webhook attempt %d failed: %s", attempt + 1, exc)
        time.sleep(min(2 ** attempt, 4))
    return False
