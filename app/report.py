import datetime
import html
import os
import re

import psutil

from app.norms import GRADE_COLORS
from PyQt6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
                             QMessageBox, QPushButton, QTextEdit, QVBoxLayout, QWidget)


def _counts(results):
    passed = sum(1 for item in results if item["result"].startswith("Пройден"))
    skipped = sum(1 for item in results if item["result"].startswith("Пропущен"))
    not_run = sum(1 for item in results if item["result"].startswith("Не выполн"))
    problems = len(results) - passed - skipped - not_run
    return passed, skipped, not_run, problems


def verdict(results):
    passed, skipped, not_run, problems = _counts(results)
    if problems > 0:
        return "ЧЕК-ЛИСТ НЕ ПРОЙДЕН", "fail"
    if skipped > 0 or not_run > 0:
        return "ЧЕК-ЛИСТ ПРОЙДЕН ЧАСТИЧНО", "skip"
    return "ЧЕК-ЛИСТ ПРОЙДЕН", "pass"


def build_report(specs, results, order):
    line = "=" * 62
    thin = "-" * 62
    verdict_text, _ = verdict(results)
    passed, skipped, not_run, problems = _counts(results)
    rows = [line, verdict_text.center(62), line]
    rows.append(f"Заказ / модель: {order or '—'}")
    rows.append(f"Дата и время:   {datetime.datetime.now():%d.%m.%Y %H:%M}")
    rows.append(thin)
    rows.append(f"Тип:         {specs.get('device_type', '—')}")
    rows.append(f"Модель:      {specs.get('model', 'н/д')}")
    rows.append(f"Процессор:   {specs.get('cpu', 'н/д')}")
    rows.append(f"ОЗУ:         {specs.get('ram', 'н/д')}")
    wear = specs.get("battery_wear", "н/д")
    note = specs.get("battery_note", "")
    rows.append(f"Износ АКБ:   {wear}" + (f" ({note})" if note else ""))
    rows.append(thin)
    rows.append(f"Пройдено: {passed}   Пропущено: {skipped}   Проблемы: {problems}")
    rows.append(thin)
    for number, item in enumerate(results, 1):
        text = f"{number:>2}. {item['title']}: {item['result']}"
        if item.get("summary"):
            text += f" — {item['summary']}"
        rows.append(text)
    rows.append(line)
    rows.append("Сервисный центр «Сервис • Com»")
    rows.append(line)
    return "\n".join(rows)


def _status_color(result, c):
    if result.startswith("Пройден"):
        return c["pass"]
    if result.startswith("Пропущен"):
        return c["skip"]
    if result.startswith("Не выполн"):
        return c["notrun"]
    return c["fail"]


def build_report_html(specs, results, order, c):
    esc = html.escape
    passed, skipped, not_run, problems = _counts(results)
    verdict_text, state = verdict(results)
    verdict_color = c[state]
    wear = specs.get("battery_wear", "н/д")
    note = specs.get("battery_note", "")
    rule = f"<div style='border-bottom:1px solid {c['report_rule']};'></div>"
    parts = [f"<div style='font-family:Segoe UI;color:{c['report_text']};'>"]
    parts.append(f"<div align='center' style='color:{verdict_color};font-size:24pt;"
                 f"font-weight:800;letter-spacing:1px;'>{esc(verdict_text)}</div>")
    parts.append("<div style='height:10px;'></div>")
    parts.append(rule)
    parts.append("<table width='100%' cellspacing='0' cellpadding='0' style='margin-top:6px;'><tr>"
                 f"<td><span style='font-size:15pt;font-weight:800;color:{c['brand']};'>Сервис • Com</span></td>"
                 f"<td align='right' style='color:{c['report_muted']};font-size:10pt;'>"
                 f"{esc(order or '—')}&nbsp;&nbsp;·&nbsp;&nbsp;{datetime.datetime.now():%d.%m.%Y %H:%M}"
                 "</td></tr></table>")
    parts.append("<table width='100%' cellspacing='0' cellpadding='6'>")
    for label, value in (("Тип", specs.get("device_type", "—")),
                         ("Модель", specs.get("model", "н/д")),
                         ("Процессор", specs.get("cpu", "н/д")),
                         ("ОЗУ", specs.get("ram", "н/д")),
                         ("Износ АКБ", wear + (f"  ·  {note}" if note else ""))):
        parts.append(f"<tr><td width='20%' style='color:{c['report_muted']};'>{esc(label)}</td>"
                     f"<td style='color:{c['report_text']};'>{esc(str(value))}</td></tr>")
    parts.append("</table>")
    parts.append(rule)
    parts.append("<table width='100%' cellspacing='0' cellpadding='6'><tr>"
                 f"<td style='color:{c['pass']};'>Пройдено&nbsp;<b>{passed}</b></td>"
                 f"<td style='color:{c['skip']};'>Пропущено&nbsp;<b>{skipped}</b></td>"
                 f"<td style='color:{c['fail']};'>Проблемы&nbsp;<b>{problems}</b></td></tr></table>")
    parts.append(rule)
    parts.append("<table width='100%' cellspacing='0' cellpadding='7'>")
    for number, item in enumerate(results, 1):
        color = _status_color(item["result"], c)
        summary = item.get("summary")
        summary_html = (f"&nbsp;&nbsp;<span style='color:{c['report_muted']};font-size:9pt;'>"
                        f"{esc(summary)}</span>" if summary else "")
        grade = item.get("grade") or ""
        dot_color = c[GRADE_COLORS.get(grade, "notrun")]
        dot = f"<span style='color:{dot_color};'>●</span>" if grade else "<span style='color:transparent;'>●</span>"
        parts.append(
            f"<tr><td width='3%' valign='top'>{dot}</td>"
            f"<td width='4%' valign='top' style='color:{c['report_num']};'>{number:02d}</td>"
            f"<td valign='top' style='color:{c['report_text']};'>{esc(item['title'])}{summary_html}</td>"
            f"<td width='16%' valign='top' align='right' style='color:{color};font-weight:700;'>"
            f"{esc(item['result'])}</td></tr>")
    parts.append("</table>")
    parts.append(f"<p style='color:{c['report_muted']};font-size:8pt;margin-top:6px;'>"
                 f"<span style='color:{c['pass']};'>●</span> норма&nbsp;&nbsp;"
                 f"<span style='color:{c['skip']};'>●</span> внимание&nbsp;&nbsp;"
                 f"<span style='color:{c['fail']};'>●</span> критично</p>")
    parts.append("</div>")
    return "".join(parts)


