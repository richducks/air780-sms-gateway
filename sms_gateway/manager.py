from __future__ import annotations

import glob
import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable

from .modem import ModemWorker, ReceivedSms, SerialModem
from .store import MessageStore

log = logging.getLogger(__name__)


@dataclass
class RuntimeDevice:
    device_id: str
    imei: str
    port: str
    worker: ModemWorker
    firmware_version: str


class DeviceManager(threading.Thread):
    """Discovers every LuatOS bridge and keeps one worker per IMEI."""

    def __init__(self, store: MessageStore, baudrate: int, poll_seconds: int,
                 configured_port: str, on_receive: Callable[[str, ReceivedSms], None],
                 on_sent: Callable[[int, bool, str | None], None],
                 on_state: Callable[[str, str, str | None], None] | None = None,
                 send_attempts: int = 3):
        super().__init__(name="device-manager", daemon=True)
        self.store = store
        self.baudrate = baudrate
        self.poll_seconds = max(1, poll_seconds)
        self.configured_port = configured_port
        self.on_receive = on_receive
        self.on_sent = on_sent
        self.on_state = on_state
        self.send_attempts = max(1, send_attempts)
        self.stop_event = threading.Event()
        self._lock = threading.RLock()
        self._devices: dict[str, RuntimeDevice] = {}
        self._rejected_until: dict[str, float] = {}

    def _ports(self) -> list[str]:
        if self.configured_port != "auto":
            return [self.configured_port]
        return sorted(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*"), reverse=True)

    def run(self) -> None:
        self.store.mark_all_devices_offline()
        while not self.stop_event.is_set():
            self._remove_offline()
            claimed = {d.port for d in self._devices.values() if d.worker.is_alive()}
            for port in self._ports():
                if port in claimed or self._rejected_until.get(port, 0) > time.monotonic():
                    continue
                self._probe(port)
            self.stop_event.wait(3)

    def _probe(self, port: str) -> None:
        modem = SerialModem(port, self.baudrate)
        try:
            modem.connect()
            info = modem.device_info
            imei = str(info.get("imei", "")).strip()
            if not imei:
                raise RuntimeError("bridge did not report IMEI")
            device_id = "air780-" + imei
            worker = ModemWorker(
                modem, self.poll_seconds,
                lambda sms, did=device_id: self.on_receive(did, sms),
                False, reconnect=False, send_attempts=self.send_attempts,
            )
            runtime = RuntimeDevice(device_id, imei, port, worker, str(info.get("version", "")))
            with self._lock:
                old = self._devices.get(device_id)
                if old and old.worker.is_alive():
                    modem.close()
                    return
                self._devices[device_id] = runtime
            self.store.upsert_device(device_id, imei, "online", port, runtime.firmware_version)
            worker.start()
            if self.on_state:
                self.on_state(device_id, "online", None)
            log.info("device %s online on %s", device_id, port)
        except Exception as exc:
            modem.close()
            self._rejected_until[port] = time.monotonic() + 30
            log.debug("port %s is not an SMS bridge: %s", port, exc)

    def _remove_offline(self) -> None:
        with self._lock:
            for device_id, runtime in list(self._devices.items()):
                if runtime.worker.is_alive():
                    self.store.upsert_device(device_id, runtime.imei, "online", runtime.port,
                                             runtime.firmware_version, runtime.worker.last_error)
                    continue
                runtime.worker.modem.close()
                self.store.upsert_device(device_id, runtime.imei, "offline", None,
                                         runtime.firmware_version, runtime.worker.last_error)
                if self.on_state:
                    self.on_state(device_id, "offline", runtime.worker.last_error)
                del self._devices[device_id]

    def online(self) -> list[RuntimeDevice]:
        with self._lock:
            return [d for d in self._devices.values() if d.worker.is_alive() and d.worker.connected]

    def select(self, device_id: str | None = None) -> RuntimeDevice:
        devices = self.online()
        if device_id:
            selected = next((d for d in devices if d.device_id == device_id), None)
            if not selected:
                raise ValueError("selected device is offline or unknown")
        else:
            if len(devices) != 1:
                raise ValueError("device_id is required unless exactly one device is online")
            selected = devices[0]
        return selected

    def send(self, message_id: int, device_id: str | None, phone: str, body: str) -> str:
        selected = self.select(device_id)
        selected.worker.enqueue(message_id, phone, body, self.on_sent)
        return selected.device_id

    def stop(self) -> None:
        self.stop_event.set()
        with self._lock:
            for runtime in self._devices.values():
                runtime.worker.stop_event.set()
                runtime.worker.modem.close()
