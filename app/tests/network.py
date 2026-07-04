import subprocess
import sys

import psutil
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QLabel, QListWidget, QProgressBar

from app.sysinfo import CREATE_NO_WINDOW
from app.tests.base import BaseTestPage


class NetworkWorker(QThread):
    done = pyqtSignal(list, bool, str)

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
        self.done.emit(interfaces, ok, note)


class NetworkPage(BaseTestPage):
    title = "Wi-Fi / LAN"
    hint = "Ожидайте автоматической проверки сетевых адаптеров и пинга..."

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

    def on_enter(self):
        if self.worker is not None:
            return
        self.busy.show()
        self.info.setText("Опрос адаптеров и пинг 8.8.8.8...")
        self.set_status("идет проверка сети...")
        self.worker = NetworkWorker(self)
        self.worker.done.connect(self.on_done)
        self.worker.start()

    def on_done(self, interfaces, ok, note):
        self.busy.hide()
        for interface in interfaces:
            self.iface_list.addItem(interface)
        self.info.setText(f"Активных адаптеров: {len(interfaces)}. {note}")
        if ok and interfaces:
            self.auto_ok(f"адаптеров: {len(interfaces)}; {note}")
        elif not interfaces:
            self.details = "активные сетевые адаптеры не найдены"
            self.set_status("активные адаптеры не найдены", False)
        else:
            self.details = note
            self.set_status(note, False)
