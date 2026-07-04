import re

import psutil
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QLabel, QProgressBar

from app.tests.base import BaseTestPage


class MemoryWorker(QThread):
    progress = pyqtSignal(int)
    done = pyqtSignal(bool, str)

    PATTERNS = (0x00, 0x55, 0xAA, 0xFF)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._abort = False

    def stop(self):
        self._abort = True
        self.wait(6000)

    SEGMENT_CAP_MB = 512

    def run(self):
        try:
            mb = 1024 * 1024
            chunk = 16 * mb
            memory = psutil.virtual_memory()
            total_mb = memory.total // mb
            target_mb = max(64, total_mb // 2)
            avail_mb = memory.available // mb
            seg_mb = max(64, min(self.SEGMENT_CAP_MB, target_mb, avail_mb - 1536))
            seg_mb = (seg_mb // 16) * 16 or 64
            seg_bytes = seg_mb * mb
            segments = max(1, (target_mb + seg_mb - 1) // seg_mb)
            chunks_per_seg = seg_bytes // chunk
            total_fills = segments * len(self.PATTERNS) * chunks_per_seg
            filled = 0
            errors = 0
            tested_mb = 0
            for _ in range(segments):
                if self._abort:
                    return
                buffer = bytearray(seg_bytes)
                for pattern in self.PATTERNS:
                    if self._abort:
                        return
                    filler = bytes([pattern]) * chunk
                    for offset in range(0, seg_bytes, chunk):
                        buffer[offset:offset + chunk] = filler
                        filled += 1
                        if filled % 8 == 0:
                            self.progress.emit(min(99, int(filled / total_fills * 100)))
                    if buffer.count(pattern) != seg_bytes:
                        errors += 1
                tested_mb += seg_mb
                del buffer
            self.progress.emit(100)
            note = (f"ОЗУ устройства {total_mb} МБ, цель — половина ({target_mb} МБ), "
                    f"проверено {tested_mb} МБ (сегмент {seg_mb} МБ × {segments}) "
                    f"× {len(self.PATTERNS)} паттерна, ошибок: {errors}")
            self.done.emit(errors == 0, note)
        except MemoryError:
            self.done.emit(False, "нехватка памяти при выделении блока")
        except Exception as exc:
            self.done.emit(False, f"сбой теста: {exc}")


class MemoryPage(BaseTestPage):
    title = "ОЗУ"
    hint = "Ожидайте завершения экспресс-теста оперативной памяти..."

    def build_body(self):
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.info = QLabel("Тест не запускался")
        self.body.addWidget(self.bar)
        self.body.addWidget(self.info)
        self.body.addStretch(1)
        self.worker = None

    def on_enter(self):
        if self.worker is not None:
            return
        self.info.setText("Идет запись и проверка паттернов 0x55 / 0xAA...")
        self.set_status("идет экспресс-тест ОЗУ...")
        self.worker = MemoryWorker(self)
        self.worker.progress.connect(self.bar.setValue)
        self.worker.done.connect(self.on_done)
        self.worker.start()

    def on_leave(self):
        if self.worker is not None and self.worker.isRunning():
            self.worker.stop()

    def on_done(self, ok, details):
        self.info.setText(details)
        match = re.search(r"проверено (\d+) МБ", details)
        tested = f"{match.group(1)} МБ" if match else ""
        errors = "0 ошибок" if ok else "есть ошибки"
        self.summary = " · ".join(part for part in [tested, errors] if part)
        if ok:
            self.auto_ok(details)
        else:
            self.details = details
            self.set_status(details, False)
