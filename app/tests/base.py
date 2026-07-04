from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class BaseTestPage(QWidget):
    completed = pyqtSignal(int, str, bool)
    wants_raw_keys = False
    title = ""
    hint = ""

    def __init__(self, index, parent=None):
        super().__init__(parent)
        self.index = index
        self.details = ""
        self.result = None
        self.summary = ""
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)
        self.hint_label = QLabel(self.hint)
        self.hint_label.setObjectName("hintLabel")
        self.hint_label.setWordWrap(True)
        root.addWidget(self.hint_label)
        self.body = QVBoxLayout()
        self.body.setSpacing(8)
        root.addLayout(self.body, 1)
        controls = QHBoxLayout()
        self.status_label = QLabel("Статус: ожидание")
        self.status_label.setObjectName("statusLabel")
        controls.addWidget(self.status_label, 1)
        self.pass_button = QPushButton("Пройден  [Space / Enter]")
        self.pass_button.setObjectName("passButton")
        self.skip_button = QPushButton("Пропустить")
        self.skip_button.setObjectName("skipButton")
        self.pass_button.clicked.connect(lambda: self.finish("Пройден"))
        self.skip_button.clicked.connect(lambda: self.finish("Пропущен"))
        controls.addWidget(self.pass_button)
        controls.addWidget(self.skip_button)
        root.addLayout(controls)
        self.build_body()

    def build_body(self):
        pass

    def on_enter(self):
        pass

    def on_leave(self):
        pass

    def set_status(self, text, state=None):
        colors = {True: "#66bb6a", False: "#ef5350", "warn": "#ffb74d", None: "#9aa7b4"}
        self.status_label.setText(f"Статус: {text}")
        self.status_label.setStyleSheet(f"color:{colors.get(state, '#9aa7b4')};font-weight:600;")

    def auto_ok(self, details="", advance=True):
        if details:
            self.details = details
        self.set_status("авто-ОК" + (f" — {details}" if details else ""), True)
        self.finish("Пройден (авто)", advance=advance)

    def finish(self, status, advance=True):
        self.result = status
        self.completed.emit(self.index, status, advance)
