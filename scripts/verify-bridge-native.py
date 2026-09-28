#!/usr/bin/env python3
"""Verify the Air780 VUART bridge using only the Python standard library."""
import glob
import json
import os
import select
import sys
import termios
import time


def probe(port: str):
    fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        attrs = termios.tcgetattr(fd)
        attrs[0] = 0
        attrs[1] = 0
        attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
        attrs[3] = 0
        attrs[4] = termios.B115200
        attrs[5] = termios.B115200
        attrs[6][termios.VMIN] = 0
        attrs[6][termios.VTIME] = 1
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        termios.tcflush(fd, termios.TCIOFLUSH)
        os.write(fd, b'{"type":"ping"}\n')
        deadline = time.monotonic() + 4
        buffer = bytearray()
        while time.monotonic() < deadline:
            readable, _, _ = select.select([fd], [], [], 0.25)
            if not readable:
                continue
            try:
                buffer.extend(os.read(fd, 4096))
            except BlockingIOError:
                continue
            while b"\n" in buffer:
                raw, _, rest = buffer.partition(b"\n")
                buffer = bytearray(rest)
                try:
                    frame = json.loads(raw.decode("utf-8", errors="strict"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if not isinstance(frame, dict):
                    continue
                if (frame.get("project") == "air780_usb_sms_bridge"
                        and frame.get("type") in ("pong", "ready")):
                    return frame
    finally:
        os.close(fd)
    return None


def main() -> int:
    ports = sorted(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*"), reverse=True)
    errors = []
    for port in ports:
        try:
            frame = probe(port)
            if frame:
                print(json.dumps({"ok": True, "port": port, "device": frame}, ensure_ascii=False))
                return 0
        except (OSError, termios.error) as exc:
            errors.append(f"{port}: {exc}")
    print(json.dumps({"ok": False, "error": "Air780 SMS bridge not found",
                      "ports": ports, "details": errors}, ensure_ascii=False), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
