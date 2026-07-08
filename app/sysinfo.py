import glob
import json
import os
import platform
import re
import subprocess
import sys
import tempfile

import psutil
from PyQt6.QtCore import QThread, pyqtSignal

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def _powershell(script, timeout=30):
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
         "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;" + script],
        capture_output=True, timeout=timeout, creationflags=CREATE_NO_WINDOW)
    return completed.stdout.decode("utf-8", "replace").strip()


def _first(value):
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _battery_wear_windows():
    try:
        raw = _powershell(
            "$d=(Get-CimInstance -Namespace root/wmi -ClassName BatteryStaticData).DesignedCapacity;"
            "$f=(Get-CimInstance -Namespace root/wmi -ClassName BatteryFullChargedCapacity).FullChargedCapacity;"
            "@{d=$d;f=$f} | ConvertTo-Json")
        data = json.loads(raw)
        design = float(_first(data.get("d")))
        full = float(_first(data.get("f")))
        if design > 0 and full > 0:
            return design, full
    except Exception:
        pass
    try:
        raw = _powershell(
            "$b=Get-CimInstance Win32_Battery;"
            "@{d=$b.DesignCapacity;f=$b.FullChargeCapacity} | ConvertTo-Json")
        data = json.loads(raw)
        design = float(_first(data.get("d")))
        full = float(_first(data.get("f")))
        if design > 0 and full > 0:
            return design, full
    except Exception:
        pass
    return None


def _battery_wear_macos():
    try:
        out = subprocess.run(["ioreg", "-r", "-c", "AppleSmartBattery"],
                             capture_output=True, timeout=10).stdout.decode("utf-8", "replace")
        design = re.search(r'"DesignCapacity"\s*=\s*(\d+)', out)
        full = re.search(r'"AppleRawMaxCapacity"\s*=\s*(\d+)', out) or re.search(r'"MaxCapacity"\s*=\s*(\d+)', out)
        if design and full:
            d, f = float(design.group(1)), float(full.group(1))
            if d > 0 and f > 0:
                return d, f
    except Exception:
        pass
    return None


def _battery_wear_linux():
    for base in glob.glob("/sys/class/power_supply/BAT*"):
        for design_name, full_name in (("charge_full_design", "charge_full"),
                                       ("energy_full_design", "energy_full")):
            try:
                with open(f"{base}/{design_name}") as handle:
                    design = float(handle.read())
                with open(f"{base}/{full_name}") as handle:
                    full = float(handle.read())
                if design > 0 and full > 0:
                    return design / 1000.0, full / 1000.0
            except OSError:
                continue
    return None


def _battery_cycles_windows():
    if sys.platform != "win32":
        return None
    try:
        report = os.path.join(tempfile.gettempdir(), "servicecom_battery.xml")
        subprocess.run(["powercfg", "/batteryreport", "/xml", "/output", report],
                       capture_output=True, timeout=25, creationflags=CREATE_NO_WINDOW)
        with open(report, encoding="utf-8-sig", errors="replace") as handle:
            text = handle.read()
        try:
            os.remove(report)
        except OSError:
            pass
        match = re.search(r"<CycleCount>(\d+)</CycleCount>", text)
        if match:
            value = int(match.group(1))
            return value if value > 0 else None
    except Exception:
        return None
    return None


def collect_battery():
    if sys.platform == "win32":
        result = _battery_wear_windows()
    elif sys.platform == "darwin":
        result = _battery_wear_macos()
    else:
        result = _battery_wear_linux()
    if not result:
        battery = psutil.sensors_battery()
        if battery is None:
            return "нет АКБ", "стационарное устройство"
        return "н/д", f"заряд {battery.percent:.0f}%"
    design, full = result
    wear = max(0.0, (1.0 - full / design) * 100.0)
    note = f"{full:.0f} / {design:.0f} мВт·ч"
    cycles = _battery_cycles_windows()
    if cycles is not None:
        note += f" · {cycles} циклов"
    return f"{wear:.0f}%", note


def list_physical_disks():
    if sys.platform != "win32":
        return []
    system_index = None
    try:
        raw = _powershell("(Get-Partition -DriveLetter C -ErrorAction Stop | Get-Disk).Number")
        if raw.strip():
            system_index = int(raw.strip())
    except Exception:
        system_index = None
    disks = []
    try:
        raw = _powershell(
            "Get-CimInstance Win32_DiskDrive | Select-Object Index, Model, Size | ConvertTo-Json")
        data = json.loads(raw) if raw else []
        if isinstance(data, dict):
            data = [data]
        for item in data:
            try:
                if item.get("Index") is None:
                    continue
                index = int(item.get("Index"))
                size = int(item.get("Size") or 0)
                model = (item.get("Model") or f"Диск {index}").strip()
                disks.append({
                    "index": index,
                    "model": model,
                    "size": size,
                    "path": f"\\\\.\\PhysicalDrive{index}",
                    "is_system": (index == system_index),
                })
            except (TypeError, ValueError):
                continue
    except Exception:
        return []
    if system_index is None and disks:
        disks[0]["is_system"] = True
    disks.sort(key=lambda d: (not d["is_system"], d["index"]))
    return disks


