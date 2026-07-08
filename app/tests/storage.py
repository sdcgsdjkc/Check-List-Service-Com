import ctypes
import json
import os
import shutil
import sys
import tempfile
import time
from ctypes import wintypes

import psutil
from PyQt6.QtCore import QPointF, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QListWidget, QProgressBar, QPushButton, QWidget

from app import theme
from app.norms import power_on_hours_grade, read_speed_grade, smart_grade
from app.sysinfo import _powershell, list_physical_disks
from app.tests.base import BaseTestPage

SURFACE_BLOCK = 1024 * 1024
SURFACE_LEVELS = [
    ("excellent", 8, "#7f8c99", "< 8 мс"),
    ("good", 20, "#57c06a", "< 20 мс"),
    ("slow", 50, "#e0a33a", "< 50 мс"),
    ("bad", 150, "#e0554f", "< 150 мс"),
    ("verybad", float("inf"), "#4a6cf0", "≥ 150 мс"),
]
SURFACE_COLOR = {name: color for name, _, color, _ in SURFACE_LEVELS}
SURFACE_COLOR["err"] = "#b01515"
SURFACE_RANK = {"excellent": 0, "good": 1, "slow": 2, "bad": 3, "verybad": 4, "err": 5}
SURFACE_RANK_COLOR = [SURFACE_COLOR[name] for name in
                      ("excellent", "good", "slow", "bad", "verybad", "err")]


def surface_grade(ms, error):
    if error:
        return "err"
    for name, limit, _, _ in SURFACE_LEVELS:
        if ms < limit:
            return name
    return "verybad"


class BlockMap(QWidget):
    CELL = 13
    MAXCELLS = 8000

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cells = []      # ранги (худший в объединённой ячейке), ограничены MAXCELLS
        self.merge = 1       # сколько сырых блоков на ячейку (растёт по мере скана)
        self._acc = -1
        self._acc_n = 0
        self._dirty = False
        self.setMinimumHeight(230)
        self._timer = QTimer(self)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self._flush_paint)
        self._timer.start()

    def reset(self):
        self.cells = []
        self.merge = 1
        self._acc = -1
        self._acc_n = 0
        self._dirty = True

    def add_batch(self, grades):
        for grade in grades:
            rank = SURFACE_RANK[grade]
            if rank > self._acc:
                self._acc = rank
            self._acc_n += 1
            if self._acc_n >= self.merge:
                self.cells.append(self._acc)
                self._acc = -1
                self._acc_n = 0
        if len(self.cells) > self.MAXCELLS:
            self.cells = [max(self.cells[i], self.cells[i + 1]) if i + 1 < len(self.cells)
                          else self.cells[i] for i in range(0, len(self.cells), 2)]
            self.merge *= 2
        self._dirty = True

    def _flush_paint(self):
        if self._dirty:
            self._dirty = False
            self.update()

    def paintEvent(self, event):
        c = theme.current()
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(c["canvas_bg"]))
        cell = self.CELL
        cols = max(1, (self.width() - 4) // cell)
        rows = max(1, (self.height() - 4) // cell)
        capacity = cols * rows
        cells = self.cells
        if cells and len(cells) > capacity:
            bucket = len(cells) / capacity
            cells = [max(cells[int(i * bucket):int((i + 1) * bucket)] or [cells[-1]])
                     for i in range(capacity)]
        painter.setPen(Qt.PenStyle.NoPen)
        for i, rank in enumerate(cells):
            col = i % cols
            row = i // cols
            painter.setBrush(QColor(SURFACE_RANK_COLOR[rank]))
            painter.drawRect(2 + col * cell, 2 + row * cell, cell - 2, cell - 2)
        painter.setPen(QColor(c["canvas_border"]))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))


