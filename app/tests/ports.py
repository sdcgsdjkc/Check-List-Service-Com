import time

import psutil
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QListWidget

from app.tests.base import BaseTestPage


class PortsWorker(QThread):
    sample = pyqtSignal(object, object)  # battery, removable set (или None при ошибке)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._run = True

    def stop(self):
        self._run = False
        self.wait(1500)

    def run(self):
        while self._run:
            try:
                battery = psutil.sensors_battery()
            except Exception:
                battery = None
            try:
                removable = {p.device for p in psutil.disk_partitions(all=False)
                             if "removable" in p.opts.lower()}
            except Exception:
                removable = None
            self.sample.emit(battery, removable)
            for _ in range(7):
                if not self._run:
                    return
                time.sleep(0.1)


class PortsPage(BaseTestPage):
    title = "Разъемы (USB и зарядка)"
    hint = ("Подключите зарядное устройство (для ноутбука), затем по очереди вставляйте флешку "
            "во ВСЕ USB-порты устройства.")

    def build_body(self):
        row = QHBoxLayout()
        self.ac_label = QLabel("Зарядка: —")
        self.ac_label.setObjectName("bigValue")
        self.usb_label = QLabel("Циклы USB: 0")
        self.usb_label.setObjectName("bigValue")
        row.addWidget(self.ac_label)
        row.addStretch(1)
        row.addWidget(self.usb_label)
        self.body.addLayout(row)
        self.log = QListWidget()
        self.body.addWidget(self.log, 1)
        self.known = None
        self.cycles = 0
        self.ac_seen = False
        self.worker = None

    def reset_state(self):
        self.log.clear()
        self.cycles = 0
        self.known = None
        self.ac_seen = False
        self.usb_label.setText("Циклы USB: 0")
        self.ac_label.setText("Зарядка: —")

    def on_enter(self):
        if self.worker is None:
            self.worker = PortsWorker(self)
            self.worker.sample.connect(self.on_sample)
        if not self.worker.isRunning():
            self.worker._run = True
            self.worker.start()
        self.set_status("идет мониторинг портов и питания...")

    def on_leave(self):
        if self.worker is not None and self.worker.isRunning():
            self.worker.stop()

    def on_sample(self, battery, current):
        if battery is None:
            self.ac_label.setText("Питание: батарея не обнаружена")
            self.ac_label.setStyleSheet("color:#9aa7b4;")
        elif battery.power_plugged:
            self.ac_seen = True
            self.ac_label.setText("Зарядка: ПОДКЛЮЧЕНА")
            self.ac_label.setStyleSheet("color:#66bb6a;font-weight:700;")
        else:
            self.ac_label.setText(f"Зарядка: от батареи ({battery.percent:.0f}%)")
            self.ac_label.setStyleSheet("color:#ffb74d;font-weight:700;")
        if current is None:
            return
        if self.known is None:
            self.known = current
            return
        for device in sorted(current - self.known):
            self.log.insertItem(0, f"[+] Подключен накопитель: {device}")
        for device in sorted(self.known - current):
            self.cycles += 1
            self.log.insertItem(0, f"[-] Извлечен накопитель: {device} (цикл №{self.cycles})")
        self.known = current
        self.usb_label.setText(f"Циклы USB: {self.cycles}")
        self.details = (f"циклов USB: {self.cycles}, "
                        f"зарядка: {'фиксировалась' if self.ac_seen else 'не фиксировалась'}")
