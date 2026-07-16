import json
import re
import sys

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QLabel, QListWidget, QProgressBar, QPushButton

from app.sysinfo import _powershell
from app.tests.base import BaseTestPage

# Комбинированный установщик драйверов:
#   1) Windows Update Agent (COM) — то, что есть в WU
#   2) Каталог Microsoft Update по Hardware ID — качает .cab, распаковывает, ставит через pnputil
# Источник только официальный Microsoft (подписанные драйверы, без стороннего мусора).
WUA_CATALOG = r'''
$ErrorActionPreference = 'Stop'
$reboot = $false

# --- 1) Windows Update Agent ---
try {
  $s = New-Object -ComObject Microsoft.Update.Session
  $se = $s.CreateUpdateSearcher()
  $r = $se.Search("IsInstalled=0 and Type='Driver'")
  if ($r.Updates.Count -gt 0) {
    $coll = New-Object -ComObject Microsoft.Update.UpdateColl
    foreach ($u in $r.Updates) { try { $u.AcceptEula() | Out-Null } catch {}; Write-Output ('WUA_FOUND|' + $u.Title); $coll.Add($u) | Out-Null }
    $d = $s.CreateUpdateDownloader(); $d.Updates = $coll; $d.Download() | Out-Null
    $i = $s.CreateUpdateInstaller(); $i.Updates = $coll; $ir = $i.Install()
    if ($ir.RebootRequired) { $reboot = $true }
    Write-Output ('WUA_RESULT|' + $ir.ResultCode)
  } else { Write-Output 'WUA_NONE' }
} catch { Write-Output ('WUA_ERR|' + $_.Exception.Message) }

# --- 2) Каталог Microsoft Update по Hardware ID ---
$queries = @(%QUERIES%)
$work = Join-Path $env:TEMP 'scaa_drv'
Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $work | Out-Null
$gotCab = $false
foreach ($q in $queries) {
  try {
    $uri = "https://www.catalog.update.microsoft.com/Search.aspx?q=" + [uri]::EscapeDataString($q)
    $page = Invoke-WebRequest -UseBasicParsing -TimeoutSec 30 -Uri $uri
    $guids = [regex]::Matches($page.Content, '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}') | ForEach-Object { $_.Value.ToLower() } | Select-Object -Unique
    if (-not $guids) { Write-Output ('CAT_NONE|' + $q); continue }
    $done = $false
    foreach ($g in ($guids | Select-Object -First 4)) {
      if ($done) { break }
      try {
        $body = @{ updateIDs = '[{"size":0,"languages":"","uidInfo":"' + $g + '","updateID":"' + $g + '"}]' }
        $dd = Invoke-WebRequest -UseBasicParsing -TimeoutSec 30 -Method Post -Uri 'https://www.catalog.update.microsoft.com/DownloadDialog.aspx' -Body $body
        $urls = [regex]::Matches($dd.Content, 'https?://[^"'' ]+?\.cab') | ForEach-Object { $_.Value } | Select-Object -Unique
        foreach ($u in $urls) {
          $cab = Join-Path $work ([System.IO.Path]::GetFileName(($u -split '\?')[0]))
          Invoke-WebRequest -UseBasicParsing -TimeoutSec 180 -Uri $u -OutFile $cab
          $ext = Join-Path $work ([System.IO.Path]::GetFileNameWithoutExtension($cab))
          New-Item -ItemType Directory -Force -Path $ext | Out-Null
          & expand.exe $cab -F:* $ext | Out-Null
          $gotCab = $true; $done = $true
          Write-Output ('CAT_GOT|' + $q)
        }
      } catch {}
    }
    if (-not $done) { Write-Output ('CAT_NONE|' + $q) }
  } catch { Write-Output ('CAT_ERR|' + $q) }
}

# --- 3) установка распакованных inf ---
if ($gotCab) {
  try {
    $null = & pnputil /add-driver (Join-Path $work '*.inf') /subdirs /install 2>&1
    if ($LASTEXITCODE -eq 3010) { $reboot = $true }
    Write-Output ('PNP|' + $LASTEXITCODE)
  } catch { Write-Output 'PNP_ERR' }
}
Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
if ($reboot) { Write-Output 'REBOOT' }
Write-Output 'DONE'
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

    def __init__(self, queries, parent=None):
        super().__init__(parent)
        self.queries = queries

    def run(self):
        if sys.platform != "win32":
            self.done.emit({"error": "установка драйверов доступна только на Windows"})
            return
        arr = ",".join("'" + q.replace("'", "") + "'" for q in self.queries)
        script = WUA_CATALOG.replace("%QUERIES%", arr)
        try:
            raw = _powershell(script, timeout=1200)
        except Exception as exc:
            self.done.emit({"error": f"Windows Update / каталог недоступны: {exc}"})
            return
        installed, reboot, error, wua_none, cat_any = [], False, None, False, False
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("WUA_FOUND|"):
                installed.append(line[10:])
            elif line == "WUA_NONE":
                wua_none = True
            elif line.startswith("WUA_ERR|"):
                error = line[8:]
            elif line.startswith("CAT_GOT|"):
                cat_any = True
                installed.append(f"драйвер из каталога Microsoft ({line[8:]})")
            elif line == "REBOOT":
                reboot = True
        self.done.emit({"installed": installed, "reboot": reboot, "error": error,
                        "wua_none": wua_none, "cat_any": cat_any})


class DriversPage(BaseTestPage):
    title = "Драйверы"
    auto = True
    hint = "Ожидайте, идет сканирование диспетчера устройств на наличие ошибок..."

    def build_body(self):
        self.busy = QProgressBar()
        self.busy.setRange(0, 0)
        self.busy.hide()
        self.info = QLabel("Сканирование не запускалось")
        self.install_button = QPushButton("🔧 Установить недостающие драйверы (автоматически)")
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
        self.hwids = []
        self._auto_mode = False
        self._install_tried = False

    def reset_state(self):
        self.problem_list.clear()
        self.info.setText("Сканирование не запускалось")
        self.install_button.hide()
        self.hwids = []
        self._auto_mode = False
        self._install_tried = False

    def auto_start(self):
        # В авто-прогоне драйверы качаются и ставятся автоматически при обнаружении проблем
        self._auto_mode = True

    def on_enter(self):
        if self.worker is not None or self.install_worker is not None:
            return
        self.scan()

    def scan(self):
        self.problem_list.clear()
        self.install_button.hide()
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
        # авто-прогон: сам ставим драйверы (один раз за прогон)
        if self._auto_mode and not self._install_tried:
            self.info.setText(f"Найдено проблемных устройств: {len(devices)}. "
                              "Скачиваю и устанавливаю драйверы автоматически...")
            self.start_install()
            return
        if self._install_tried:
            # уже пробовали — часть не поставилась
            self.info.setText(f"Осталось проблемных устройств: {len(devices)}. "
                              "Не для всех нашлись драйверы в Windows Update / каталоге Microsoft.")
            self.details = f"остались проблемы с драйверами: {len(devices)}"
            if self._auto_mode:
                self.finish("Не пройден", advance=True)
                return
            self.install_button.setText("↻ Повторить установку драйверов")
            self.install_button.show()
            self.set_status("часть драйверов не установлена", False)
            return
        # ручной режим, первый показ
        self.info.setText(f"Найдено проблемных устройств: {len(devices)}. "
                          "Нажмите «Установить», чтобы скачать и поставить драйверы автоматически.")
        self.install_button.show()
        self.set_status(f"найдены ошибки драйверов ({len(devices)})", False)

    @staticmethod
    def _catalog_query(hwid):
        # Для каталога Microsoft ищем по VEN_xxxx&DEV_xxxx (без SUBSYS/REV — иначе часто пусто)
        ven = re.search(r"VEN_[0-9A-Fa-f]{4}", hwid)
        dev = re.search(r"DEV_[0-9A-Fa-f]{4}", hwid)
        if ven and dev:
            return f"{ven.group()}&{dev.group()}"
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

    def start_install(self):
        if self.install_worker is not None:
            return
        self._install_tried = True
        self.install_button.hide()
        self.busy.show()
        self.problem_list.addItem("— Поиск и установка драйверов (Windows Update + каталог Microsoft)...")
        self.problem_list.addItem("   Это может занять несколько минут, не выключайте ноутбук.")
        self.info.setText("Идёт скачивание и установка драйверов...")
        self.set_status("установка драйверов — не выключайте ноутбук...")
        queries = list(dict.fromkeys(self._catalog_query(h) for h in self.hwids if h))
        self.install_worker = DriverInstallWorker(queries, self)
        self.install_worker.done.connect(self.on_install_done)
        self.install_worker.start()

    def on_install_done(self, result):
        self.install_worker = None
        self.busy.hide()
        if result.get("error") and not result.get("installed"):
            self.problem_list.addItem(f"✕ {result['error']}")
            if self._auto_mode:
                self.details = f"не удалось установить драйверы: {result['error']}"
                self.set_status("не удалось установить драйверы автоматически", False)
                self.finish("Не пройден", advance=True)
                return
            self.install_button.setText("↻ Повторить установку драйверов")
            self.install_button.show()
            self.set_status("не удалось установить драйверы", "warn")
            return
        for title in result.get("installed", []):
            self.problem_list.addItem(f"✓ Установлен: {title}")
        if result.get("reboot"):
            self.problem_list.addItem("↻ Требуется перезагрузка для завершения установки")
            self.info.setText("Драйверы установлены. Нужна перезагрузка, затем проверьте снова.")
            self.grade = "warn"
            self.summary = "драйверы установлены (нужна перезагрузка)"
            if self._auto_mode:
                self.details = "драйверы установлены автоматически — требуется перезагрузка"
                self.finish("Пройден (нужна перезагрузка)", advance=True)
                return
            self.set_status("драйверы установлены — требуется перезагрузка", "warn")
            return
        self.info.setText("Установка завершена. Повторная проверка...")
        self.set_status("проверяю результат установки...")
        self.scan()
