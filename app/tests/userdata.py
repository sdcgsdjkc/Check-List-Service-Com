from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QLabel, QListWidget, QProgressBar

from app.tests.base import BaseTestPage


class ScanWorker(QThread):
    done = pyqtSignal(list)
    IGNORE = {"desktop.ini", "thumbs.db", ".ds_store", ".localized"}
    FOLDERS = ("Desktop", "Documents", "Downloads", "Pictures", "Videos", "Music")

    def run(self):
        found = []
        home = Path.home()
        for folder in self.FOLDERS:
            root = home / folder
            if not root.is_dir():
                continue
            try:
                for entry in root.iterdir():
                    name = entry.name.lower()
                    if name in self.IGNORE or name.endswith(".lnk") or name.startswith("~"):
                        continue
                    suffix = "\\" if entry.is_dir() else ""
                    found.append(f"{folder}\\{entry.name}{suffix}")
            except OSError:
                continue
        self.done.emit(found)


class UserDataPage(BaseTestPage):
    title = "Сохранение данных"
    auto = True
    hint = "Проверка пользовательских данных на Рабочем столе и в профиле..."

    def build_body(self):
        self.busy = QProgressBar()
        self.busy.setRange(0, 0)
        self.busy.hide()
        self.info = QLabel("Сканирование не запускалось")
        self.info.setObjectName("bigValue")
        self.found_list = QListWidget()
        self.body.addWidget(self.busy)
        self.body.addWidget(self.info)
        self.body.addWidget(self.found_list, 1)
        self.worker = None

    def reset_state(self):
        self.found_list.clear()
        self.info.setText("Сканирование не запускалось")
        self.info.setStyleSheet("")

    def on_enter(self):
        if self.worker is not None:
            return
        self.busy.show()
        self.info.setText("Сканирование Desktop, Documents, Downloads...")
        self.set_status("идет проверка профиля...")
        self.worker = ScanWorker(self)
        self.worker.done.connect(self.on_done)
        self.worker.start()

    def on_done(self, found):
        self.busy.hide()
        if not found:
            self.info.setText("Чистая ОС")
            self.info.setStyleSheet("color:#66bb6a;font-size:17px;font-weight:700;padding:6px;")
            self.summary = "чистая ОС"
            self.grade = "ok"
            self.auto_ok("чистая ОС, данные пользователя не обнаружены")
            return
        for item in found[:300]:
            self.found_list.addItem(item)
        if len(found) > 300:
            self.found_list.addItem(f"... и еще {len(found) - 300} объектов")
        self.info.setText(f"Данные пользователя обнаружены: {len(found)} объектов")
        self.info.setStyleSheet("color:#ffb74d;font-size:17px;font-weight:700;padding:6px;")
        self.details = f"обнаружены данные пользователя ({len(found)} объектов)"
        self.summary = f"данные пользователя: {len(found)} объектов"
        self.grade = "warn"
        self.set_status("данные пользователя обнаружены — согласуйте сохранение", "warn")
