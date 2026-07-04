from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QLabel, QPushButton, QWidget

from app.tests.base import BaseTestPage


class ColorScreen(QWidget):
    finished = pyqtSignal(int, int)
    COLORS = [
        (QColor("#FFFFFF"), "Белый"),
        (QColor("#000000"), "Черный"),
        (QColor("#FF0000"), "Красный"),
        (QColor("#00FF00"), "Зеленый"),
        (QColor("#0000FF"), "Синий"),
    ]

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setCursor(Qt.CursorShape.BlankCursor)
        self.index = 0
        self.max_seen = 1
        self._emitted = False

    def paintEvent(self, e):
        painter = QPainter(self)
        color, name = self.COLORS[self.index]
        painter.fillRect(self.rect(), color)
        painter.setPen(QColor(128, 128, 128))
        painter.drawText(20, self.height() - 20,
                         f"{name} ({self.index + 1}/{len(self.COLORS)}) — клик: следующий цвет, Esc: выход")

    def advance(self):
        if self.index + 1 >= len(self.COLORS):
            self.close()
            return
        self.index += 1
        self.max_seen = max(self.max_seen, self.index + 1)
        self.update()

    def mousePressEvent(self, e):
        self.advance()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.close()
        elif e.key() in (Qt.Key.Key_Space, Qt.Key.Key_Right, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.advance()

    def closeEvent(self, e):
        if not self._emitted:
            self._emitted = True
            self.finished.emit(self.max_seen, len(self.COLORS))
        super().closeEvent(e)


class DisplayPage(BaseTestPage):
    title = "Матрица"
    hint = "Кликните для перехода в полноэкранный режим. Переключайте цвета кликом. Выход — Esc."

    def build_body(self):
        self.launch_button = QPushButton("Запустить полноэкранный тест матрицы")
        self.launch_button.setMinimumHeight(56)
        self.launch_button.clicked.connect(self.launch)
        info = QLabel("Цвета: Белый → Черный → Красный → Зеленый → Синий")
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body.addStretch(1)
        self.body.addWidget(self.launch_button)
        self.body.addWidget(info)
        self.body.addStretch(1)
        self.screen_widget = None

    def launch(self):
        self.screen_widget = ColorScreen()
        self.screen_widget.finished.connect(self.on_screen_done)
        self.screen_widget.showFullScreen()

    def on_screen_done(self, seen, total):
        self.screen_widget = None
        if seen >= total:
            self.auto_ok(f"показаны все {total} цветов")
        else:
            self.details = f"показано цветов: {seen}/{total}"
            self.set_status(f"показано цветов: {seen} из {total}", "warn")
