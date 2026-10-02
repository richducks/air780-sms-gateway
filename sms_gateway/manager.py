from __future__ import annotations

import glob
import logging
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
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
    parent_key: str
    generation: str
    online_since: float


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
        self._candidate_seen_since: dict[str, float] = {}
        self._generation_failures: dict[str, int] = {}
        self._generation_blocked_until: dict[str, float] = {}

        # USB links that flap can enumerate successfully for only a second or two.
        # Do not hand such a transient device to the SMS worker immediately.
        self._stable_window_seconds = 8.0
        self._stable_reset_seconds = 120.0
        self._backoff_base_seconds = 5.0
        self._backoff_max_seconds = 120.0

    @staticmethod
    def _port_number(port: str) -> int:
        match = re.search(r"(\d+)$", port)
        return int(match.group(1)) if match else -1

    @staticmethod
    def _air780_parent(port: str) -> str | None:
        """Return the physical Air780 USB sysfs node owning one tty port."""
        try:
            device = (Path("/sys/class/tty") / Path(port).name / "device").resolve()
        except OSError:
            return None
        for parent in (device, *device.parents):
            try:
                if ((parent / "idVendor").read_text().strip().lower() == "19d1"
                        and (parent / "idProduct").read_text().strip().lower() == "0001"):
                    return str(parent)
            except OSError:
                continue
        return None

    @staticmethod
    def _usb_generation(parent_key: str) -> str:
        """Return a token that changes whenever the physical USB device re-enumerates."""
        parent = Path(parent_key)
        try:
            devnum = (parent / "devnum").read_text().strip()
        except OSError:
            devnum = "unknown"
        return f"{parent_key}#{devnum}"

    @staticmethod
    def _backoff_seconds(failures: int, base: float = 5.0, maximum: float = 120.0) -> float:
        failures = max(1, failures)
        return min(maximum, base * (2 ** min(failures - 1, 8)))

    def _register_generation_failure(
            self, generation: str, parent_key: str, reason: str) -> float:
        failures = self._generation_failures.get(generation, 0) + 1
        self._generation_failures[generation] = failures
        delay = self._backoff_seconds(
            failures, self._backoff_base_seconds, self._backoff_max_seconds)
        self._generation_blocked_until[generation] = time.monotonic() + delay
        log.warning(
            "Air780 USB instance %s on %s unstable (%d failures); retry in %.0fs: %s",
            generation, parent_key, failures, delay, reason)
        return delay

    def _reset_generation_health(self, generation: str, parent_key: str) -> None:
        if self._generation_failures.pop(generation, None):
            log.info(
                "Air780 USB instance %s on %s stable again; failure backoff reset",
                generation, parent_key)
        self._generation_blocked_until.pop(generation, None)

    def _forget_generation(self, generation: str) -> None:
        self._candidate_seen_since.pop(generation, None)
        self._generation_failures.pop(generation, None)
        self._generation_blocked_until.pop(generation, None)

    def _ports(self) -> list[str]:
        if self.configured_port != "auto":
            return [self.configured_port]

        # Air780 exposes three ACM ports per physical USB device. The SMS VUART is
        # the highest-numbered ACM port for that device. Probe only that port so a
        # reconnect does not make the gateway open the modem's other control ports.
        acm_groups: dict[str, list[str]] = {}
        fallback: list[str] = []
        for port in glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*"):
            parent = self._air780_parent(port) if Path(port).name.startswith("ttyACM") else None
            if parent:
                acm_groups.setdefault(parent, []).append(port)
            else:
                fallback.append(port)
        preferred = [max(ports, key=self._port_number) for ports in acm_groups.values()]
        return sorted(preferred + fallback, key=self._port_number, reverse=True)

    def run(self) -> None:
        self.store.mark_all_devices_offline()
        while not self.stop_event.is_set():
            self._remove_offline()
            now = time.monotonic()
            claimed_ports = {d.port for d in self._devices.values() if d.worker.is_alive()}
            claimed_parents = {d.parent_key for d in self._devices.values() if d.worker.is_alive()}
            visible_generations: set[str] = set()

            for port in self._ports():
                parent_key = self._air780_parent(port) or port
                generation = self._usb_generation(parent_key) if parent_key != port else port
                visible_generations.add(generation)

                first_seen = self._candidate_seen_since.setdefault(generation, now)
                if now - first_seen < self._stable_window_seconds:
                    continue
                if port in claimed_ports or parent_key in claimed_parents:
                    continue
                if self._generation_blocked_until.get(generation, 0) > now:
                    continue
                self._probe(port, parent_key, generation)

            # A re-enumerated device gets a new generation token, so its stability
            # window starts over even if Linux reuses the same ttyACM number.
            known_generations = (
                set(self._candidate_seen_since)
                | set(self._generation_failures)
                | set(self._generation_blocked_until)
            )
            for generation in known_generations:
                if generation not in visible_generations:
                    self._forget_generation(generation)

            self.stop_event.wait(1)

    def _probe(self, port: str, parent_key: str, generation: str) -> None:
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
            runtime = RuntimeDevice(
                device_id, imei, port, worker, str(info.get("version", "")),
                parent_key, generation, time.monotonic())
            with self._lock:
                old = self._devices.get(device_id)
                if old and old.worker.is_alive():
                    modem.close()
                    return
                self._devices[device_id] = runtime
            self._reset_generation_health(generation, parent_key)
            self.store.upsert_device(device_id, imei, "online", port, runtime.firmware_version)
            worker.start()
            if self.on_state:
                self.on_state(device_id, "online", None)
            log.info("device %s online on %s (%s)", device_id, port, parent_key)
        except Exception as exc:
            modem.close()
            self._register_generation_failure(
                generation, parent_key, f"probe failed on {port}: {exc}")

    def _remove_offline(self) -> None:
        with self._lock:
            for device_id, runtime in list(self._devices.items()):
                if runtime.worker.is_alive():
                    online_age = time.monotonic() - runtime.online_since
                    if online_age >= self._stable_reset_seconds:
                        self._reset_generation_health(
                            runtime.generation, runtime.parent_key)
                    self.store.upsert_device(device_id, runtime.imei, "online", runtime.port,
                                             runtime.firmware_version, runtime.worker.last_error)
                    continue

                runtime.worker.modem.close()
                error = runtime.worker.last_error or "USB/serial worker stopped"
                online_age = time.monotonic() - runtime.online_since
                if online_age < self._stable_reset_seconds:
                    self._register_generation_failure(
                        runtime.generation, runtime.parent_key,
                        f"device {runtime.imei} dropped after {online_age:.1f}s: {error}")
                else:
                    # A single disconnect after a long healthy run gets only the
                    # minimum retry delay for this exact USB enumeration instance.
                    self._reset_generation_health(
                        runtime.generation, runtime.parent_key)
                    self._register_generation_failure(
                        runtime.generation, runtime.parent_key,
                        f"device {runtime.imei} disconnected after stable run: {error}")

                self.store.upsert_device(device_id, runtime.imei, "offline", None,
                                         runtime.firmware_version, error)
                if self.on_state:
                    self.on_state(device_id, "offline", error)
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
