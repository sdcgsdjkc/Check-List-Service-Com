import json
import sys

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QLabel, QListWidget, QProgressBar

from app.sysinfo import _powershell
from app.tests.base import BaseTestPage


class DriversWorker(QThread):
    done = pyqtSignal(object)

    def run(self):
        if sys.platform != "win32":
            self.done.emit(None)
            return
        try:
            raw = _powershell(
                'Get-CimInstance Win32_PnPEntity -Filter "ConfigManagerErrorCode<>0" | '
                "Select-Object Name, ConfigManagerErrorCode | ConvertTo-Json", timeout=60)
            if not raw:
                self.done.emit([])
                return
            data = json.loads(raw)
            if isinstance(data, dict):
                data = [data]
            self.done.emit(data)
        except Exception:
            self.done.emit(None)


class DriversPage(BaseTestPage):
    title = "Драйверы"
    auto = True
    hint = "Ожидайте, идет сканирование диспетчера устройств на наличие ошибок..."

    def build_body(self):
        self.busy = QProgressBar()
        self.busy.setRange(0, 0)
        self.busy.hide()
        self.info = QLabel("Сканирование не запускалось")
        self.problem_list = QListWidget()
        self.body.addWidget(self.busy)
        self.body.addWidget(self.info)
        self.body.addWidget(self.problem_list, 1)
        self.worker = None

    def on_enter(self):
        if self.worker is not None:
            return
        self.busy.show()
        self.info.setText("Опрос WMI (Win32_PnPEntity)...")
        self.set_status("идет проверка...")
        self.worker = DriversWorker(self)
        self.worker.done.connect(self.on_done)
        self.worker.start()

    def on_done(self, devices):
        self.busy.hide()
        if devices is None:
            self.info.setText("Автоматическая проверка недоступна (WMI не отвечает)")
            self.set_status("проверьте диспетчер устройств вручную", "warn")
            return
        if not devices:
            self.info.setText("Устройств с ошибками не найдено")
            self.summary = "ошибок нет"
            self.grade = "ok"
            self.auto_ok("ошибок в диспетчере устройств нет")
            return
        for device in devices:
            name = device.get("Name") or "Неизвестное устройство"
            code = device.get("ConfigManagerErrorCode")
            self.problem_list.addItem(f"{name} — код ошибки {code}")
        self.info.setText(f"Найдено проблемных устройств: {len(devices)}")
        self.details = f"устройств с ошибками: {len(devices)}"
        self.summary = f"проблемных устройств: {len(devices)}"
        self.grade = "bad"
        self.set_status(f"найдены ошибки драйверов ({len(devices)})", False)