class ReportPage(QWidget):
    def __init__(self, theme_colors, parent=None):
        super().__init__(parent)
        self._specs = {}
        self._results = []
        self._colors = theme_colors
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)
        self.title = QLabel("Итоговый отчет")
        self.title.setStyleSheet(f"font-size:18px;font-weight:700;color:{theme_colors['brand']};")
        root.addWidget(self.title)
        order_row = QHBoxLayout()
        order_row.addWidget(QLabel("Номер заказа или модель устройства:"))
        self.order_edit = QLineEdit()
        self.order_edit.setPlaceholderText("Например: 12345 или Lenovo IdeaPad 5")
        self.order_edit.textChanged.connect(self.regen)
        order_row.addWidget(self.order_edit, 1)
        root.addLayout(order_row)
        self.view = QTextEdit()
        self.view.setReadOnly(True)
        root.addWidget(self.view, 1)
        buttons = QHBoxLayout()
        self.copy_button = QPushButton("Скопировать в буфер")
        self.save_button = QPushButton("Сохранить на флешку")
        self.copy_button.clicked.connect(self.copy_report)
        self.save_button.clicked.connect(self.save_report)
        buttons.addStretch(1)
        buttons.addWidget(self.copy_button)
        buttons.addWidget(self.save_button)
        root.addLayout(buttons)
        self._apply_view_style()

    def _apply_view_style(self):
        c = self._colors
        self.view.setStyleSheet(f"QTextEdit{{background:{c['report_bg']};"
                                f"border:1px solid {c['report_border']};"
                                "border-radius:8px;padding:18px;}")
        self.title.setStyleSheet(f"font-size:18px;font-weight:700;color:{c['brand']};")

    def set_colors(self, theme_colors):
        self._colors = theme_colors
        self._apply_view_style()
        self.regen()

    def refresh(self, specs, results):
        self._specs = specs
        self._results = results
        self.regen()

    def regen(self):
        if self._results:
            self.view.setHtml(build_report_html(self._specs, self._results,
                                                self.order_edit.text().strip(), self._colors))

    def _plain(self):
        return build_report(self._specs, self._results, self.order_edit.text().strip())

    def copy_report(self):
        QApplication.clipboard().setText(self._plain())
        QMessageBox.information(self, "Готово", "Отчет скопирован в буфер обмена (текстом).")

    def _filename(self):
        name = re.sub(r'[\\/:*?"<>|]+', "_", self.order_edit.text().strip())
        return (name or "Отчет_диагностики") + ".txt"

    def _find_removable(self):
        try:
            for part in psutil.disk_partitions(all=False):
                if "removable" in part.opts.lower():
                    return part.mountpoint
        except Exception:
            return None
        return None

    def _write(self, path):
        with open(path, "w", encoding="utf-8-sig") as handle:
            handle.write(self._plain())

    def save_report(self):
        filename = self._filename()
        target = self._find_removable()
        if target:
            path = os.path.join(target, filename)
            try:
                self._write(path)
                QMessageBox.information(self, "Готово", f"Отчет сохранен на съемный диск (текстом):\n{path}")
                return
            except OSError:
                pass
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить отчет", filename, "Текстовые файлы (*.txt)")
        if not path:
            return
        try:
            self._write(path)
            QMessageBox.information(self, "Готово", f"Отчет сохранен:\n{path}")
        except OSError as exc:
            QMessageBox.warning(self, "Ошибка", f"Не удалось сохранить файл:\n{exc}")