class SurfaceWorker(QThread):
    batch = pyqtSignal(list)
    progress = pyqtSignal(int)
    speed = pyqtSignal(float)
    done = pyqtSignal(object)

    def __init__(self, path, size, time_limit, parent=None):
        super().__init__(parent)
        self.path = path
        self.size = size
        self.time_limit = time_limit
        self._abort = False

    def stop(self):
        self._abort = True
        self.wait(3000)

    def run(self):
        if sys.platform != "win32":
            self.done.emit({"error": "посекторное чтение доступно только на Windows"})
            return
        kernel = ctypes.windll.kernel32
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                       wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.ReadFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                                    ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
        kernel.ReadFile.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        kernel.SetFilePointerEx.argtypes = [wintypes.HANDLE, ctypes.c_longlong,
                                            ctypes.POINTER(ctypes.c_longlong), wintypes.DWORD]
        kernel.SetFilePointerEx.restype = wintypes.BOOL
        handle = kernel.CreateFileW(self.path, 0x80000000, 0x1 | 0x2, None, 3, 0, None)
        if handle == wintypes.HANDLE(-1).value or not handle:
            self.done.emit({"error": "не удалось открыть диск (нужны права администратора)"})
            return
        try:
            buffer = ctypes.create_string_buffer(SURFACE_BLOCK)
            read_bytes = wintypes.DWORD(0)
            counts = {name: 0 for name in SURFACE_RANK}
            total = self.size if self.size and self.size > 0 else 0
            worst = 0.0
            done_blocks = 0
            pos = 0
            start = time.perf_counter()
            win_bytes = 0
            win_start = start
            batch = []
            while not self._abort:
                # у конца диска остаток < 1 МБ не читаем (не выровнен по сектору → ложный бэд)
                if total and pos + SURFACE_BLOCK > total:
                    break
                elapsed = time.perf_counter() - start
                if self.time_limit and elapsed >= self.time_limit:
                    break
                t0 = time.perf_counter()
                ok = kernel.ReadFile(handle, buffer, SURFACE_BLOCK, ctypes.byref(read_bytes), None)
                dt_ms = (time.perf_counter() - t0) * 1000.0
                error = (not ok) or read_bytes.value == 0
                grade = surface_grade(dt_ms, error)
                counts[grade] += 1
                batch.append(grade)
                pos += SURFACE_BLOCK
                done_blocks += 1
                if error:
                    new_pos = ctypes.c_longlong(0)
                    kernel.SetFilePointerEx(handle, ctypes.c_longlong(pos), ctypes.byref(new_pos), 0)
                else:
                    worst = max(worst, dt_ms)
                    win_bytes += read_bytes.value
                now = time.perf_counter()
                if now - win_start >= 0.25 or len(batch) >= 512:
                    self.batch.emit(batch)
                    batch = []
                    if win_bytes:
                        self.speed.emit(win_bytes / (1024 * 1024) / (now - win_start))
                    win_bytes = 0
                    win_start = now
                    if self.time_limit:
                        self.progress.emit(min(100, int((now - start) * 100 / self.time_limit)))
                    elif total:
                        self.progress.emit(min(100, int(pos * 100 / total)))
                if not error and 0 < read_bytes.value < SURFACE_BLOCK:
                    break
            if batch:
                self.batch.emit(batch)
            self.done.emit({"counts": counts, "worst_ms": round(worst),
                            "elapsed": round(time.perf_counter() - start), "blocks": done_blocks,
                            "scanned_gb": done_blocks * SURFACE_BLOCK / 1024 ** 3})
        except Exception as exc:
            self.done.emit({"error": str(exc)})
        finally:
            kernel.CloseHandle(handle)


class SpeedGraph(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.samples = []
        self.slow_threshold = 0.0
        self.setMinimumHeight(180)

    def reset(self):
        self.samples = []
        self.slow_threshold = 0.0
        self.update()

    def add(self, speed):
        self.samples.append(speed)
        if len(self.samples) > 4000:
            self.samples = self.samples[-4000:]
        self.update()

    def set_threshold(self, value):
        self.slow_threshold = value
        self.update()

    def paintEvent(self, event):
        c = theme.current()
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(c["canvas_bg"]))
        w, h = self.width(), self.height()
        peak = max(self.samples) if self.samples else 1.0
        peak = max(peak, 1.0)
        painter.setPen(QColor(c["canvas_grid"]))
        for frac in (0.25, 0.5, 0.75):
            y = int(h * frac)
            painter.drawLine(0, y, w, y)
        if self.slow_threshold > 0:
            y = int(h - self.slow_threshold / peak * (h - 8) - 4)
            painter.setPen(QPen(QColor("#e0b13a"), 1, Qt.PenStyle.DashLine))
            painter.drawLine(0, y, w, y)
        if len(self.samples) >= 2:
            step = w / max(1, len(self.samples) - 1)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            points = [QPointF(i * step, h - s / peak * (h - 8) - 4)
                      for i, s in enumerate(self.samples)]
            painter.setPen(QPen(QColor("#1e88e5"), 2))
            painter.drawPolyline(QPolygonF(points))
            if self.slow_threshold > 0:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(224, 79, 79, 200))
                for i, s in enumerate(self.samples):
                    if s < self.slow_threshold:
                        painter.drawEllipse(QPointF(i * step, h - s / peak * (h - 8) - 4), 3, 3)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QColor(c["canvas_text"]))
        painter.drawText(8, 16, f"пик {peak:.0f} МБ/с")
        painter.setPen(QColor(c["canvas_border"]))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))


