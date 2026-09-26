#!/usr/bin/env bash
set -euo pipefail

python3 - <<'PY'
import secrets
print("SMS_GATEWAY_API_TOKEN=" + secrets.token_urlsafe(32))
print("SMS_GATEWAY_WEBHOOK_SECRET=" + secrets.token_urlsafe(32))
PY
