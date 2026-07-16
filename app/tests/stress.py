import threading
import time
from collections import deque

import psutil
from PyQt6.QtCore import QPointF, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF
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


def _numpy_worker(stop_event, size=1100):
    # Крупные матрицы: счёт O(n^3), память O(n^2) → нагрузка счётно-ограниченная,
    # ядра грузятся сильнее (matmul в BLAS отпускает GIL → реальная параллельность).
    try:
        a = np.random.rand(size, size)
        b = np.random.rand(size, size)
        while not stop_event.is_set():
            c = a.dot(b)
            c = c.dot(b)
            a = c * (1.0 / (np.abs(c).max() + 1e-9))
    except Exception:
        pass


def _python_worker(stop_event):
    import math
    try:
        value = 0.0001
        while not stop_event.is_set():
            for _ in range(50000):
                value = math.sin(value) + math.sqrt(value * value + 1.0)
            value = 0.0001
    except Exception:
        pass


def _memory_worker(stop_event):
    try:
        block = 64 * 1024 * 1024
        source = bytes(block)
        target = bytearray(block)
        while not stop_event.is_set():
            target[:] = source
            _ = sum(target[::4194304])
    except Exception:
        pass


class StressEngine:
    def __init__(self):
        self.threads = []
        self.stop_thread = None
        self.vectors = []

    def start(self):
        cores = psutil.cpu_count() or 4
        self.stop_thread = threading.Event()
        use_numpy = np is not None
        # Размер матриц под систему: слабым (мало ОЗУ) — меньше (без свопа),
        # мощным — больше (сильнее счётная нагрузка). Потоки = числу ядер.
        size = 1100
        if use_numpy:
            try:
                total_gb = psutil.virtual_memory().total / 1024 ** 3
                per_thread_gb = total_gb / max(1, cores)
                if total_gb < 5 or per_thread_gb < 0.6:
                    size = 800
                elif total_gb >= 16 and per_thread_gb >= 1.2:
                    size = 1500
            except Exception:
                size = 1100
        label = (f"матричные вычисления FP {size}×{size} (numpy)" if use_numpy
                 else "вычислительные потоки CPU")
        for _ in range(cores):
            args = (self.stop_thread, size) if use_numpy else (self.stop_thread,)
            worker = _numpy_worker if use_numpy else _python_worker
            thread = threading.Thread(target=worker, args=args, daemon=True)
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

