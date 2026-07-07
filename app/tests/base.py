from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class BaseTestPage(QWidget):
    completed = pyqtSignal(int, str, bool)
    restarted = pyqtSignal(int)
    wants_raw_keys = False
    auto = False
    title = ""
    hint = ""

    def __init__(self, index, parent=None):
        super().__init__(parent)
        self.index = index
        self.details = ""
        self.result = None
        self.summary = ""
        self.grade = ""
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
        controls.setSpacing(8)
        self.status_label = QLabel("Статус: ожидание")
        self.status_label.setObjectName("statusLabel")
        controls.addWidget(self.status_label, 1)
        self.repeat_button = QPushButton("↻ Повторить")
        self.repeat_button.setObjectName("ghostButton")
        self.repeat_button.setToolTip("Сбросить и пройти этот тест заново")
        self.repeat_button.clicked.connect(self.repeat)
        self.skip_button = QPushButton("Пропустить")
        self.skip_button.setObjectName("skipButton")
        self.skip_button.clicked.connect(lambda: self.finish("Пропущен"))
        self.fail_button = QPushButton("✕ Не пройден")
        self.fail_button.setObjectName("failButton")
        self.fail_button.clicked.connect(lambda: self.finish("Не пройден"))
        self.pass_button = QPushButton("✓ Пройден")
        self.pass_button.setObjectName("passButton")
        self.pass_button.clicked.connect(lambda: self.finish("Пройден"))
        controls.addWidget(self.repeat_button)
        controls.addWidget(self.skip_button)
        controls.addWidget(self.fail_button)
        controls.addWidget(self.pass_button)
        root.addLayout(controls)
        self.build_body()

    def build_body(self):
        pass

    def retheme(self):
        self.update()

    def reset_state(self):
        pass

    def repeat(self):
        try:
            self.on_leave()
        except Exception:
            pass
        for attr in ("worker", "speed_worker", "monitor", "modules_worker", "engine"):
            if hasattr(self, attr):
                setattr(self, attr, None)
        self.result = None
        self.details = ""
        self.summary = ""
        self.grade = ""
        try:
            self.reset_state()
        except Exception:
            pass
        self.set_status("тест сброшен, запуск заново...")
        self.restarted.emit(self.index)
        try:
            self.on_enter()
        except Exception:
            pass

    def auto_start(self):
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
