import psutil
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QListWidget

from app.tests.base import BaseTestPage


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
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)

    def reset_state(self):
        self.log.clear()
        self.cycles = 0
        self.known = None
        self.ac_seen = False
        self.usb_label.setText("Циклы USB: 0")
        self.ac_label.setText("Зарядка: —")

    def on_enter(self):
        self.timer.start(700)
        self.set_status("идет мониторинг портов и питания...")

    def on_leave(self):
        self.timer.stop()

    def poll(self):
        battery = psutil.sensors_battery()
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
        try:
            current = {p.device for p in psutil.disk_partitions(all=False)
                       if "removable" in p.opts.lower()}
        except Exception:
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
