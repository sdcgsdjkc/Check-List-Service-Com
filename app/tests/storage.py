import json
import os
import shutil
import sys
import tempfile
import time

import psutil
from PyQt6.QtCore import QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import QLabel, QListWidget, QProgressBar

from app.sysinfo import _powershell
from app.tests.base import BaseTestPage

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
                        samples.append(win_bytes / (1024 * 1024) / max(1e-6, now - win_start))
                        win_start = now
                        win_bytes = 0
                    self.progress.emit(50 + int(read / total * 50))
            read_stats = _stats(samples, size_mb, time.perf_counter() - start)
            self.done.emit({"write": write_stats, "read": read_stats, "size_mb": size_mb})
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

    def run(self):
        if sys.platform == "win32":
            try:
                raw = _powershell(
                    "Get-PhysicalDisk | Select-Object FriendlyName, MediaType, HealthStatus, Size | ConvertTo-Json",
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
    MEDIA = {0: "Накопитель", 3: "HDD", 4: "SSD", 5: "SCM"}
    HEALTH = {0: "Good", 1: "Warning", 2: "Unhealthy"}

    def build_body(self):
        self.busy = QProgressBar()
        self.busy.setRange(0, 0)
        self.busy.hide()
        self.info = QLabel("Проверка не запускалась")
        self.speed_label = QLabel("Скорость: —")
        self.speed_label.setObjectName("bigValue")
        self.disk_list = QListWidget()
        self.body.addWidget(self.busy)
        self.body.addWidget(self.info)
        self.body.addWidget(self.speed_label)
        self.body.addWidget(self.disk_list, 1)
        self.worker = None
        self.speed_worker = None
        self.health_summary = ""
        self.healthy = True
        self.auto_pass = True
        self.countdown = 0
        self.advance_timer = QTimer(self)
        self.advance_timer.timeout.connect(self._countdown_tick)

    def on_enter(self):
        if self.worker is not None:
            return
        self.busy.show()
        self.info.setText("Чтение состояния накопителей...")
        self.set_status("идет проверка...")
        self.worker = StorageWorker(self)
        self.worker.done.connect(self.on_done)
        self.worker.start()

    def start_speed_test(self):
        self.busy.setRange(0, 100)
        self.busy.setValue(0)
        self.busy.show()
        self.speed_label.setText("Скорость: идет замер записи/чтения (2 ГБ)...")
        self.set_status("замер скорости накопителя...")
        self.speed_worker = SpeedWorker(self)
        self.speed_worker.progress.connect(self.busy.setValue)
        self.speed_worker.done.connect(self.on_speed_done)
        self.speed_worker.start()

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
        if write or read:
            speed_text = f"запись {write_text}, чтение {read_text}"
            w = f"{write['avg']}" if write else "н/д"
            r = f"{read['avg']}" if read else "н/д"
            state = self.health_summary.split(";")[0] if self.health_summary else ""
            self.summary = " · ".join(part for part in [state, f"чтение {r} / запись {w} МБ/с"] if part)
        else:
            speed_text = f"замер скорости не выполнен ({result.get('error', 'ошибка')})"
            self.summary = self.health_summary
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
        self.busy.hide()
        if data is None:
            self.info.setText("S.M.A.R.T. недоступен, выполняется только замер скорости")
            self.health_summary = "S.M.A.R.T. недоступен"
            self.auto_pass = False
            self.start_speed_test()
            return
        if isinstance(data, dict) and "fallback" in data:
            for disk in data["fallback"]:
                self.disk_list.addItem(f"{disk['FriendlyName']} — {disk['Size'] / 1024 ** 3:.0f} ГБ")
            self.info.setText("S.M.A.R.T. недоступен, показаны только разделы")
            self.health_summary = "S.M.A.R.T. недоступен"
            self.auto_pass = False
            self.start_speed_test()
            return
        if not data:
            self.info.setText("Накопители не найдены")
            self.set_status("накопители не обнаружены", False)
            return
        healthy = True
        summary = []
        for disk in data:
            health = self._health_text(disk.get("HealthStatus"))
            media = self._media_text(disk.get("MediaType"))
            size = float(disk.get("Size") or 0) / 1024 ** 3
            name = disk.get("FriendlyName") or "Диск"
            self.disk_list.addItem(f"{name} — {media}, {size:.0f} ГБ — состояние: {health}")
            summary.append(f"{name}: {health}")
            if health != "Good":
                healthy = False
        self.info.setText(f"Накопителей: {len(data)}. Состояние: {'OK' if healthy else 'есть проблемы'}")
        self.health_summary = "; ".join(summary)
        self.healthy = healthy
        self.start_speed_test()