BLOCK = 8 * 1024 * 1024
WINDOW = 64 * 1024 * 1024
TARGET = 2 * 1024 * 1024 * 1024


def _stats(samples, size_mb, total_time):
    avg = size_mb / max(1e-6, total_time)
    if samples:
        return {"min": round(min(samples)), "avg": round(avg), "max": round(max(samples))}
    return {"min": round(avg), "avg": round(avg), "max": round(avg)}


class SpeedWorker(QThread):
    done = pyqtSignal(object)
    progress = pyqtSignal(int)
    sample = pyqtSignal(str, float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._abort = False

    def stop(self):
        self._abort = True
        self.wait(6000)

    def run(self):
        tempdir = tempfile.gettempdir()
        try:
            free = shutil.disk_usage(tempdir).free
        except Exception:
            free = 0
        total = TARGET
        if free and free < TARGET + 2 * 1024 * 1024 * 1024:
            total = free - 2 * 1024 * 1024 * 1024
        total = (total // BLOCK) * BLOCK
        if total < 64 * 1024 * 1024:
            self.done.emit({"error": "мало свободного места на диске для безопасного замера"})
            return
        size_mb = total // (1024 * 1024)
        block = os.urandom(BLOCK)
        path = os.path.join(tempdir, "servicecom_disktest.tmp")
        write_stats = None
        read_stats = None
        try:
            samples = []
            start = time.perf_counter()
            win_start = start
            win_bytes = 0
            written = 0
            with open(path, "wb") as handle:
                while written < total:
                    if self._abort:
                        return
                    handle.write(block)
                    written += BLOCK
                    win_bytes += BLOCK
                    if win_bytes >= WINDOW:
                        now = time.perf_counter()
                        samples.append(win_bytes / (1024 * 1024) / max(1e-6, now - win_start))
                        win_start = now
                        win_bytes = 0
                    self.progress.emit(int(written / total * 50))
                handle.flush()
                try:
                    os.fsync(handle.fileno())
                except OSError:
                    pass
            for sp in samples:
                self.sample.emit("write", 0.0, sp)
            write_stats = _stats(samples, size_mb, time.perf_counter() - start)
            samples = []
            start = time.perf_counter()
            win_start = start
            win_bytes = 0
            read = 0
            with open(path, "rb") as handle:
                while True:
                    if self._abort:
                        return
                    chunk = handle.read(BLOCK)
                    if not chunk:
                        break
                    read += len(chunk)
                    win_bytes += len(chunk)
                    if win_bytes >= WINDOW:
                        now = time.perf_counter()
                        speed = win_bytes / (1024 * 1024) / max(1e-6, now - win_start)
                        samples.append(speed)
                        self.sample.emit("read", read / total * 100.0, speed)
                        win_start = now
                        win_bytes = 0
                    self.progress.emit(50 + int(read / total * 50))
            read_stats = _stats(samples, size_mb, time.perf_counter() - start)
            self.done.emit({"write": write_stats, "read": read_stats,
                            "size_mb": size_mb, "read_samples": samples})
        except Exception as exc:
            self.done.emit({"write": write_stats, "read": read_stats,
                            "size_mb": size_mb, "error": str(exc)})
        finally:
            try:
                os.remove(path)
            except OSError:
                pass


class StorageWorker(QThread):
    done = pyqtSignal(object)
    disks = pyqtSignal(list)

    def run(self):
        try:
            self.disks.emit(list_physical_disks())
        except Exception:
            self.disks.emit([])
        if sys.platform == "win32":
            try:
                raw = _powershell(
                    "Get-PhysicalDisk | ForEach-Object { $r=$_ | Get-StorageReliabilityCounter "
                    "-ErrorAction SilentlyContinue; [PSCustomObject]@{ FriendlyName=$_.FriendlyName; "
                    "MediaType=$_.MediaType; HealthStatus=$_.HealthStatus; Size=$_.Size; "
                    "Temperature=$r.Temperature; PowerOnHours=$r.PowerOnHours; Wear=$r.Wear; "
                    "ReadErrors=$r.ReadErrorsTotal } } | ConvertTo-Json",
                    timeout=45)
                data = json.loads(raw) if raw else []
                if isinstance(data, dict):
                    data = [data]
                self.done.emit(data)
                return
            except Exception:
                pass
        try:
            fallback = []
            for part in psutil.disk_partitions(all=False):
                if not part.fstype:
                    continue
                total = psutil.disk_usage(part.mountpoint).total
                fallback.append({"FriendlyName": part.device, "Size": total})
            self.done.emit({"fallback": fallback})
        except Exception:
            self.done.emit(None)


class StoragePage(BaseTestPage):
    title = "HDD / SSD"
    hint = "Ожидайте автоматического считывания S.M.A.R.T.-статуса накопителей..."
    auto = True
    MEDIA = {0: "Накопитель", 3: "HDD", 4: "SSD", 5: "SCM"}
    HEALTH = {0: "Good", 1: "Warning", 2: "Unhealthy"}

    def build_body(self):
        self.busy = QProgressBar()
        self.busy.setRange(0, 0)
        self.busy.hide()
        self.info = QLabel("Проверка не запускалась")
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Диск:"))
        self.disk_combo = QComboBox()
        controls.addWidget(self.disk_combo, 1)
        self.quick_button = QPushButton("Быстрый скан (3 мин)")
        self.quick_button.clicked.connect(lambda: self.start_surface(180))
        self.full_button = QPushButton("Полный проход")
        self.full_button.clicked.connect(lambda: self.start_surface(None))
        self.stop_button = QPushButton("Стоп")
        self.stop_button.setObjectName("failButton")
        self.stop_button.clicked.connect(self.stop_surface)
        self.stop_button.hide()
        controls.addWidget(self.quick_button)
        controls.addWidget(self.full_button)
        controls.addWidget(self.stop_button)
        self.speed_label = QLabel("Скорость: —")
        self.speed_label.setObjectName("bigValue")
        self.blockmap = BlockMap()
        self.graph = SpeedGraph()
        self.graph.hide()
        self.legend = QLabel(self._legend_html())
        self.legend.setObjectName("specLabel")
        self.disk_list = QListWidget()
        self.disk_list.setMaximumHeight(120)
        self.body.addWidget(self.busy)
        self.body.addWidget(self.info)
        self.body.addLayout(controls)
        self.body.addWidget(self.speed_label)
        self.body.addWidget(self.blockmap, 1)
        self.body.addWidget(self.graph, 1)
        self.body.addWidget(self.legend)
        self.body.addWidget(self.disk_list)
        self.worker = None
        self.speed_worker = None
        self.surface_worker = None
        self.disks = []
        self._auto_quick = False
        self._smart_done = False
        self.health_summary = ""
        self.healthy = True
        self.auto_pass = True
        self.smart_grade = "ok"
        self.countdown = 0
        self.advance_timer = QTimer(self)
        self.advance_timer.timeout.connect(self._countdown_tick)

    @staticmethod
    def _legend_html():
        parts = [(SURFACE_COLOR["excellent"], "отлично"), (SURFACE_COLOR["good"], "норма"),
                 (SURFACE_COLOR["slow"], "медленно"), (SURFACE_COLOR["bad"], "проблема"),
                 (SURFACE_COLOR["verybad"], "оч. медленно"), (SURFACE_COLOR["err"], "бэд-блок")]
        return "&nbsp;&nbsp;".join(f"<span style='color:{c}'>■</span> {t}" for c, t in parts)

    def reset_state(self):
        self.advance_timer.stop()
        self.countdown = 0
        self.disk_list.clear()
        self.blockmap.reset()
        self.graph.reset()
        self.graph.hide()
        self.blockmap.show()
        self.busy.hide()
        self.stop_button.hide()
        self.quick_button.setEnabled(True)
        self.full_button.setEnabled(True)
        self.info.setText("Проверка не запускалась")
        self.speed_label.setText("Скорость: —")
        self.health_summary = ""
        self.healthy = True
        self.auto_pass = True
        self.smart_grade = "ok"
        self._auto_quick = False
        self._smart_done = False

    def on_enter(self):
        if self.worker is not None or self.surface_worker is not None:
            return
        self.busy.show()
        self.info.setText("Чтение состояния накопителей (S.M.A.R.T.)...")
        self.set_status("идет проверка S.M.A.R.T. ...")
        self.worker = StorageWorker(self)
        self.worker.disks.connect(self._on_disks)
        self.worker.done.connect(self.on_done)
        self.worker.start()

    def auto_start(self):
        self._auto_quick = True
        if self._smart_done:
            self.start_surface(180)

    def _on_disks(self, disks):
        self.disks = disks
        self.disk_combo.clear()
        for disk in disks:
            label = f"{disk['model']} — {disk['size'] / 1024 ** 3:.0f} ГБ"
            if disk["is_system"]:
                label += " (системный)"
            self.disk_combo.addItem(label)

    def _populate_disks(self):
        # список дисков уже получен в фоне через сигнал disks; ничего не блокируем
        if not self.disk_combo.count():
            self._on_disks(self.disks or [])

    def _smart_ready(self):
        self._smart_done = True
        self.busy.hide()
        self._populate_disks()
        if self._auto_quick:
            self.start_surface(180)
        elif self.disks:
            self.set_status("выберите режим скана поверхности или отметьте тест вручную")
        else:
            self.set_status("физические диски не найдены (нужны права администратора)", "warn")

    def start_surface(self, time_limit):
        if not self.disks:
            self.set_status("физические диски не найдены (нужны права администратора)", "warn")
            return
        index = max(0, self.disk_combo.currentIndex())
        disk = self.disks[index]
        self.blockmap.reset()
        self.blockmap.show()
        self.graph.hide()
        self.busy.setRange(0, 100)
        self.busy.setValue(0)
        self.busy.show()
        self.quick_button.setEnabled(False)
        self.full_button.setEnabled(False)
        self.stop_button.show()
        mode = "быстрый, 3 мин" if time_limit else "полный проход"
        self.info.setText(f"Скан поверхности [{mode}]: {disk['model']}")
        self.set_status("идет посекторное чтение поверхности...")
        self.surface_worker = SurfaceWorker(disk["path"], disk["size"], time_limit, self)
        self.surface_worker.batch.connect(self.blockmap.add_batch)
        self.surface_worker.speed.connect(self.on_surface_speed)
        self.surface_worker.progress.connect(self.busy.setValue)
        self.surface_worker.done.connect(self.on_surface_done)
        self.surface_worker.start()

    def stop_surface(self):
        if self.surface_worker is not None and self.surface_worker.isRunning():
            self.surface_worker.stop()

    def on_surface_speed(self, mbps):
        self.speed_label.setText(f"Текущая скорость: {mbps:.0f} МБ/с")

    def on_surface_done(self, result):
        self.busy.hide()
        self.stop_button.hide()
        self.quick_button.setEnabled(True)
        self.full_button.setEnabled(True)
        self.surface_worker = None
        if "error" in result:
            self.disk_list.addItem(f"Скан поверхности недоступен: {result['error']}")
            self.disk_list.addItem("    ⚠ замер скорости идёт по системному диску (не по выбранному)")
            self.speed_label.setText("Посекторный скан недоступен — обычный замер скорости системного диска")
            self.blockmap.hide()
            self.graph.show()
            self.start_speed_test()
            return
        counts = result["counts"]
        good = counts["excellent"] + counts["good"]
        problem = counts["bad"] + counts["verybad"] + counts["err"]
        total_blocks = max(1, result["blocks"])
        slow_ratio = counts["slow"] / total_blocks
        bad_ratio = (counts["bad"] + counts["verybad"]) / total_blocks
        stats = (f"проверено {result['scanned_gb']:.1f} ГБ за {result['elapsed']} с · "
                 f"норма {good} · медленно {counts['slow']} · "
                 f"проблемных {problem} · бэдов {counts['err']} · макс. {result['worst_ms']} мс")
        self.disk_list.addItem(f"Скан поверхности: {stats}")
        if counts["err"] > 0 or counts["verybad"] > 0 or bad_ratio > 0.01:
            surface_grade_name = "bad"
            zone = "бэд-блоки / провалы — диск деградирует"
        elif slow_ratio > 0.05 or counts["bad"] > 0:
            surface_grade_name = "warn"
            zone = "есть медленные зоны"
        else:
            surface_grade_name = "ok"
            zone = "поверхность в норме"
        rank = {"ok": 0, "warn": 1, "bad": 2}
        self.grade = max([self.smart_grade, surface_grade_name], key=lambda g: rank.get(g, 1))
        self.summary = " · ".join(part for part in [
            (self.health_summary.split(";")[0] if self.health_summary else ""), zone] if part)
        combined = "; ".join(part for part in [self.health_summary, stats] if part)
        if self.grade == "bad":
            self.details = combined
            self.set_status(f"КРИТИЧНО: {zone}", False)
            self.finish("Не пройден", advance=False)
        elif self.healthy:
            self.auto_ok(combined, advance=False)
            self.countdown = 10
            self.advance_timer.start(1000)
            self._countdown_tick(initial=True)
        else:
            self.details = combined
            self.set_status("проверьте состояние S.M.A.R.T. вручную", "warn")

    def start_speed_test(self):
        self.busy.setRange(0, 100)
        self.busy.setValue(0)
        self.busy.show()
        self.graph.reset()
        self.speed_label.setText("Скорость: идет замер записи/чтения (2 ГБ)...")
        self.set_status("замер скорости накопителя...")
        self.speed_worker = SpeedWorker(self)
        self.speed_worker.progress.connect(self.busy.setValue)
        self.speed_worker.sample.connect(self.on_speed_sample)
        self.speed_worker.done.connect(self.on_speed_done)
        self.speed_worker.start()

    def on_speed_sample(self, phase, position, speed):
        if phase == "read":
            self.graph.add(speed)
            self.speed_label.setText(f"Чтение: {speed:.0f} МБ/с  (позиция {position:.0f}%)")

    @staticmethod
    def _fmt(stats):
        if not stats:
            return "н/д"
        return f"{stats['avg']} МБ/с (мин {stats['min']} · макс {stats['max']})"

    def on_speed_done(self, result):
        self.busy.hide()
        write = result.get("write")
        read = result.get("read")
        size_mb = result.get("size_mb")
        write_text = self._fmt(write)
        read_text = self._fmt(read)
        gb = (size_mb or 0) / 1024
        self.speed_label.setText(f"Запись: {write_text}      Чтение: {read_text}"
                                 + (f"      (объем {gb:.1f} ГБ)" if size_mb else ""))
        self.disk_list.addItem(f"Тест скорости накопителя ({gb:.1f} ГБ):")
        self.disk_list.addItem(f"    запись — {write_text}")
        self.disk_list.addItem(f"    чтение — {read_text}")
        grades = [self.smart_grade]
        zone_note = ""
        if write or read:
            speed_text = f"запись {write_text}, чтение {read_text}"
            w = f"{write['avg']}" if write else "н/д"
            r = f"{read['avg']}" if read else "н/д"
            state = self.health_summary.split(";")[0] if self.health_summary else ""
            if read:
                grades.append(read_speed_grade(read["avg"]))
                samples = result.get("read_samples") or []
                if samples and len(samples) >= 4:
                    threshold = read["max"] * 0.5
                    self.graph.set_threshold(threshold)
                    slow = sum(1 for s in samples if s < threshold)
                    ratio = slow / len(samples)
                    if read["min"] < read["max"] * 0.35 and ratio > 0.15:
                        grades.append("bad")
                        zone_note = f"провалы скорости: {slow} из {len(samples)} зон (деградация)"
                        self.disk_list.addItem(f"    ⚠ {zone_note}")
                    elif read["min"] < read["max"] * 0.5:
                        grades.append("warn")
                        zone_note = f"неравномерная скорость (мин {read['min']} / макс {read['max']})"
                        self.disk_list.addItem(f"    {zone_note}")
            self.summary = " · ".join(part for part in [
                state, f"чтение {r} / запись {w} МБ/с", zone_note] if part)
        else:
            speed_text = f"замер скорости не выполнен ({result.get('error', 'ошибка')})"
            self.summary = self.health_summary
        self.grade = "bad" if "bad" in grades else "warn" if "warn" in grades else "ok"
        combined = "; ".join(part for part in [self.health_summary, speed_text] if part)
        if self.auto_pass and self.healthy:
            self.auto_ok(combined, advance=False)
            self.countdown = 10
            self.advance_timer.start(1000)
            self._countdown_tick(initial=True)
        elif not self.healthy:
            self.details = combined
            self.set_status("есть накопители с проблемами S.M.A.R.T.", False)
        else:
            self.details = combined
            self.set_status("оцените состояние дисков вручную (S.M.A.R.T. недоступен)", "warn")

    def _countdown_tick(self, initial=False):
        if not initial:
            self.countdown -= 1
        if self.countdown <= 0:
            self.advance_timer.stop()
            self.finish(self.result or "Пройден (авто)", advance=True)
            return
        self.set_status(f"авто-ОК — переход к следующему тесту через {self.countdown} с "
                        f"(Пробел — сразу)", True)

    def on_leave(self):
        self.advance_timer.stop()
        if self.surface_worker is not None and self.surface_worker.isRunning():
            self.surface_worker.stop()
        if self.speed_worker is not None and self.speed_worker.isRunning():
            self.speed_worker.stop()
        if self.worker is not None and self.worker.isRunning():
            self.worker.wait(3000)

    def _health_text(self, value):
        if isinstance(value, str):
            return "Good" if value.lower() == "healthy" else value
        return self.HEALTH.get(value, str(value))

    def _media_text(self, value):
        if isinstance(value, str):
            return value or "Накопитель"
        return self.MEDIA.get(value, "Накопитель")

    def on_done(self, data):
        self.worker = None
        if data is None:
            self.info.setText("S.M.A.R.T. недоступен")
            self.health_summary = "S.M.A.R.T. недоступен"
            self.auto_pass = False
            self._smart_ready()
            return
        if isinstance(data, dict) and "fallback" in data:
            for disk in data["fallback"]:
                self.disk_list.addItem(f"{disk['FriendlyName']} — {disk['Size'] / 1024 ** 3:.0f} ГБ")
            self.info.setText("S.M.A.R.T. недоступен, показаны только разделы")
            self.health_summary = "S.M.A.R.T. недоступен"
            self.auto_pass = False
            self._smart_ready()
            return
        if not data:
            self.info.setText("S.M.A.R.T. недоступен")
            self.health_summary = "S.M.A.R.T. недоступен"
            self.auto_pass = False
            self._smart_ready()
            return
        healthy = True
        summary = []
        worst_grade = "ok"
        for disk in data:
            health = self._health_text(disk.get("HealthStatus"))
            media = self._media_text(disk.get("MediaType"))
            size = float(disk.get("Size") or 0) / 1024 ** 3
            name = disk.get("FriendlyName") or "Диск"
            extra = []
            hours = disk.get("PowerOnHours")
            temp = disk.get("Temperature")
            wear = disk.get("Wear")
            errors = disk.get("ReadErrors")
            if hours:
                extra.append(f"наработка {int(hours)} ч")
            if temp:
                extra.append(f"{int(temp)} °C")
            if wear:
                extra.append(f"износ {int(wear)}%")
            if errors:
                extra.append(f"ошибок чтения {int(errors)}")
            extra_text = ("  [" + ", ".join(extra) + "]") if extra else ""
            self.disk_list.addItem(f"{name} — {media}, {size:.0f} ГБ — состояние: {health}{extra_text}")
            summary.append(f"{name}: {health}")
            grade = smart_grade(health == "Good", read_errors=int(errors or 0))
            if hours and power_on_hours_grade(int(hours)) == "warn" and grade == "ok":
                grade = "warn"
            if grade == "bad" or worst_grade == "bad":
                worst_grade = "bad"
            elif grade == "warn":
                worst_grade = "warn"
            if health != "Good":
                healthy = False
        self.info.setText(f"Накопителей: {len(data)}. Состояние: {'OK' if healthy else 'есть проблемы'}")
        self.health_summary = "; ".join(summary)
        self.healthy = healthy
        self.smart_grade = worst_grade
        self._smart_ready()