CHASSIS_TYPES = {
    3: "ПК", 4: "ПК", 5: "ПК", 6: "ПК", 7: "ПК", 15: "ПК", 16: "ПК", 35: "ПК",
    8: "Ноутбук", 9: "Ноутбук", 10: "Ноутбук", 14: "Ноутбук", 30: "Планшет",
    31: "Ноутбук", 32: "Планшет", 13: "Моноблок",
}


def _device_type_from_chassis(code, battery):
    if code is not None:
        try:
            name = CHASSIS_TYPES.get(int(code))
            if name:
                return name
        except Exception:
            pass
    return "Ноутбук" if battery is not None else "ПК"


def collect_device_type():
    battery = None
    try:
        battery = psutil.sensors_battery()
    except Exception:
        pass
    code = None
    if sys.platform == "win32":
        try:
            raw = _powershell(
                "(Get-CimInstance Win32_SystemEnclosure).ChassisTypes | ConvertTo-Json")
            code = _first(json.loads(raw))
        except Exception:
            code = None
    return _device_type_from_chassis(code, battery)


def collect_specs():
    battery = None
    try:
        battery = psutil.sensors_battery()
    except Exception:
        pass
    specs = {
        "model": platform.node() or "н/д",
        "cpu": platform.processor() or "н/д",
        "ram": f"{psutil.virtual_memory().total / 1024 ** 3:.0f} ГБ",
        "device_type": "Ноутбук" if battery is not None else "ПК",
        "battery_wear": "н/д",
        "battery_note": "",
    }
    if sys.platform != "win32":
        specs["battery_wear"], specs["battery_note"] = collect_battery()
        return specs
    # одним вызовом PowerShell: модель, CPU и тип корпуса (вместо трёх процессов)
    try:
        raw = _powershell(
            "$cs=Get-CimInstance Win32_ComputerSystem;"
            "$pr=Get-CimInstance Win32_ComputerSystemProduct;"
            "$cpu=Get-CimInstance Win32_Processor | Select-Object -First 1;"
            "$ch=(Get-CimInstance Win32_SystemEnclosure).ChassisTypes;"
            "@{man=$cs.Manufacturer;model=$cs.Model;ver=$pr.Version;cpu=$cpu.Name;chassis=$ch} "
            "| ConvertTo-Json")
        data = json.loads(raw)
        model = " ".join(part for part in [data.get("man") or "", data.get("model") or ""] if part).strip()
        version = (data.get("ver") or "").strip()
        if version and version.lower() not in model.lower() and version.lower() != "none":
            model = f"{model} ({version})"
        if model:
            specs["model"] = model
        cpu = (data.get("cpu") or "").strip()
        if cpu:
            specs["cpu"] = cpu
        specs["device_type"] = _device_type_from_chassis(_first(data.get("chassis")), battery)
    except Exception:
        pass
    specs["battery_wear"], specs["battery_note"] = collect_battery()
    return specs


def read_temperature():
    if sys.platform == "win32":
        try:
            from app.temperature import read_temperature as read_lhm
            value = read_lhm()
            if value is not None:
                return value
        except Exception:
            pass
        try:
            raw = _powershell(
                "(Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature "
                "-ErrorAction Stop | Select-Object -First 1).CurrentTemperature", timeout=8)
            if raw:
                celsius = float(raw) / 10.0 - 273.15
                if -40 < celsius < 130:
                    return round(celsius, 1)
        except Exception:
            pass
        for namespace in ("root/LibreHardwareMonitor", "root/OpenHardwareMonitor"):
            try:
                raw = _powershell(
                    f"(Get-CimInstance -Namespace {namespace} -ClassName Sensor "
                    "-ErrorAction Stop | Where-Object {$_.SensorType -eq 'Temperature'} | "
                    "Measure-Object -Property Value -Maximum).Maximum", timeout=8)
                if raw:
                    celsius = float(raw)
                    if 0 < celsius < 130:
                        return round(celsius, 1)
            except Exception:
                continue
        return None
    try:
        temps = psutil.sensors_temperatures()
        best = None
        for entries in temps.values():
            for entry in entries:
                if entry.current and entry.current > 0:
                    best = max(best or 0.0, entry.current)
        return round(best, 1) if best else None
    except Exception:
        return None


class SpecsWorker(QThread):
    ready = pyqtSignal(dict)

    def run(self):
        self.ready.emit(collect_specs())