FRAGMENT_SHADER = """#version 330 core
uniform float uTime;
uniform vec2 uRes;
uniform int uIter;
out vec4 fragColor;

float hash13(vec3 p) {
    p = fract(p * 0.3183099 + 0.1);
    p *= 17.0;
    return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
}

float noise(vec3 x) {
    vec3 i = floor(x);
    vec3 f = fract(x);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(mix(hash13(i + vec3(0,0,0)), hash13(i + vec3(1,0,0)), f.x),
                   mix(hash13(i + vec3(0,1,0)), hash13(i + vec3(1,1,0)), f.x), f.y),
               mix(mix(hash13(i + vec3(0,0,1)), hash13(i + vec3(1,0,1)), f.x),
                   mix(hash13(i + vec3(0,1,1)), hash13(i + vec3(1,1,1)), f.x), f.y), f.z);
}

mat2 rot(float a) { float c = cos(a), s = sin(a); return mat2(c, -s, s, c); }

vec3 twist(vec3 p, float t) {
    p.xz = rot(t) * p.xz;
    p.xy = rot(t * 0.6) * p.xy;
    return p;
}

float sdTorus(vec3 p) {
    vec2 q = vec2(length(p.xz) - 1.0, p.y);
    return length(q) - 0.42;
}

void main() {
    vec2 uv = (gl_FragCoord.xy * 2.0 - uRes) / uRes.y;
    float t = uTime * 0.5;
    vec3 ro = vec3(0.0, 0.0, -3.2);
    vec3 rd = normalize(vec3(uv, 1.7));

    float d = 0.0;
    float hit = -1.0;
    vec3 pos = ro;
    for (int i = 0; i < 110; i++) {
        pos = ro + rd * d;
        float dist = sdTorus(twist(pos, t));
        if (dist < 0.004) { hit = d; break; }
        d += dist * 0.85;
        if (d > 9.0) break;
    }

    vec3 col = vec3(0.04, 0.045, 0.06) + 0.02 * uv.y;
    if (hit > 0.0) {
        vec3 q = twist(pos, t);
        vec2 e = vec2(0.001, 0.0);
        vec3 n = normalize(vec3(
            sdTorus(q + e.xyy) - sdTorus(q - e.xyy),
            sdTorus(q + e.yxy) - sdTorus(q - e.yxy),
            sdTorus(q + e.yyx) - sdTorus(q - e.yyx)));

        // Мех: множество прядей-сэмплов вдоль нормали (тяжёлая + «волосатая» часть)
        int steps = clamp(uIter, 24, 3000);
        float fur = 0.0;
        for (int i = 0; i < steps; i++) {
            float fi = float(i) / float(steps);
            vec3 sp = q + n * fi * 0.16;
            float strand = noise(sp * 46.0 + vec3(0.0, 0.0, t * 3.0));
            fur += smoothstep(0.62, 0.98, strand) * (1.0 - fi);
        }
        fur = fur / (float(steps) * 0.14);

        vec3 ld = normalize(vec3(0.7, 0.9, -0.6));
        float lig = max(dot(n, ld), 0.0);
        float rim = pow(1.0 - max(dot(n, -rd), 0.0), 2.5);
        vec3 base = 0.5 + 0.5 * cos(6.28318 * (vec3(0.0, 0.33, 0.62) + q.x * 0.35 + q.y * 0.2 + t * 0.15));
        col = base * (0.22 + lig) * (0.35 + fur) + rim * vec3(0.5, 0.7, 1.0) * 0.6;
    }
    col = pow(clamp(col, 0.0, 1.0), vec3(0.85));
    fragColor = vec4(col, 1.0);
}
"""


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
            self.iters = 800
            self._last_t = None
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
                # Адаптив (агрессивный): целимся в тяжёлый кадр ~35-70 мс — грузим GPU
                # по максимуму. Запас до порога TDR (~2 c) огромный. Слабая GPU сама
                # снизит итерации, мощная — раскочегарит до потолка.
                now = time.perf_counter()
                if self._last_t is not None:
                    dt_ms = (now - self._last_t) * 1000.0
                    if dt_ms > 70.0:
                        self.iters = max(200, int(self.iters * 0.9))
                    elif dt_ms < 35.0:
                        self.iters = min(60000, int(self.iters * 1.22) + 40)
                self._last_t = now
                self.program.bind()
                self.program.setUniformValue1f(self.program.uniformLocation("uTime"), self.frame * 0.05)
                self.program.setUniformValue1i(self.program.uniformLocation("uIter"), int(self.iters))
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
            self.iters = 800
            self._last_t = None
            self.timer.start(4)

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
        return self.wait(4000)


