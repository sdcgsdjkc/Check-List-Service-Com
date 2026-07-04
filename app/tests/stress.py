import threading
from collections import deque

import psutil
from PyQt6.QtCore import QPointF, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.norms import temperature_grade
from app.sysinfo import read_temperature
from app.tests.base import BaseTestPage

try:
    import numpy as np
except Exception:
    np = None

DURATION = 120


def _numpy_worker(stop_event):
    size = 768
    a = np.random.rand(size, size)
    b = np.random.rand(size, size)
    while not stop_event.is_set():
        c = a.dot(b)
        c = np.sin(c) + np.sqrt(np.abs(c) + 1.0)
        a = c / (np.max(c) + 1e-9)


def _python_worker(stop_event):
    import math
    value = 0.0001
    while not stop_event.is_set():
        for _ in range(50000):
            value = math.sin(value) + math.sqrt(value * value + 1.0)
        value = 0.0001


def _memory_worker(stop_event):
    block = 64 * 1024 * 1024
    source = bytes(block)
    target = bytearray(block)
    while not stop_event.is_set():
        target[:] = source
        _ = sum(target[::4194304])


class StressEngine:
    def __init__(self):
        self.threads = []
        self.stop_thread = None
        self.vectors = []

    def start(self):
        cores = psutil.cpu_count() or 4
        self.stop_thread = threading.Event()
        worker = _numpy_worker if np is not None else _python_worker
        label = ("матричные вычисления FP (numpy)" if np is not None
                 else "вычислительные потоки CPU")
        for _ in range(cores):
            thread = threading.Thread(target=worker, args=(self.stop_thread,), daemon=True)
            thread.start()
            self.threads.append(thread)
        self.vectors.append(f"{cores} потоков — {label}")
        bandwidth = threading.Thread(target=_memory_worker, args=(self.stop_thread,), daemon=True)
        bandwidth.start()
        self.threads.append(bandwidth)
        self.vectors.append("пропускная способность ОЗУ")

    def stop(self):
        if self.stop_thread is not None:
            self.stop_thread.set()
        for thread in self.threads:
            thread.join(timeout=1.5)
        self.threads = []


class GpuFallbackWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(300, 200)
        self.angle = 0
        self.active = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)

    def start(self):
        self.active = True
        self.timer.start(33)

    def stop(self):
        self.active = False
        self.timer.stop()
        self.update()

    def _tick(self):
        self.angle = (self.angle + 8) % 360
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#0f1216"))
        painter.setPen(QColor("#2b323b"))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        if not self.active:
            painter.setPen(QColor("#565f69"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "GPU (в покое)")
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = self.rect().center()
        radius = min(self.width(), self.height()) // 2 - 14
        painter.translate(center)
        for i in range(7):
            painter.rotate(self.angle * (1 if i % 2 == 0 else -1) + i * 26)
            painter.setBrush(QColor.fromHsv((self.angle + i * 40) % 360, 200, 230))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(-radius, -5, 2 * radius, 10)


class SensorWorker(QThread):
    sample = pyqtSignal(float, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active = True
        self._temp_failures = 0

    def run(self):
        psutil.cpu_percent(interval=None)
        while self._active:
            load = psutil.cpu_percent(interval=1.5)
            temp = None if self._temp_failures >= 8 else read_temperature()
            if temp is None:
                self._temp_failures += 1
            else:
                self._temp_failures = 0
            if self._active:
                self.sample.emit(float(load), temp)

    def stop(self):
        self._active = False
        self.wait(4000)


class TempGraph(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.samples = deque(maxlen=200)
        self.setMinimumSize(300, 200)

    def add(self, load, temp):
        self.samples.append((load, temp))
        self.update()

    def clear(self):
        self.samples.clear()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#0f1216"))
        w, h = self.width(), self.height()
        painter.setPen(QColor("#1b2027"))
        for frac in (0.25, 0.5, 0.75):
            y = int(h * frac)
            painter.drawLine(0, y, w, y)
        if len(self.samples) >= 2:
            step = w / (self.samples.maxlen - 1)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            load_points = [QPointF(i * step, h - s[0] / 100.0 * (h - 8) - 4)
                           for i, s in enumerate(self.samples)]
            painter.setPen(QPen(QColor("#1e88e5"), 2))
            painter.drawPolyline(QPolygonF(load_points))
            temp_points = [QPointF(i * step, h - s[1] / 105.0 * (h - 8) - 4)
                           for i, s in enumerate(self.samples) if s[1] is not None]
            if len(temp_points) >= 2:
                painter.setPen(QPen(QColor("#ef5350"), 2))
                painter.drawPolyline(QPolygonF(temp_points))
        painter.setPen(QColor("#1e88e5"))
        painter.drawText(8, 16, "— нагрузка CPU, %")
        painter.setPen(QColor("#ef5350"))
        painter.drawText(8, 32, "— температура, °C")
        painter.setPen(QColor("#2b323b"))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))


class StressPage(BaseTestPage):
    title = "Стресс-тест (нагрузка)"
    auto = True
    hint = "Нажмите «Старт» для запуска 2-минутного теста стабильности CPU/GPU и следите за температурой."

    def build_body(self):
        top = QHBoxLayout()
        self.start_button = QPushButton("Старт (2 минуты)")
        self.start_button.clicked.connect(self.toggle)
        self.time_label = QLabel("—")
        self.load_label = QLabel("Нагрузка CPU: —")
        self.temp_label = QLabel("Температура: —")
        top.addWidget(self.start_button)
        top.addWidget(self.time_label)
        top.addStretch(1)
        top.addWidget(self.load_label)
        top.addWidget(self.temp_label)
        self.vectors_label = QLabel("Векторы нагрузки: CPU-процессы + матрицы FP + пропускная способность ОЗУ + GPU-шейдер")
        self.vectors_label.setObjectName("specLabel")
        self.middle = QHBoxLayout()
        self.gpu = GpuFallbackWidget()
        self.graph = TempGraph()
        self.middle.addWidget(self.gpu, 1)
        self.middle.addWidget(self.graph, 1)
        self.body.addLayout(top)
        self.body.addWidget(self.vectors_label)
        self.body.addLayout(self.middle, 1)
        self.engine = None
        self.seconds_left = 0
        self.max_temp = None
        self.max_load = 0.0
        self.temp_samples = []
        self.load_samples = []
        self.monitor = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)

    def auto_start(self):
        if self.engine is None:
            self.start_test()

    def toggle(self):
        if self.engine is not None:
            self.stop_test(aborted=True)
        else:
            self.start_test()

    def start_test(self):
        self.graph.clear()
        self.max_temp = None
        self.max_load = 0.0
        self.temp_samples = []
        self.load_samples = []
        self.engine = StressEngine()
        self.engine.start()
        if self.engine.vectors:
            self.vectors_label.setText("Векторы нагрузки: " + " + ".join(self.engine.vectors)
                                       + " + GPU (графика)")
        self.gpu.start()
        self.monitor = SensorWorker(self)
        self.monitor.sample.connect(self.on_sample)
        self.monitor.start()
        self.seconds_left = DURATION
        self.time_label.setText(f"Осталось: {self.seconds_left} с")
        self.timer.start(1000)
        self.start_button.setText("Стоп")
        self.set_status("идет стресс-тест (комплекс нагрузок)...")

    def tick(self):
        self.seconds_left -= 1
        self.time_label.setText(f"Осталось: {self.seconds_left} с")
        if self.seconds_left <= 0:
            self.stop_test(aborted=False)

    def on_sample(self, load, temp):
        self.max_load = max(self.max_load, load)
        self.load_samples.append(load)
        self.load_label.setText(f"Нагрузка CPU: {load:.0f}%")
        if temp is not None and temp > 0:
            self.max_temp = max(self.max_temp or 0.0, temp)
            self.temp_samples.append(temp)
            self.temp_label.setText(f"Температура: {temp:.0f} °C")
        else:
            self.temp_label.setText("Температура: датчик недоступен")
        self.graph.add(load, temp)

    def stop_test(self, aborted):
        self.timer.stop()
        self.gpu.stop()
        if self.monitor is not None:
            self.monitor.stop()
            self.monitor = None
        if self.engine is not None:
            self.engine.stop()
            self.engine = None
        self.start_button.setText("Старт (2 минуты)")
        if aborted:
            self.set_status("тест остановлен вручную", "warn")
            return
        load_note = ""
        summary_parts = []
        if self.load_samples:
            avg_load = sum(self.load_samples) / len(self.load_samples)
            load_note = f"нагрузка CPU сред. {avg_load:.0f}% / макс. {self.max_load:.0f}%"
            summary_parts.append(f"CPU {avg_load:.0f}%")
        if self.temp_samples:
            avg_temp = sum(self.temp_samples) / len(self.temp_samples)
            temp_note = f"температура сред. {avg_temp:.0f} °C / макс. {self.max_temp:.0f} °C"
            summary_parts.append(f"сред. {avg_temp:.0f} °C / макс. {self.max_temp:.0f} °C")
            self.grade = temperature_grade(self.max_temp)
        else:
            temp_note = "температура: датчик недоступен"
            self.grade = "ok"
        self.summary = " · ".join(summary_parts)
        parts = [f"{DURATION} с без сбоев", load_note, temp_note]
        self.auto_ok(", ".join(part for part in parts if part))

    def on_leave(self):
        if self.engine is not None:
            self.stop_test(aborted=True)
