from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QWidget

from app.tests.base import BaseTestPage
from app.touchpad_hid import TouchpadTracker, is_supported


class TouchZone(QWidget):
    changed = pyqtSignal(int, int)
    COLS = 26
    ROWS = 13

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMinimumSize(500, 240)
        self.visited = set()

    def reset(self):
        self.visited.clear()
        self.update()
        self.changed.emit(0, self.COLS * self.ROWS)

    def _mark(self, col, row):
        col = min(self.COLS - 1, max(0, col))
        row = min(self.ROWS - 1, max(0, row))
        if (col, row) not in self.visited:
            self.visited.add((col, row))
            self.update()
            self.changed.emit(len(self.visited), self.COLS * self.ROWS)

    def mark_norm(self, xn, yn):
        self._mark(int(xn * self.COLS), int(yn * self.ROWS))

    def mouseMoveEvent(self, e):
        if self.width() < 2 or self.height() < 2:
            return
        self._mark(int(e.position().x() * self.COLS / self.width()),
                   int(e.position().y() * self.ROWS / self.height()))

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#0d1117"))
        cell_w = self.width() / self.COLS
        cell_h = self.height() / self.ROWS
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(229, 57, 53, 170))
        for col, row in self.visited:
            painter.drawRect(int(col * cell_w), int(row * cell_h), int(cell_w) + 1, int(cell_h) + 1)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QColor("#22303f"))
        for i in range(1, self.COLS):
            x = int(i * cell_w)
            painter.drawLine(x, 0, x, self.height())
        for i in range(1, self.ROWS):
            y = int(i * cell_h)
            painter.drawLine(0, y, self.width(), y)
        painter.setPen(QColor("#2c3947"))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))


class TouchpadPage(BaseTestPage):
    title = "Тачпад / Мышь"
    hint = ("Ноутбук: водите пальцем по тачпаду (на современных — трекинг по реальной поверхности). "
            "ПК/моноблок: водите мышью, закрашивая зону. Авто-зачет при 70% покрытия.")
    THRESHOLD = 70

    def build_body(self):
        top = QHBoxLayout()
        self.progress_label = QLabel("Покрытие: 0%")
        self.progress_label.setObjectName("bigValue")
        reset_button = QPushButton("Сбросить")
        top.addWidget(self.progress_label, 1)
        top.addWidget(reset_button)
        self.mode_label = QLabel("Режим: —")
        self.mode_label.setObjectName("specLabel")
        self.zone = TouchZone()
        reset_button.clicked.connect(self.zone.reset)
        self.zone.changed.connect(self.on_changed)
        self.body.addLayout(top)
        self.body.addWidget(self.mode_label)
        self.body.addWidget(self.zone, 1)
        self.tracker = None

    def on_enter(self):
        if not is_supported():
            self.mode_label.setText("Режим: курсор (raw-трекинг только на Windows)")
            return
        self.mode_label.setText("Режим: курсор (коснитесь тачпада для реального трекинга)")
        self.tracker = TouchpadTracker(self)
        self.tracker.contact.connect(self.zone.mark_norm)
        self.tracker.active.connect(self._on_hid_active)
        QApplication.instance().installNativeEventFilter(self.tracker)
        try:
            hwnd = int(self.window().winId())
            if not self.tracker.start(hwnd):
                self.mode_label.setText("Режим: курсор (Precision Touchpad не обнаружен)")
        except Exception:
            self.mode_label.setText("Режим: курсор")

    def _on_hid_active(self):
        self.mode_label.setText("Режим: реальный трекинг тачпада (Precision Touchpad)")

    def on_leave(self):
        if self.tracker is not None:
            try:
                self.tracker.stop()
                QApplication.instance().removeNativeEventFilter(self.tracker)
            except Exception:
                pass
            self.tracker = None

    def on_changed(self, visited, total):
        percent = visited / total * 100
        self.progress_label.setText(f"Покрытие: {percent:.0f}%")
        self.details = f"покрытие зоны {percent:.0f}%"
        if self.result is None and percent >= self.THRESHOLD:
            self.auto_ok(self.details)
