from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel

from app.tests.base import BaseTestPage

KEY_STYLE = "background:#1a222c;border:1px solid #2c3947;border-radius:4px;color:#8fa1b3;"
KEY_STYLE_OK = "background:#1e7e34;border:1px solid #27ae4b;border-radius:4px;color:#ffffff;font-weight:600;"

KEY_ROWS = [
    [("Esc", 1), ("F1", 59), ("F2", 60), ("F3", 61), ("F4", 62), ("F5", 63), ("F6", 64),
     ("F7", 65), ("F8", 66), ("F9", 67), ("F10", 68), ("F11", 87), ("F12", 88), ("Del", 339)],
    [("`", 41), ("1", 2), ("2", 3), ("3", 4), ("4", 5), ("5", 6), ("6", 7), ("7", 8),
     ("8", 9), ("9", 10), ("0", 11), ("-", 12), ("=", 13), ("Backspace", 14)],
    [("Tab", 15), ("Q", 16), ("W", 17), ("E", 18), ("R", 19), ("T", 20), ("Y", 21),
     ("U", 22), ("I", 23), ("O", 24), ("P", 25), ("[", 26), ("]", 27), ("\\", 43)],
    [("Caps", 58), ("A", 30), ("S", 31), ("D", 32), ("F", 33), ("G", 34), ("H", 35),
     ("J", 36), ("K", 37), ("L", 38), (";", 39), ("'", 40), ("Enter", 28)],
    [("LShift", 42), ("Z", 44), ("X", 45), ("C", 46), ("V", 47), ("B", 48), ("N", 49),
     ("M", 50), (",", 51), (".", 52), ("/", 53), ("RShift", 54)],
    [("LCtrl", 29), ("Win", 347), ("LAlt", 56), ("Space", 57), ("RAlt", 312), ("RCtrl", 285),
     ("←", 331), ("↑", 328), ("↓", 336), ("→", 333)],
]

SPECIAL = {
    "Esc": Qt.Key.Key_Escape, "F1": Qt.Key.Key_F1, "F2": Qt.Key.Key_F2, "F3": Qt.Key.Key_F3,
    "F4": Qt.Key.Key_F4, "F5": Qt.Key.Key_F5, "F6": Qt.Key.Key_F6, "F7": Qt.Key.Key_F7,
    "F8": Qt.Key.Key_F8, "F9": Qt.Key.Key_F9, "F10": Qt.Key.Key_F10, "F11": Qt.Key.Key_F11,
    "F12": Qt.Key.Key_F12, "Del": Qt.Key.Key_Delete, "Backspace": Qt.Key.Key_Backspace,
    "Tab": Qt.Key.Key_Tab, "Caps": Qt.Key.Key_CapsLock, "Enter": Qt.Key.Key_Return,
    "LShift": Qt.Key.Key_Shift, "RShift": None, "LCtrl": Qt.Key.Key_Control, "RCtrl": None,
    "LAlt": Qt.Key.Key_Alt, "RAlt": Qt.Key.Key_AltGr, "Win": Qt.Key.Key_Meta,
    "Space": Qt.Key.Key_Space, "←": Qt.Key.Key_Left, "↑": Qt.Key.Key_Up,
    "↓": Qt.Key.Key_Down, "→": Qt.Key.Key_Right,
}


class KeyboardPage(BaseTestPage):
    title = "Клавиатура"
    hint = ("Нажимайте все клавиши на клавиатуре по очереди, пока сетка не заполнится зеленым. "
            "Авто-зачет при 93% нажатых клавиш. Кнопки внизу — только мышью (клавиатура занята тестом).")
    wants_raw_keys = True
    THRESHOLD = 93

    def build_body(self):
        self.progress_label = QLabel()
        self.progress_label.setObjectName("bigValue")
        self.body.addWidget(self.progress_label)
        self.cells = {}
        self.scan_map = {}
        self.key_map = {}
        for row in KEY_ROWS:
            line = QHBoxLayout()
            line.setSpacing(4)
            for label, scan in row:
                cell = QLabel(label)
                cell.setAlignment(Qt.AlignmentFlag.AlignCenter)
                cell.setStyleSheet(KEY_STYLE)
                cell.setFixedHeight(34)
                cell.setMinimumWidth(28 + 8 * len(label))
                line.addWidget(cell, 4 if label == "Space" else 1)
                key_id = (label, scan)
                self.cells[key_id] = cell
                self.scan_map[scan] = key_id
                if label in SPECIAL:
                    fallback = SPECIAL[label]
                else:
                    fallback = ord(label) if len(label) == 1 else None
                if fallback is not None and fallback not in self.key_map:
                    self.key_map[fallback] = key_id
            self.body.addLayout(line)
        self.body.addStretch(1)
        self.pressed = set()
        self.total = len(self.cells)
        self.update_progress()

    def update_progress(self):
        percent = len(self.pressed) / self.total * 100
        self.progress_label.setText(f"Нажато {len(self.pressed)} из {self.total} ({percent:.0f}%)")

    def reset_state(self):
        self.pressed.clear()
        for cell in self.cells.values():
            cell.setStyleSheet(KEY_STYLE)
        self.update_progress()

    def on_enter(self):
        self.grabKeyboard()
        self.set_status("нажимайте клавиши...")

    def on_leave(self):
        self.releaseKeyboard()

    def event(self, e):
        if e.type() == QEvent.Type.KeyPress:
            if not e.isAutoRepeat():
                self.register(e)
            return True
        if e.type() == QEvent.Type.KeyRelease:
            return True
        return super().event(e)

    def register(self, e):
        key_id = self.scan_map.get(e.nativeScanCode()) or self.key_map.get(e.key())
        if key_id is None or key_id in self.pressed:
            return
        self.pressed.add(key_id)
        self.cells[key_id].setStyleSheet(KEY_STYLE_OK)
        self.update_progress()
        self.details = f"нажато {len(self.pressed)} из {self.total} клавиш"
        if self.result is None and len(self.pressed) / self.total * 100 >= self.THRESHOLD:
            self.auto_ok(self.details)
