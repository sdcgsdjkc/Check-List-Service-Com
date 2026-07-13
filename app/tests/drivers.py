import json
import sys

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QLabel, QListWidget, QProgressBar, QPushButton

from app.sysinfo import _powershell
from app.tests.base import BaseTestPage

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
                "Select-Object Name, ConfigManagerErrorCode | ConvertTo-Json", timeout=60)
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
        self.problem_list = QListWidget()
        self.body.addWidget(self.busy)
        self.body.addWidget(self.info)
        self.body.addWidget(self.install_button)
        self.body.addWidget(self.problem_list, 1)
        self.worker = None
        self.install_worker = None

    def reset_state(self):
        self.problem_list.clear()
        self.info.setText("Сканирование не запускалось")
        self.install_button.hide()

    def on_enter(self):
        if self.worker is not None or self.install_worker is not None:
            return
        self.scan()

    def scan(self):
        self.problem_list.clear()
        self.install_button.hide()
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
        for device in devices:
            name = device.get("Name") or "Неизвестное устройство"
            code = device.get("ConfigManagerErrorCode")
            self.problem_list.addItem(f"⚠ {name} — код ошибки {code}")
        self.info.setText(f"Найдено проблемных устройств: {len(devices)}. "
                          "Можно установить драйверы автоматически или отметить вручную.")
        self.details = f"устройств с ошибками: {len(devices)}"
        self.summary = f"проблемных устройств: {len(devices)}"
        self.grade = "bad"
        self.install_button.show()
        self.set_status(f"найдены ошибки драйверов ({len(devices)})", False)

    def start_install(self):
        if self.install_worker is not None:
            return
        self.install_button.hide()
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
            self.install_button.show()
            self.set_status("не удалось установить драйверы автоматически", "warn")
            return
        if result.get("none"):
            self.problem_list.addItem("— В Windows Update нет подходящих драйверов для этих устройств")
            self.info.setText("Windows Update не нашёл драйверов — установите вручную с сайта производителя")
            self.set_status("драйверы не найдены в Windows Update", "warn")
            return
        for title in result.get("found", []):
            self.problem_list.addItem(f"✓ Установлен: {title}")
        if result.get("reboot"):
            self.problem_list.addItem("↻ Требуется перезагрузка для завершения установки")
            self.info.setText("Драйверы установлены. Нужна перезагрузка, затем проверьте снова.")
            self.set_status("драйверы установлены — требуется перезагрузка", "warn")
            return
        self.info.setText("Драйверы установлены. Повторная проверка...")
        self.set_status("драйверы установлены, перепроверяю...")
        self.scan()
