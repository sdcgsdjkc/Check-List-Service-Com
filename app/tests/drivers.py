import json
import sys
import urllib.parse
import webbrowser

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QLabel, QListWidget, QProgressBar, QPushButton

from app.sysinfo import _powershell
from app.tests.base import BaseTestPage

CATALOG_URL = "https://www.catalog.update.microsoft.com/Search.aspx?q="

# Поиск + скачивание + установка драйверов через Windows Update Agent (COM)
WUA_INSTALL = r'''
$ErrorActionPreference = 'Stop'
try {
  $s = New-Object -ComObject Microsoft.Update.Session
  $se = $s.CreateUpdateSearcher()
  $r = $se.Search("IsInstalled=0 and Type='Driver'")
  if ($r.Updates.Count -eq 0) {
    Write-Output 'NONE'
  } else {
    $coll = New-Object -ComObject Microsoft.Update.UpdateColl
    foreach ($u in $r.Updates) {
      try { $u.AcceptEula() | Out-Null } catch {}
      Write-Output ('FOUND|' + $u.Title)
      $coll.Add($u) | Out-Null
    }
    $d = $s.CreateUpdateDownloader(); $d.Updates = $coll; $d.Download() | Out-Null
    $i = $s.CreateUpdateInstaller(); $i.Updates = $coll; $ir = $i.Install()
    Write-Output ('RESULT|' + $ir.ResultCode + '|' + $ir.RebootRequired)
  }
} catch {
  Write-Output ('ERR|' + $_.Exception.Message)
}
'''


class DriversWorker(QThread):
    done = pyqtSignal(object)

    def run(self):
        if sys.platform != "win32":
            self.done.emit(None)
            return
        try:
            raw = _powershell(
                'Get-CimInstance Win32_PnPEntity -Filter "ConfigManagerErrorCode<>0" | '
                "Select-Object Name, ConfigManagerErrorCode, HardwareID, DeviceID | ConvertTo-Json",
                timeout=60)
            if not raw:
                self.done.emit([])
                return
            data = json.loads(raw)
            if isinstance(data, dict):
                data = [data]
            self.done.emit(data)
        except Exception:
            self.done.emit(None)


class DriverInstallWorker(QThread):
    done = pyqtSignal(object)

    def run(self):
        if sys.platform != "win32":
            self.done.emit({"error": "установка драйверов доступна только на Windows"})
            return
        try:
            raw = _powershell(WUA_INSTALL, timeout=900)
        except Exception as exc:
            self.done.emit({"error": f"Windows Update недоступен: {exc}"})
            return
        found, reboot, result, error, none = [], False, None, None, False
        for line in raw.splitlines():
            line = line.strip()
            if line == "NONE":
                none = True
            elif line.startswith("FOUND|"):
                found.append(line[6:])
            elif line.startswith("RESULT|"):
                parts = line.split("|")
                result = parts[1] if len(parts) > 1 else None
                reboot = len(parts) > 2 and parts[2].lower() in ("true", "1")
            elif line.startswith("ERR|"):
                error = line[4:]
        self.done.emit({"found": found, "reboot": reboot, "result": result,
                        "error": error, "none": none})


