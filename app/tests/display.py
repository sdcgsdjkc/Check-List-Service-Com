from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QLinearGradient, QPainter
from PyQt6.QtWidgets import QLabel, QPushButton, QWidget

from app.tests.base import BaseTestPage


class ColorScreen(QWidget):
    finished = pyqtSignal(int, int)
    PATTERNS = [
        ("solid", "#FFFFFF", "Белый"),
        ("solid", "#000000", "Чёрный"),
        ("solid", "#FF0000", "Красный (субпиксель R)"),
        ("solid", "#00FF00", "Зелёный (субпиксель G)"),
        ("solid", "#0000FF", "Синий (субпиксель B)"),
        ("solid", "#00FFFF", "Голубой"),
        ("solid", "#FF00FF", "Пурпурный"),
        ("solid", "#FFFF00", "Жёлтый"),
        ("solid", "#808080", "Серый 50%"),
        ("gradient", None, "Градиент (полосы/зоны, засветы)"),
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
        kind, data, name = self.PATTERNS[self.index]
        if kind == "solid":
            painter.fillRect(self.rect(), QColor(data))
        else:
            gradient = QLinearGradient(0, 0, self.width(), 0)
            gradient.setColorAt(0.0, QColor("#000000"))
            gradient.setColorAt(1.0, QColor("#ffffff"))
            painter.fillRect(self.rect(), gradient)
        painter.setPen(QColor(128, 128, 128))
        painter.drawText(20, self.height() - 20,
                         f"{name} ({self.index + 1}/{len(self.PATTERNS)}) — "
                         "клик/пробел: далее, Esc: выход. Ищите точки другого цвета (битые пиксели).")

    def advance(self):
        if self.index + 1 >= len(self.PATTERNS):
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
            self.finished.emit(self.max_seen, len(self.PATTERNS))
        super().closeEvent(e)


class DisplayPage(BaseTestPage):
    title = "Матрица (битые пиксели)"
    hint = ("Полноэкранный тест матрицы: переключайте заливки и ищите точки другого цвета "
            "(битые/залипшие пиксели), полосы, засветы. Клик/пробел — далее, Esc — выход.")

    def build_body(self):
        self.launch_button = QPushButton("Запустить полноэкранный тест матрицы")
        self.launch_button.setMinimumHeight(56)
        self.launch_button.clicked.connect(self.launch)
        info = QLabel("Заливки: Белый · Чёрный · R · G · B · Голубой · Пурпурный · Жёлтый · Серый · Градиент")
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info.setWordWrap(True)
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
            self.summary = "все заливки показаны"
            self.auto_ok(f"показаны все {total} заливок (битые пиксели проверены)")
        else:
            self.details = f"показано заливок: {seen}/{total}"
            self.summary = f"показано {seen}/{total}"
            self.set_status(f"показано заливок: {seen} из {total}", "warn")