class TempGraph(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.samples = deque(maxlen=200)
        self.setMinimumSize(300, 200)

    CPU_LOAD = "#29b6d8"
    GPU_LOAD = "#a06cff"
    CPU_TEMP = "#ef5350"
    GPU_TEMP = "#ffa726"
    LEGEND = [(CPU_LOAD, "CPU %"), (GPU_LOAD, "GPU %"), (CPU_TEMP, "CPU °C"), (GPU_TEMP, "GPU °C")]

    def add(self, load, temp, gpu_load=None, gpu_temp=None):
        self.samples.append((load, temp, gpu_load, gpu_temp))
        self.update()

    def clear(self):
        self.samples.clear()
        self.update()

    def _series(self, idx, scale, w, h, step):
        return [QPointF(i * step, h - s[idx] / scale * (h - 34) - 6)
                for i, s in enumerate(self.samples) if s[idx] is not None]

    def paintEvent(self, event):
        c = theme.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        radius = 12
        clip = QPainterPath()
        clip.addRoundedRect(0.0, 0.0, float(w), float(h), radius, radius)
        painter.setClipPath(clip)
        painter.fillRect(self.rect(), QColor(c["canvas_bg"]))
        painter.setPen(QPen(QColor(c["canvas_grid"]), 1))
        for frac in (0.25, 0.5, 0.75):
            y = int(h * frac)
            painter.drawLine(0, y, w, y)
        if len(self.samples) >= 2:
            step = w / (self.samples.maxlen - 1)
            load_points = self._series(0, 100.0, w, h, step)
            if len(load_points) >= 2:
                area = QPolygonF(load_points + [QPointF(load_points[-1].x(), h),
                                                QPointF(load_points[0].x(), h)])
                gradient = QLinearGradient(0, 0, 0, h)
                top = QColor(self.CPU_LOAD)
                top.setAlpha(90)
                bottom = QColor(self.CPU_LOAD)
                bottom.setAlpha(0)
                gradient.setColorAt(0.0, top)
                gradient.setColorAt(1.0, bottom)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(gradient))
                painter.drawPolygon(area)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor(self.CPU_LOAD), 2))
                painter.drawPolyline(QPolygonF(load_points))
            for idx, color, scale in ((2, self.GPU_LOAD, 100.0),
                                      (1, self.CPU_TEMP, 105.0),
                                      (3, self.GPU_TEMP, 105.0)):
                points = self._series(idx, scale, w, h, step)
                if len(points) >= 2:
                    painter.setPen(QPen(QColor(color), 2))
                    painter.drawPolyline(QPolygonF(points))
        # легенда-чипы
        x = 12
        for color, label in self.LEGEND:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(color))
            painter.drawRoundedRect(x, 9, 11, 11, 3, 3)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QColor(c["canvas_text"]))
            painter.drawText(x + 16, 19, label)
            x += 16 + painter.fontMetrics().horizontalAdvance(label) + 14
        painter.setClipping(False)
        painter.setPen(QColor(c["canvas_border"]))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(0, 0, w - 1, h - 1, radius, radius)


