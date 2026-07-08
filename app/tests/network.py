import json
import subprocess
import sys

import psutil
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QLabel, QListWidget, QProgressBar

from app.sysinfo import CREATE_NO_WINDOW, _powershell
from app.tests.base import BaseTestPage


def _bluetooth_windows():
    if sys.platform != "win32":
        return {"skip": True}
    try:
        raw = _powershell(
            "Get-PnpDevice -Class Bluetooth -PresentOnly -ErrorAction Stop | "
            "Select-Object FriendlyName, Status | ConvertTo-Json")
        data = json.loads(raw) if raw else []
        if isinstance(data, dict):
            data = [data]
        if not data:
            return {"present": False}
        names = [((d.get("FriendlyName") or "устройство").strip(), (d.get("Status") or "?"))
                 for d in data]
        problems = [name for name, status in names if status != "OK"]
        return {"present": True, "names": names, "problems": problems}
    except Exception as exc:
        return {"present": False, "error": str(exc)}


class NetworkWorker(QThread):
    done = pyqtSignal(list, bool, str, object)

    def run(self):
        interfaces = []
        try:
            for name, stats in psutil.net_if_stats().items():
                low = name.lower()
                if not stats.isup or "loopback" in low or low == "lo" or low.startswith("lo0"):
                    continue
                wireless = any(marker in low for marker in ("wi-fi", "wlan", "wireless", "беспровод"))
                kind = "Wi-Fi" if wireless else "LAN / другое"
                speed = f", {stats.speed} Мбит/с" if stats.speed else ""
                interfaces.append(f"{name} ({kind}{speed})")
        except Exception:
            pass
        if sys.platform == "win32":
            command = ["ping", "-n", "2", "-w", "1500", "8.8.8.8"]
        else:
            command = ["ping", "-c", "2", "-W", "2", "8.8.8.8"]
        ok = False
        note = ""
        try:
            result = subprocess.run(command, capture_output=True, timeout=15,
                                    creationflags=CREATE_NO_WINDOW)
            ok = result.returncode == 0
            note = "пинг 8.8.8.8: успешно" if ok else "пинг 8.8.8.8: нет ответа"
        except Exception as exc:
            note = f"пинг не выполнен: {exc}"
        self.done.emit(interfaces, ok, note, _bluetooth_windows())


class NetworkPage(BaseTestPage):
    title = "Wi-Fi / LAN / Bluetooth"
    auto = True
    hint = "Ожидайте автоматической проверки сетевых адаптеров, пинга и Bluetooth..."

    def build_body(self):
        self.busy = QProgressBar()
        self.busy.setRange(0, 0)
        self.busy.hide()
        self.info = QLabel("Проверка не запускалась")
        self.iface_list = QListWidget()
        self.body.addWidget(self.busy)
        self.body.addWidget(self.info)
        self.body.addWidget(self.iface_list, 1)
        self.worker = None

    def reset_state(self):
        self.iface_list.clear()
        self.info.setText("Проверка не запускалась")

    def on_enter(self):
        if self.worker is not None:
            return
        self.busy.show()
        self.info.setText("Опрос адаптеров, пинг 8.8.8.8 и Bluetooth...")
        self.set_status("идет проверка сети...")
        self.worker = NetworkWorker(self)
        self.worker.done.connect(self.on_done)
        self.worker.start()

    def _apply_bluetooth(self, bt):
        # добавляет строки в список, возвращает (текст для сводки, состояние: ok/warn/none/"")
        if not bt or bt.get("skip"):
            return "", ""
        if not bt.get("present"):
            self.iface_list.addItem("Bluetooth: адаптер не обнаружен")
            return "Bluetooth: не обнаружен", "none"
        for name, status in bt.get("names", []):
            mark = "OK" if status == "OK" else f"⚠ {status}"
            self.iface_list.addItem(f"Bluetooth: {name} — {mark}")
        if bt.get("problems"):
            return "Bluetooth: ошибка драйвера", "warn"
        count = len(bt.get("names", []))
        return f"Bluetooth: OK ({count} устр.)", "ok"

    def on_done(self, interfaces, ok, note, bt):
        self.busy.hide()
        for interface in interfaces:
            self.iface_list.addItem(interface)
        bt_text, bt_state = self._apply_bluetooth(bt)
        summary_bt = f" · {bt_text}" if bt_text else ""
        detail_bt = f"; {bt_text}" if bt_text else ""
        self.info.setText(f"Активных адаптеров: {len(interfaces)}. {note}"
                          + (f". {bt_text}" if bt_text else ""))
        if not interfaces:
            self.details = "активные сетевые адаптеры не найдены" + detail_bt
            self.summary = "адаптеры не найдены" + summary_bt
            self.grade = "bad"
            self.set_status("активные адаптеры не найдены", False)
            return
        if ok:
            self.grade = "warn" if bt_state == "warn" else "ok"
            self.summary = f"адаптеров: {len(interfaces)} · интернет есть" + summary_bt
            if bt_state == "warn":
                self.details = f"адаптеров: {len(interfaces)}; {note}{detail_bt}"
                self.set_status(f"сеть в порядке, но {bt_text.lower()}", "warn")
            else:
                self.auto_ok(f"адаптеров: {len(interfaces)}; {note}{detail_bt}")
        else:
            self.details = note + detail_bt
            self.summary = f"адаптеров: {len(interfaces)} · нет интернета" + summary_bt
            self.grade = "warn"
            self.set_status(note, False)
