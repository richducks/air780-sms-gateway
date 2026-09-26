from __future__ import annotations

import glob
import json
import logging
import queue
import re
import threading
import time
from dataclasses import dataclass
from typing import Callable

import serial

log = logging.getLogger(__name__)


class ModemError(RuntimeError):
    pass


@dataclass
class ReceivedSms:
    index: int
    sender: str
    body: str


class SerialModem:
    """JSON-lines client for the LuatOS VUART SMS bridge."""

    def __init__(self, configured_port: str, baudrate: int = 115200):
        self.configured_port = configured_port
        self.baudrate = baudrate
        self.port: str | None = None
        self.serial: serial.Serial | None = None
        self._lock = threading.RLock()
        self._buffer = bytearray()
        self._received: list[ReceivedSms] = []
        self._results: dict[str, dict] = {}
        self.device_info: dict = {}
        self._receive_sequence = int(time.time() * 1000)

    def _candidates(self) -> list[str]:
        if self.configured_port != "auto":
            return [self.configured_port]
        # VUART is normally the highest numbered ACM port on Air780EPM.
        return sorted(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*"), reverse=True)

    def connect(self) -> str:
        self.close()
        errors: list[str] = []
        for port in self._candidates():
            try:
                candidate = serial.Serial(port, self.baudrate, timeout=0.15, write_timeout=2)
                candidate.reset_input_buffer()
                self.serial, self.port = candidate, port
                self._buffer.clear()
                self._write({"type": "ping"})
                deadline = time.monotonic() + 2.5
                while time.monotonic() < deadline:
                    for frame in self._read_frames():
                        if (frame.get("type") == "pong"
                                and frame.get("project") == "air780_usb_sms_bridge"
                                and frame.get("imei")):
                            self.device_info = {**self.device_info, **frame}
                            log.info("connected to LuatOS SMS bridge on %s", port)
                            return port
                        self._dispatch(frame)
                candidate.close()
                self.serial, self.port = None, None
                errors.append(f"{port}: no SMS bridge response")
            except (OSError, serial.SerialException) as exc:
                self.close()
                errors.append(f"{port}: {exc}")
        raise ModemError("cannot find LuatOS SMS bridge; " + "; ".join(errors or ["no serial ports found"]))

    def close(self) -> None:
        if self.serial:
            try:
                self.serial.close()
            finally:
                self.serial, self.port = None, None
        self._buffer.clear()

    def _write(self, frame: dict) -> None:
        if not self.serial or not self.serial.is_open:
            raise ModemError("SMS bridge is not connected")
        data = json.dumps(frame, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"
        self.serial.write(data)
        self.serial.flush()

    def _read_frames(self) -> list[dict]:
        if not self.serial or not self.serial.is_open:
            raise ModemError("SMS bridge is not connected")
        chunk = self.serial.read(1024)
        if chunk:
            self._buffer.extend(chunk)
        frames: list[dict] = []
        while b"\n" in self._buffer:
            raw, _, remaining = self._buffer.partition(b"\n")
            self._buffer = bytearray(remaining)
            try:
                frame = json.loads(raw.decode("utf-8").strip())
                if isinstance(frame, dict):
                    frames.append(frame)
            except (UnicodeDecodeError, json.JSONDecodeError):
                log.debug("ignored non-bridge serial data")
        if len(self._buffer) > 65536:
            self._buffer.clear()
        return frames

    def _dispatch(self, frame: dict) -> None:
        kind = frame.get("type")
        if kind == "sms_received":
            self._receive_sequence += 1
            self._received.append(ReceivedSms(
                self._receive_sequence, str(frame.get("phone", "")), str(frame.get("body", ""))
            ))
        elif kind == "sms_result":
            self._results[str(frame.get("id", ""))] = frame
        elif kind in ("pong", "ready"):
            self.device_info = {**self.device_info, **frame}

    def send_sms(self, phone: str, body: str) -> str:
        if not re.fullmatch(r"\+?[0-9]{5,20}", phone):
            raise ValueError("phone must contain 5-20 digits with optional leading +")
        request_id = str(time.time_ns())
        with self._lock:
            self._write({"type": "sms_send", "id": request_id, "phone": phone, "body": body})
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                for frame in self._read_frames():
                    self._dispatch(frame)
                result = self._results.pop(request_id, None)
                if result is not None:
                    if result.get("ok"):
                        return "sent"
                    raise ModemError(str(result.get("error", "send failed")))
            raise ModemError("timeout waiting for LuatOS SMS result")

    def unread(self) -> list[ReceivedSms]:
        with self._lock:
            for frame in self._read_frames():
                self._dispatch(frame)
            result, self._received = self._received, []
            return result

    def delete(self, index: int) -> None:
        # LuatOS invokes the callback once and manages modem storage itself.
        return None


class ModemWorker(threading.Thread):
    def __init__(self, modem: SerialModem, poll_seconds: int,
                 on_receive: Callable[[ReceivedSms], None], delete_after_receive: bool,
                 reconnect: bool = True):
        super().__init__(name="modem-worker", daemon=True)
        self.modem = modem
        self.poll_seconds = max(1, poll_seconds)
        self.on_receive = on_receive
        self.outbox: queue.Queue[tuple[int, str, str, Callable[[int, bool, str | None], None]]] = queue.Queue()
        self.stop_event = threading.Event()
        self.last_error: str | None = None
        self.reconnect = reconnect

    @property
    def connected(self) -> bool:
        return bool(self.modem.serial and self.modem.serial.is_open)

    def enqueue(self, message_id: int, phone: str, body: str,
                callback: Callable[[int, bool, str | None], None]) -> None:
        self.outbox.put((message_id, phone, body, callback))

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                if not self.connected:
                    if not self.reconnect:
                        break
                    self.modem.connect()
                self._send_pending()
                for sms in self.modem.unread():
                    self.on_receive(sms)
                self.last_error = None
            except Exception as exc:
                self.last_error = str(exc)
                log.warning("SMS bridge cycle failed: %s", exc)
                self.modem.close()
                if not self.reconnect:
                    break
            self.stop_event.wait(self.poll_seconds)

    def _send_pending(self) -> None:
        while True:
            try:
                message_id, phone, body, callback = self.outbox.get_nowait()
            except queue.Empty:
                return
            try:
                self.modem.send_sms(phone, body)
                callback(message_id, True, None)
            except Exception as exc:
                callback(message_id, False, str(exc))
            finally:
                self.outbox.task_done()