class StressPage(BaseTestPage):
    title = "Стресс-тест (нагрузка)"
    auto = True
    hint = "Нажмите «Старт» для запуска 2-минутного теста стабильности CPU/GPU и следите за температурой."

    def build_body(self):
        top = QHBoxLayout()
        self.start_button = QPushButton("Старт (2 минуты)")
        self.start_button.clicked.connect(self.toggle)
        self.infinite_button = QPushButton("∞ Бесконечно")
        self.infinite_button.setToolTip("Гонять стресс без ограничения по времени — до ручной остановки")
        self.infinite_button.clicked.connect(self.toggle_infinite)
        self.time_label = QLabel("—")
        self.load_label = QLabel("Нагрузка CPU: —")
        self.temp_label = QLabel("Температура: —")
        top.addWidget(self.start_button)
        top.addWidget(self.infinite_button)
        top.addWidget(self.time_label)
        top.addStretch(1)
        top.addWidget(self.load_label)
        top.addWidget(self.temp_label)
        self.gpu_label = QLabel("GPU: —")
        self.gpu_label.setObjectName("specLabel")
        self.gpu_label.setWordWrap(True)
        self.vectors_label = QLabel("Векторы нагрузки: CPU-процессы + матрицы FP + пропускная способность ОЗУ + GPU-шейдер")
        self.vectors_label.setObjectName("specLabel")
        self.vectors_label.setWordWrap(True)
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
        self.infinite = False
        self.elapsed = 0
        self.max_temp = None
        self.max_load = 0.0
        self.temp_samples = []
        self.load_samples = []
        self.gpu_seen = False
        self.gpu_dropped = False
        self.gpu_name = ""
        self.max_gpu_temp = None
        self._last_gpu_temp = None
        self._last_gpu_load = None
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
        self.infinite = False
        self.elapsed = 0
        self.max_temp = None
        self.max_load = 0.0
        self.temp_samples = []
        self.load_samples = []
        self.gpu_seen = False
        self.gpu_dropped = False
        self.gpu_name = ""
        self.max_gpu_temp = None
        self._last_gpu_temp = None
        self._last_gpu_load = None
        self.time_label.setText("—")
        self.load_label.setText("Нагрузка CPU: —")
        self.temp_label.setText("Температура: —")
        self.gpu_label.setText("GPU: —")
        self.start_button.setText("Старт (2 минуты)")
        self.infinite_button.setEnabled(True)

    def auto_start(self):
        if self.engine is None:
            self.start_test(infinite=False)

    def toggle(self):
        if self.engine is not None:
            # ручная остановка: для бесконечного режима — с вердиктом, для 2-мин — как прерывание
            self.stop_test(aborted=not self.infinite)
        else:
            self.start_test(infinite=False)

    def toggle_infinite(self):
        if self.engine is None:
            self.start_test(infinite=True)

    def start_test(self, infinite=False):
        self.infinite = infinite
        self.elapsed = 0
        self.graph.clear()
        self.max_temp = None
        self.max_load = 0.0
        self.temp_samples = []
        self.load_samples = []
        self.gpu_seen = False
        self.gpu_dropped = False
        self.gpu_name = ""
        self.max_gpu_temp = None
        self._last_gpu_temp = None
        self._last_gpu_load = None
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
        self.infinite_button.setEnabled(False)
        self.start_button.setText("■ Стоп")
        if infinite:
            self.time_label.setText("Идёт: 0:00 (∞ — стоп вручную)")
            self.set_status("идет бесконечный стресс-тест — остановите вручную...")
        else:
            self.seconds_left = DURATION
            self.time_label.setText(f"Осталось: {self.seconds_left} с")
            self.set_status("идет стресс-тест (комплекс нагрузок)...")
        self.timer.start(1000)

    def tick(self):
        if self.infinite:
            self.elapsed += 1
            minutes, seconds = divmod(self.elapsed, 60)
            self.time_label.setText(f"Идёт: {minutes}:{seconds:02d} (∞ — стоп вручную)")
            return
        self.seconds_left -= 1
        self.time_label.setText(f"Осталось: {self.seconds_left} с")
        if self.seconds_left <= 0:
            self.stop_test(aborted=False)

    def on_sample(self, load, temp):
        if self.monitor is None:
            return
        self.max_load = max(self.max_load, load)
        self.load_samples.append(load)
        self.load_label.setText(f"Нагрузка CPU: {load:.0f}%")
        if temp is not None and temp > 0:
            self.max_temp = max(self.max_temp or 0.0, temp)
            self.temp_samples.append(temp)
            self.temp_label.setText(f"Температура: {temp:.0f} °C")
        else:
            self.temp_label.setText("Температура: датчик недоступен")
        self.graph.add(load, temp, self._last_gpu_load, self._last_gpu_temp)

    def on_gpu(self, gpu):
        if self.monitor is None or gpu is None:
            return
        name = gpu.get("name")
        load = gpu.get("load")
        temp = gpu.get("temp")
        if name and (load is not None or temp is not None):
            self.gpu_seen = True
            self.gpu_name = name
            if temp is not None:
                self.max_gpu_temp = max(self.max_gpu_temp or 0.0, temp)
                self._last_gpu_temp = temp
            if load is not None:
                self._last_gpu_load = load
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
            finished = self.monitor.stop()
            if finished:
                self.monitor.deleteLater()
            self.monitor = None
        if self.engine is not None:
            self.engine.stop()
            self.engine = None
        self.start_button.setText("Старт (2 минуты)")
        self.infinite_button.setEnabled(True)
        was_infinite = self.infinite
        self.infinite = False
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
        ran = f"{self.elapsed} с (бесконечный режим)" if was_infinite else f"{DURATION} с без сбоев"
        parts = [ran, load_note, temp_note, gpu_note]
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
