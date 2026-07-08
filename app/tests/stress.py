import threading
from collections import deque

import psutil
from PyQt6.QtCore import QPointF, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from app import theme
from app.norms import temperature_grade
from app.sysinfo import read_temperature
from app.temperature import read_gpu
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


VERTEX_SHADER = (
    "#version 330 core\n"
    "void main() {\n"
    "  vec2 p = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2));\n"
    "  gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);\n"
    "}\n"
)

FRAGMENT_SHADER = (
    "#version 330 core\n"
    "uniform float uTime;\n"
    "uniform vec2 uRes;\n"
    "out vec4 fragColor;\n"
    "void main() {\n"
    "  vec2 uv = gl_FragCoord.xy / uRes;\n"
    "  float v = 0.0;\n"
    "  for (int i = 0; i < 500; i++) {\n"
    "    float fi = float(i);\n"
    "    v += sin(uv.x * 42.0 + uTime + fi) * cos(uv.y * 42.0 - uTime - fi);\n"
    "    v = fract(v * 1.37 + 0.11);\n"
    "  }\n"
    "  fragColor = vec4(v, uv.x * 0.7 + v * 0.3, uv.y, 1.0);\n"
    "}\n"
)


def make_gpu_widget():
    try:
        from PyQt6.QtOpenGLWidgets import QOpenGLWidget
        from PyQt6.QtOpenGL import QOpenGLShader, QOpenGLShaderProgram, QOpenGLVertexArrayObject
        from PyQt6.QtGui import QSurfaceFormat, QVector2D
        from OpenGL.GL import (glClear, glClearColor, glDrawArrays, glViewport,
                               GL_COLOR_BUFFER_BIT, GL_TRIANGLES)
        try:
            from OpenGL.GL import glGetGraphicsResetStatus, GL_NO_ERROR
        except Exception:
            glGetGraphicsResetStatus = None
            GL_NO_ERROR = 0
    except Exception:
        return None

    class GpuBurnWidget(QOpenGLWidget):
        failed = pyqtSignal()
        lost = pyqtSignal()

        def __init__(self):
            super().__init__()
            self.setMinimumSize(300, 200)
            self.active = False
            self.dead = False
            self.linked = False
            self.frame = 0
            self.program = None
            self.vao = None
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.update)

        def initializeGL(self):
            try:
                ctx = self.context()
                if ctx is None or not ctx.isValid():
                    self._fail()
                    return
                major, minor = ctx.format().version()
                if (major, minor) < (3, 2):
                    self._fail()
                    return
                self.program = QOpenGLShaderProgram(self)
                self.program.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Vertex, VERTEX_SHADER)
                self.program.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Fragment, FRAGMENT_SHADER)
                self.linked = self.program.link()
                self.vao = QOpenGLVertexArrayObject(self)
                self.vao.create()
                if not self.linked or not self.vao.isCreated():
                    self._fail()
            except Exception:
                self._fail()

        def resizeGL(self, width, height):
            try:
                glViewport(0, 0, width, height)
            except Exception:
                pass

        def paintGL(self):
            if self.dead:
                return
            try:
                ctx = self.context()
                if ctx is None or not ctx.isValid():
                    self._lost()
                    return
                if glGetGraphicsResetStatus is not None:
                    try:
                        if glGetGraphicsResetStatus() != GL_NO_ERROR:
                            self._lost()
                            return
                    except Exception:
                        pass
                glClearColor(0.05, 0.06, 0.09, 1.0)
                glClear(GL_COLOR_BUFFER_BIT)
                if not (self.active and self.linked):
                    return
                self.program.bind()
                self.program.setUniformValue1f(self.program.uniformLocation("uTime"), self.frame * 0.05)
                self.program.setUniformValue(self.program.uniformLocation("uRes"),
                                             QVector2D(float(self.width()), float(self.height())))
                self.vao.bind()
                glDrawArrays(GL_TRIANGLES, 0, 3)
                self.vao.release()
                self.program.release()
                self.frame += 1
            except Exception:
                self._fail()

        def _fail(self):
            if self.dead:
                return
            self.dead = True
            self.active = False
            self.linked = False
            self.timer.stop()
            QTimer.singleShot(0, self.failed.emit)

        def _lost(self):
            if self.dead:
                return
            self.dead = True
            self.active = False
            self.linked = False
            self.timer.stop()
            QTimer.singleShot(0, self.lost.emit)

        def start(self):
            if self.dead:
                return
            self.active = True
            self.frame = 0
            self.timer.start(33)

        def stop(self):
            self.active = False
            self.timer.stop()
            if not self.dead:
                self.update()

    fmt = QSurfaceFormat()
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setVersion(3, 3)
    try:
        fmt.setOption(QSurfaceFormat.FormatOption.ResetNotification)
    except Exception:
        pass
    try:
        widget = GpuBurnWidget()
        widget.setFormat(fmt)
        return widget
    except Exception:
        return None


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
        c = theme.current()
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(c["canvas_bg"]))
        painter.setPen(QColor(c["canvas_border"]))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        if not self.active:
            painter.setPen(QColor(c["canvas_text"]))
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
    gpu = pyqtSignal(object)

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
            try:
                gpu = read_gpu()
            except Exception:
                gpu = None
            if self._active:
                self.sample.emit(float(load), temp)
                self.gpu.emit(gpu)

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
        c = theme.current()
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(c["canvas_bg"]))
        w, h = self.width(), self.height()
        painter.setPen(QColor(c["canvas_grid"]))
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
        painter.setPen(QColor(c["canvas_border"]))
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
        self.gpu_label = QLabel("GPU: —")
        self.gpu_label.setObjectName("specLabel")
        self.gpu_label.setWordWrap(True)
        self.vectors_label = QLabel("Векторы нагрузки: CPU-процессы + матрицы FP + пропускная способность ОЗУ + GPU-шейдер")
        self.vectors_label.setObjectName("specLabel")
        self.middle = QHBoxLayout()
        self.gpu = make_gpu_widget()
        self.gpu_shader = self.gpu is not None
        if self.gpu is not None:
            self.gpu.failed.connect(self._on_gpu_failed)
            self.gpu.lost.connect(self._on_gpu_lost)
        else:
            self.gpu = GpuFallbackWidget()
        self.graph = TempGraph()
        self.middle.addWidget(self.gpu, 1)
        self.middle.addWidget(self.graph, 1)
        self.body.addLayout(top)
        self.body.addWidget(self.gpu_label)
        self.body.addWidget(self.vectors_label)
        self.body.addLayout(self.middle, 1)
        self.engine = None
        self.seconds_left = 0
        self.max_temp = None
        self.max_load = 0.0
        self.temp_samples = []
        self.load_samples = []
        self.gpu_seen = False
        self.gpu_dropped = False
        self.gpu_name = ""
        self.max_gpu_temp = None
        self.monitor = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)

    def _swap_to_fallback(self):
        was_active = getattr(self.gpu, "active", False)
        old = self.gpu
        fallback = GpuFallbackWidget()
        self.middle.replaceWidget(old, fallback)
        old.setParent(None)
        old.deleteLater()
        self.gpu = fallback
        self.gpu_shader = False
        return was_active

    def _on_gpu_failed(self):
        if isinstance(self.gpu, GpuFallbackWidget):
            return
        was_active = self._swap_to_fallback()
        if was_active:
            self.gpu.start()

    def _on_gpu_lost(self):
        # Контекст OpenGL потерян под нагрузкой — GPU перестал отвечать (TDR).
        if isinstance(self.gpu, GpuFallbackWidget):
            return
        was_active = self._swap_to_fallback()
        if was_active:
            self.gpu.start()
        if not self.gpu_dropped:
            self.gpu_dropped = True
            self.gpu_label.setText("GPU: ⚠ потеря контекста под нагрузкой (видеоядро перестало отвечать)")
            self.set_status("GPU отвалился под нагрузкой (потеря контекста)", False)

    def reset_state(self):
        self.graph.clear()
        self.gpu.stop()
        self.max_temp = None
        self.max_load = 0.0
        self.temp_samples = []
        self.load_samples = []
        self.gpu_seen = False
        self.gpu_dropped = False
        self.gpu_name = ""
        self.max_gpu_temp = None
        self.time_label.setText("—")
        self.load_label.setText("Нагрузка CPU: —")
        self.temp_label.setText("Температура: —")
        self.gpu_label.setText("GPU: —")
        self.start_button.setText("Старт (2 минуты)")

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
        self.gpu_seen = False
        self.gpu_dropped = False
        self.gpu_name = ""
        self.max_gpu_temp = None
        self.engine = StressEngine()
        self.engine.start()
        if self.engine.vectors:
            self.vectors_label.setText("Векторы нагрузки: " + " + ".join(self.engine.vectors)
                                       + " + GPU (графика)")
        self.gpu.start()
        self.monitor = SensorWorker(self)
        self.monitor.sample.connect(self.on_sample)
        self.monitor.gpu.connect(self.on_gpu)
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

    def on_gpu(self, gpu):
        if gpu is None:
            return
        name = gpu.get("name")
        load = gpu.get("load")
        temp = gpu.get("temp")
        if name and (load is not None or temp is not None):
            self.gpu_seen = True
            self.gpu_name = name
            if temp is not None:
                self.max_gpu_temp = max(self.max_gpu_temp or 0.0, temp)
            parts = [name]
            if load is not None:
                parts.append(f"нагрузка {load:.0f}%")
            if temp is not None:
                parts.append(f"{temp:.0f} °C")
            self.gpu_label.setText("GPU: " + " · ".join(parts))
        elif self.gpu_seen and not self.gpu_dropped:
            self.gpu_dropped = True
            self.gpu_label.setText(f"GPU: ⚠ {self.gpu_name or 'видеоядро'} — ПЕРЕСТАЛ ОТВЕЧАТЬ ПОД НАГРУЗКОЙ")

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
        if self.gpu_dropped:
            gpu_note = f"GPU ({self.gpu_name or 'видеоядро'}) ОТКЛЮЧИЛСЯ под нагрузкой"
            summary_parts.append("⚠ GPU отвалился")
            self.grade = "bad"
        elif self.gpu_seen:
            gpu_note = f"GPU {self.gpu_name}: стабилен" + (
                f", макс. {self.max_gpu_temp:.0f} °C" if self.max_gpu_temp else "")
            if self.max_gpu_temp and temperature_grade(self.max_gpu_temp) == "bad" and self.grade != "bad":
                self.grade = "warn"
        else:
            gpu_note = "GPU: датчик недоступен"
        self.summary = " · ".join(summary_parts)
        parts = [f"{DURATION} с без сбоев", load_note, temp_note, gpu_note]
        details = ", ".join(part for part in parts if part)
        if self.gpu_dropped:
            self.details = details
            self.set_status("КРИТИЧНО: GPU отключился под нагрузкой", False)
            self.finish("Проблема: GPU отвалился", advance=False)
        else:
            self.auto_ok(details)

    def on_leave(self):
        if self.engine is not None:
            self.stop_test(aborted=True)
