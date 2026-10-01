from __future__ import annotations

import os
from dataclasses import dataclass


def _int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value else default


@dataclass(frozen=True)
class Settings:
    bind_host: str = os.getenv("SMS_GATEWAY_HOST", "127.0.0.1")
    bind_port: int = _int("SMS_GATEWAY_PORT", 8787)
    api_token: str = os.getenv("SMS_GATEWAY_API_TOKEN", "")
    admin_password: str = os.getenv("SMS_GATEWAY_ADMIN_PASSWORD", "admin")
    webhook_url: str = os.getenv("SMS_GATEWAY_WEBHOOK_URL", "")
    webhook_secret: str = os.getenv("SMS_GATEWAY_WEBHOOK_SECRET", "")
    feishu_webhook_url: str = os.getenv("SMS_GATEWAY_FEISHU_WEBHOOK_URL", "")
    database_path: str = os.getenv("SMS_GATEWAY_DB", "sms_gateway.db")
    serial_port: str = os.getenv("SMS_GATEWAY_SERIAL_PORT", "auto")
    serial_baudrate: int = _int("SMS_GATEWAY_SERIAL_BAUDRATE", 115200)
    poll_seconds: int = _int("SMS_GATEWAY_POLL_SECONDS", 3)
    send_attempts: int = _int("SMS_GATEWAY_SEND_ATTEMPTS", 3)
    delete_after_receive: bool = os.getenv("SMS_GATEWAY_DELETE_AFTER_RECEIVE", "true").lower() in {
        "1", "true", "yes", "on"
    }