class DriversPage(BaseTestPage):
    title = "Драйверы"
    auto = True
    hint = "Ожидайте, идет сканирование диспетчера устройств на наличие ошибок..."

    def build_body(self):
        self.busy = QProgressBar()
        self.busy.setRange(0, 0)
        self.busy.hide()
        self.info = QLabel("Сканирование не запускалось")
        self.install_button = QPushButton("🔧 Скачать и установить драйверы (Windows Update)")
        self.install_button.setObjectName("autoButton")
        self.install_button.setMinimumHeight(44)
        self.install_button.clicked.connect(self.start_install)
        self.install_button.hide()
        self.catalog_button = QPushButton("🔎 Найти драйверы по ID оборудования (каталог Microsoft)")
        self.catalog_button.setObjectName("ghostButton")
        self.catalog_button.setMinimumHeight(40)
        self.catalog_button.clicked.connect(self.open_catalog)
        self.catalog_button.hide()
        self.problem_list = QListWidget()
        self.body.addWidget(self.busy)
        self.body.addWidget(self.info)
        self.body.addWidget(self.install_button)
        self.body.addWidget(self.catalog_button)
        self.body.addWidget(self.problem_list, 1)
        self.worker = None
        self.install_worker = None
        self.hwids = []
        self._auto_mode = False
        self._install_tried = False

    def reset_state(self):
        self.problem_list.clear()
        self.info.setText("Сканирование не запускалось")
        self.install_button.hide()
        self.catalog_button.hide()
        self.hwids = []
        self._auto_mode = False
        self._install_tried = False

    def auto_start(self):
        # В авто-прогоне драйверы ставятся автоматически при обнаружении проблем
        self._auto_mode = True

    def on_enter(self):
        if self.worker is not None or self.install_worker is not None:
            return
        self.scan()

    def scan(self):
        self.problem_list.clear()
        self.install_button.hide()
        self.catalog_button.hide()
        self.hwids = []
        self.busy.show()
        self.info.setText("Опрос WMI (Win32_PnPEntity)...")
        self.set_status("идет проверка...")
        self.worker = DriversWorker(self)
        self.worker.done.connect(self.on_done)
        self.worker.start()

    def on_done(self, devices):
        self.worker = None
        self.busy.hide()
        if devices is None:
            self.info.setText("Автоматическая проверка недоступна (WMI не отвечает)")
            self.set_status("проверьте диспетчер устройств вручную", "warn")
            return
        if not devices:
            self.info.setText("Устройств с ошибками не найдено")
            self.summary = "ошибок нет"
            self.grade = "ok"
            self.auto_ok("ошибок в диспетчере устройств нет")
            return
        self.hwids = []
        for device in devices:
            name = device.get("Name") or "Неизвестное устройство"
            code = device.get("ConfigManagerErrorCode")
            hwid = self._hwid(device)
            if hwid:
                self.hwids.append(hwid)
                self.problem_list.addItem(f"⚠ {name} — код {code}\n      ID: {hwid}")
            else:
                self.problem_list.addItem(f"⚠ {name} — код ошибки {code}")
        self.details = f"устройств с ошибками: {len(devices)}"
        self.summary = f"проблемных устройств: {len(devices)}"
        self.grade = "bad"
        # Авто-прогон: сам ставим драйверы (один раз за прогон)
        if self._auto_mode and not self._install_tried:
            self.info.setText(f"Найдено проблемных устройств: {len(devices)}. "
                              "Устанавливаю драйверы автоматически...")
            self.set_status("найдены проблемы — ставлю драйверы автоматически...", "warn")
            self.start_install()
            return
        self.install_button.show()
        if self.hwids:
            self.catalog_button.show()
        if self._auto_mode and self._install_tried:
            # уже пробовали поставить, но проблемы остались — завершаем, чтобы авто-прогон шёл дальше
            self.info.setText(f"Осталось проблемных устройств: {len(devices)}. "
                              "Windows Update не помог — найдите драйверы по ID оборудования.")
            self.details = f"остались проблемы с драйверами: {len(devices)} (нужна установка по ID)"
            self.finish("Не пройден", advance=True)
            return
        self.info.setText(f"Найдено проблемных устройств: {len(devices)}. "
                          "Установите драйверы автоматически, найдите по ID оборудования или отметьте вручную.")
        self.set_status(f"найдены ошибки драйверов ({len(devices)})", False)

    @staticmethod
    def _catalog_query(hwid):
        # Для каталога Microsoft ищем по VEN_xxxx&DEV_xxxx (без SUBSYS/REV — иначе часто пусто)
        import re
        ven = re.search(r"VEN_[0-9A-Fa-f]{4}", hwid)
        dev = re.search(r"DEV_[0-9A-Fa-f]{4}", hwid)
        if ven and dev:
            return f"{ven.group()}&{dev.group()}"
        # USB и прочее: VID/PID
        vid = re.search(r"VID_[0-9A-Fa-f]{4}", hwid)
        pid = re.search(r"PID_[0-9A-Fa-f]{4}", hwid)
        if vid and pid:
            return f"{vid.group()}&{pid.group()}"
        tail = hwid.split("\\")[-1] if "\\" in hwid else hwid
        return tail.strip()

    @staticmethod
    def _hwid(device):
        raw = device.get("HardwareID")
        if isinstance(raw, list):
            raw = next((x for x in raw if x), None)
        if not raw:
            raw = device.get("DeviceID")
        return (raw or "").strip()

    def open_catalog(self):
        # Открывает официальный каталог Microsoft Update с поиском по ID (до 3 вкладок)
        opened = 0
        seen = set()
        for hwid in self.hwids:
            if opened >= 3:
                break
            query = self._catalog_query(hwid)
            if not query or query in seen:
                continue
            seen.add(query)
            try:
                webbrowser.open(CATALOG_URL + urllib.parse.quote(query))
                opened += 1
            except Exception:
                pass
        if opened:
            self.problem_list.addItem(f"🔎 Открыт каталог Microsoft для поиска по ID ({opened})")
            self.set_status("каталог драйверов открыт в браузере — скачайте подписанный драйвер", "warn")

    def start_install(self):
        if self.install_worker is not None:
            return
        self._install_tried = True
        self.install_button.hide()
        self.catalog_button.hide()
        self.busy.show()
        self.problem_list.addItem("— Поиск драйверов в Windows Update (может занять несколько минут)...")
        self.info.setText("Идёт скачивание и установка драйверов через Windows Update...")
        self.set_status("установка драйверов — не выключайте ноутбук...")
        self.install_worker = DriverInstallWorker(self)
        self.install_worker.done.connect(self.on_install_done)
        self.install_worker.start()

    def on_install_done(self, result):
        self.install_worker = None
        self.busy.hide()
        if result.get("error"):
            self.problem_list.addItem(f"✕ {result['error']}")
            if self.hwids:
                self.catalog_button.show()
            if self._auto_mode:
                self.details = f"не удалось установить драйверы автоматически: {result['error']}"
                self.set_status("не удалось установить драйверы автоматически", False)
                self.finish("Не пройден", advance=True)
                return
            self.install_button.show()
            self.set_status("не удалось установить драйверы автоматически", "warn")
            return
        if result.get("none"):
            self.problem_list.addItem("— В Windows Update нет драйверов — попробуйте поиск по ID оборудования")
            self.info.setText("Windows Update не нашёл драйверов. Ищите по ID в каталоге Microsoft или на сайте производителя.")
            if self.hwids:
                self.catalog_button.show()
            if self._auto_mode:
                self.details = "в Windows Update драйверов нет — нужна установка по ID"
                self.finish("Не пройден", advance=True)
                return
            self.set_status("в Windows Update драйверов нет — ищите по ID", "warn")
            return
        for title in result.get("found", []):
            self.problem_list.addItem(f"✓ Установлен: {title}")
        if result.get("reboot"):
            self.problem_list.addItem("↻ Требуется перезагрузка для завершения установки")
            self.info.setText("Драйверы установлены. Нужна перезагрузка, затем проверьте снова.")
            self.grade = "warn"
            self.summary = "драйверы установлены (нужна перезагрузка)"
            if self._auto_mode:
                self.details = "драйверы установлены автоматически — требуется перезагрузка"
                self.set_status("драйверы установлены — требуется перезагрузка", "warn")
                self.finish("Пройден (нужна перезагрузка)", advance=True)
                return
            self.set_status("драйверы установлены — требуется перезагрузка", "warn")
            return
        self.info.setText("Драйверы установлены. Повторная проверка...")
        self.set_status("драйверы установлены, перепроверяю...")
        self.scan()
