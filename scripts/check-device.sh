#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

python3 - <<'PY'
import glob, json, serial, time

for port in sorted(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*"), reverse=True):
    try:
        with serial.Serial(port, 115200, timeout=0.2, write_timeout=1) as device:
            device.reset_input_buffer()
            device.write(b'{"type":"ping"}\n')
            deadline = time.monotonic() + 3
            data = bytearray()
            while time.monotonic() < deadline:
                data.extend(device.read(512))
                for line in data.splitlines():
                    try:
                        frame = json.loads(line)
                    except Exception:
                        continue
                    if frame.get("project") == "air780_usb_sms_bridge":
                        print(json.dumps({"ok": True, "port": port, "device": frame}, ensure_ascii=False))
                        raise SystemExit(0)
    except Exception:
        pass
print(json.dumps({"ok": False, "error": "Air780 SMS bridge not found"}))
raise SystemExit(1)
PY

