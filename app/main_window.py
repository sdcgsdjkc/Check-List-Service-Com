from PyQt6.QtCore import QEvent, Qt, QTimer
from PyQt6.QtGui import QColor, QPixmap
from PyQt6.QtWidgets import (QApplication, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                             QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
                             QPlainTextEdit, QPushButton, QStackedWidget, QTextEdit,
                             QVBoxLayout, QWidget)

from app import config
from app.report import ReportPage
from app.resources import resource_path
from app.sysinfo import SpecsWorker
from app.tests import PAGE_CLASSES
from app.tests.base import BaseTestPage
from app.theme import colors, stylesheet
from app.updater import VERSION, UpdateChecker, UpdateDownloader, can_update, is_configured


class MainWindow(QMainWindow):
    def __init__(self, theme_name="dark"):
        super().__init__()
        self.theme_name = theme_name if theme_name in ("dark", "light") else "dark"
        self.setWindowTitle("SCAA — Service Com Auto Analyze")
        self.resize(1200, 760)
        self.specs = {"model": "определяется...", "cpu": "определяется...",
                      "ram": "...", "device_type": "…", "battery_wear": "...", "battery_note": ""}
        central = QWidget()
        central.setObjectName("root")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 14, 14, 6)
        root.setSpacing(12)
        root.addWidget(self._build_header())
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(12)
        self.checklist = QListWidget()
        self.checklist.setFixedWidth(280)
        self.stack = QStackedWidget()
        self.stack.setObjectName("contentCard")
        self.pages = []
        self.results = []
        for index, page_class in enumerate(PAGE_CLASSES):
            page = page_class(index)
            page.completed.connect(self.on_completed)
            self.pages.append(page)
            self.stack.addWidget(page)
            self.results.append({"title": page_class.title, "result": "Не выполнялся",
                                 "details": "", "summary": "", "grade": ""})
            QListWidgetItem(f"{index + 1}. {page_class.title}", self.checklist)
        self.report_page = ReportPage(colors(self.theme_name))
        self.stack.addWidget(self.report_page)
        QListWidgetItem("Итоговый отчет", self.checklist)
        body.addWidget(self.checklist)
        body.addWidget(self.stack, 1)
        root.addLayout(body, 1)
        root.addLayout(self._build_footer())
        self.current_row = -1
        self.auto_running = False
        self.auto_queue = []
        self.checklist.currentRowChanged.connect(self.switch_page)
        self.checklist.setCurrentRow(0)
        self.specs_worker = SpecsWorker(self)
        self.specs_worker.ready.connect(self.apply_specs)
        self.specs_worker.start()
        self.update_checker = UpdateChecker(self)
        self.update_checker.result.connect(self.on_update_found)
        self.update_checker.start()
        self.update_downloader = None

    def on_update_found(self, info):
        if not info:
            return
        notes = f"\n\nЧто нового:\n{info['notes']}" if info.get("notes") else ""
        answer = QMessageBox.question(
            self, "Доступно обновление",
            f"Доступна новая версия {info['version']} (у вас {VERSION}).\n"
            f"Обновить программу прямо сейчас?{notes}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        if not can_update():
            QMessageBox.information(
                self, "Обновление",
                "Обновление доступно только для собранной программы (.exe). "
                f"Скачайте новую версию ({info['version']}) со страницы релизов на GitHub.")
            return
        self.update_downloader = UpdateDownloader(info["url"], self)
        self.update_downloader.done.connect(self.on_update_done)
        self.update_downloader.start()

    def on_update_done(self, ok, message, restart):
        if not ok:
            QMessageBox.warning(self, "Обновление не удалось", f"Не удалось обновить:\n{message}")
            return
        if restart:
            QMessageBox.information(
                self, "Обновление",
                "Программа сейчас закроется, обновится и запустится заново автоматически.")
            QApplication.instance().quit()
        else:
            QMessageBox.information(
                self, "Обновление завершено",
                "Программа обновлена. Новая версия вступит в силу при следующем запуске.\n\n"
                "Закройте программу и запустите заново.")

    def _build_header(self):
        header = QWidget()
        header.setObjectName("header")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(14)
        logo = QLabel()
        logo.setObjectName("logoLabel")
        pixmap = QPixmap(resource_path("logo.png"))
        if pixmap.isNull():
            logo.hide()
        else:
            logo.setPixmap(pixmap.scaledToHeight(
                40, Qt.TransformationMode.SmoothTransformation))
        layout.addWidget(logo)
        brand_box = QVBoxLayout()
        brand_box.setSpacing(0)
        brand = QLabel("SCAA")
        brand.setObjectName("brandLabel")
        sub = QLabel("Service Com Auto Analyze · диагностика ПК, ноутбуков и моноблоков")
        sub.setObjectName("brandSub")
        brand_box.addWidget(brand)
        brand_box.addWidget(sub)
        layout.addLayout(brand_box)
        layout.addStretch(1)
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(2)
        self.model_value = self._spec_cell(grid, 0, 0, "Модель:")
        self.cpu_value = self._spec_cell(grid, 1, 0, "CPU:")
        self.type_value = self._spec_cell(grid, 0, 1, "Тип:")
        self.ram_value = self._spec_cell(grid, 1, 1, "ОЗУ:")
        self.battery_value = self._spec_cell(grid, 0, 2, "Износ АКБ:")
        layout.addLayout(grid)
        self.theme_button = QPushButton()
        self.theme_button.setObjectName("themeButton")
        self.theme_button.setToolTip("Сменить тему (тёмная / светлая)")
        self.auto_button = QPushButton("▶ Авто-прогон")
        self.auto_button.setToolTip("Запустить все автоматические тесты подряд без участия мастера")
        self.auto_button.clicked.connect(self.start_auto_run)
        layout.addWidget(self.auto_button)
        self.theme_button.clicked.connect(self.toggle_theme)
        self._update_theme_button()
        layout.addWidget(self.theme_button)
        self.update_button = QPushButton("Обновления")
        self.update_button.setToolTip("Проверить обновления на GitHub")
        self.update_button.clicked.connect(self.check_updates_manual)
        layout.addWidget(self.update_button)
        about_button = QPushButton("О программе")
        about_button.clicked.connect(self.show_about)
        layout.addWidget(about_button)
        return header

    def check_updates_manual(self):
        if not is_configured():
            QMessageBox.information(self, "Обновления",
                                    "Автообновление не настроено в этой сборке.")
            return
        self.update_button.setEnabled(False)
        self.update_button.setText("Проверка…")
        self.manual_checker = UpdateChecker(self)
        self.manual_checker.result.connect(self.on_manual_result)
        self.manual_checker.start()

    def on_manual_result(self, info):
        self.update_button.setEnabled(True)
        self.update_button.setText("Обновления")
        if info:
            self.on_update_found(info)
        else:
            QMessageBox.information(
                self, "Обновления",
                f"Обновлений не найдено — у вас актуальная версия {VERSION}.\n"
                "Если считаете, что вышла новее — проверьте подключение к интернету.")

    def _update_theme_button(self):
        self.theme_button.setText("☀" if self.theme_name == "light" else "☾")

    def toggle_theme(self):
        self.theme_name = "light" if self.theme_name == "dark" else "dark"
        QApplication.instance().setStyleSheet(stylesheet(self.theme_name))
        self._update_theme_button()
        self.report_page.set_colors(colors(self.theme_name))
        data = config.load()
        data["theme"] = self.theme_name
        config.save(data)

    def _spec_cell(self, grid, row, column, caption):
        caption_label = QLabel(caption)
        caption_label.setObjectName("specLabel")
        value_label = QLabel("…")
        value_label.setObjectName("specValue")
        grid.addWidget(caption_label, row, column * 2)
        grid.addWidget(value_label, row, column * 2 + 1)
        return value_label

    def _build_footer(self):
        footer = QHBoxLayout()
        footer.setContentsMargins(12, 2, 12, 8)
        tip = QLabel("Space / Enter — отметить текущий пункт как «Пройден»")
        tip.setObjectName("devLabel")
        developer = QLabel("Разработчик: Владислав Артемьев")
        developer.setObjectName("devLabel")
        footer.addWidget(tip)
        footer.addStretch(1)
        footer.addWidget(developer)
        return footer

    def apply_specs(self, specs):
        self.specs = specs
        self.model_value.setText(specs.get("model", "н/д"))
        self.cpu_value.setText(specs.get("cpu", "н/д"))
        self.type_value.setText(specs.get("device_type", "—"))
        self.ram_value.setText(specs.get("ram", "н/д"))
        wear_text = specs.get("battery_wear", "н/д")
        note = specs.get("battery_note", "")
        self.battery_value.setText(wear_text + (f" ({note})" if note else ""))
        try:
            wear = float(wear_text.rstrip("%"))
            color = "#57c06a" if wear < 20 else "#e0b13a" if wear < 40 else "#ff5f5f"
            self.battery_value.setStyleSheet(f"color:{color};font-weight:700;")
        except ValueError:
            self.battery_value.setStyleSheet("color:#8a93a0;font-weight:600;")
        if self.current_row >= len(self.pages):
            self.report_page.refresh(self.specs, self.results)

    def switch_page(self, row):
        if row < 0 or row == self.current_row:
            return
        if 0 <= self.current_row < len(self.pages):
            try:
                self.pages[self.current_row].on_leave()
            except Exception:
                pass
        self.current_row = row
        self.stack.setCurrentIndex(row)
        if row < len(self.pages):
            page = self.pages[row]
            try:
                page.on_enter()
            except Exception as exc:
                page.set_status(f"ошибка теста: {exc}", "warn")
        else:
            for index, page in enumerate(self.pages):
                if page.details:
                    self.results[index]["details"] = page.details
                if page.summary:
                    self.results[index]["summary"] = page.summary
                if page.grade:
                    self.results[index]["grade"] = page.grade
            self.report_page.refresh(self.specs, self.results)

    def on_completed(self, index, status, advance):
        page = self.pages[index]
        self.results[index]["result"] = status
        self.results[index]["details"] = page.details
        self.results[index]["summary"] = page.summary
        self.results[index]["grade"] = page.grade
        item = self.checklist.item(index)
        passed = status.startswith("Пройден")
        marker = "✓" if passed else "↷"
        item.setText(f"{marker} {index + 1}. {page.title}")
        item.setForeground(QColor("#66bb6a") if passed else QColor("#ffb74d"))
        if self.auto_running and index == self.current_row:
            QTimer.singleShot(500, self._auto_next)
        elif advance:
            self.checklist.setCurrentRow(min(index + 1, self.checklist.count() - 1))

    def start_auto_run(self):
        pending = [i for i, page in enumerate(self.pages) if page.auto and page.result is None]
        if not pending:
            QMessageBox.information(self, "Авто-прогон",
                                   "Все автоматические тесты уже выполнены.")
            return
        self.auto_running = True
        self.auto_queue = pending
        self.auto_button.setEnabled(False)
        self.auto_button.setText("Авто-прогон идёт…")
        self._auto_next()

    def _auto_next(self):
        if not self.auto_running:
            return
        while self.auto_queue:
            index = self.auto_queue.pop(0)
            if self.pages[index].result is None:
                self.checklist.setCurrentRow(index)
                try:
                    self.pages[index].auto_start()
                except Exception:
                    pass
                return
        self._auto_finish()

    def _auto_finish(self):
        self.auto_running = False
        self.auto_button.setEnabled(True)
        self.auto_button.setText("▶ Авто-прогон")
        manual = [page.title for page in self.pages if not page.auto and page.result is None]
        text = "Автоматические тесты завершены."
        if manual:
            text += "\n\nОсталось пройти вручную:\n• " + "\n• ".join(manual)
        else:
            text += "\nВсе тесты пройдены — можно открыть отчёт."
        QMessageBox.information(self, "Авто-прогон", text)

    def eventFilter(self, obj, event):
        if event.type() != QEvent.Type.KeyPress:
            return False
        if event.key() not in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            return False
        if event.isAutoRepeat():
            return True
        if QApplication.activeWindow() is not self:
            return False
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QTextEdit, QPlainTextEdit)):
            return False
        page = self.stack.currentWidget()
        if isinstance(page, BaseTestPage) and not page.wants_raw_keys:
            page.pass_button.animateClick()
            return True
        return False

    def show_about(self):
        QMessageBox.about(
            self, "О программе",
            "<h3>SCAA</h3>"
            "<p><b>Service Com Auto Analyze</b><br>"
            f"Комплексная диагностика ПК, ноутбуков и моноблоков.<br>Версия {VERSION} (Portable)</p>"
            "<p>Разработчик: <b>Владислав Артемьев</b></p>"
            "<p>© 2026 Сервисный центр «Сервис • Com»</p>")

    def closeEvent(self, event):
        for page in self.pages:
            try:
                page.on_leave()
            except Exception:
                pass
        super().closeEvent(event)
