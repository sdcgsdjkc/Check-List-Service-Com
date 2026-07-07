import atexit
import os
import shutil
import sys
import tempfile

from app.resources import resource_path

_state = {"tried": False, "computer": None, "sensor_type": None}


def _stable_dir():
    path = os.path.join(tempfile.gettempdir(), "ServiceCom", "lib")
    os.makedirs(path, exist_ok=True)
    return path


def _stage_dll(name, stable):
    src = resource_path(name)
    if not os.path.exists(src):
        return False
    dst = os.path.join(stable, name)
    try:
        if not os.path.exists(dst) or os.path.getsize(dst) != os.path.getsize(src):
            shutil.copy2(src, dst)
        return True
    except OSError:
        return os.path.exists(dst)


def _init():
    if _state["tried"]:
        return _state["computer"] is not None
    _state["tried"] = True
    if sys.platform != "win32":
        return False
    try:
        stable = _stable_dir()
        if not _stage_dll("LibreHardwareMonitorLib.dll", stable):
            return False
        _stage_dll("HidSharp.dll", stable)
        os.environ.setdefault("PYTHONNET_RUNTIME", "netfx")
        try:
            from pythonnet import load
            load("netfx")
        except Exception:
            pass
        import clr
        if stable not in sys.path:
            sys.path.insert(0, stable)
        clr.AddReference("LibreHardwareMonitorLib")
        from LibreHardwareMonitor.Hardware import Computer, SensorType
        computer = Computer()
        computer.IsCpuEnabled = True
        computer.IsGpuEnabled = True
        computer.IsMotherboardEnabled = True
        computer.Open()
        _state["computer"] = computer
        _state["sensor_type"] = SensorType
        atexit.register(close)
        return True
    except Exception:
        _state["computer"] = None
        return False


def read_temperature():
    if not _init():
        return None
    computer = _state["computer"]
    temperature_type = _state["sensor_type"].Temperature
    try:
        best = None
        for hardware in computer.Hardware:
            hardware.Update()
            for sensor in hardware.Sensors:
                if sensor.SensorType == temperature_type and sensor.Value is not None:
                    value = float(sensor.Value)
                    if 0 < value < 130:
                        best = value if best is None else max(best, value)
        return round(best, 1) if best is not None else None
    except Exception:
        return None


def read_gpu():
    if not _init():
        return None
    computer = _state["computer"]
    try:
        for hardware in computer.Hardware:
            if "gpu" not in str(hardware.HardwareType).lower():
                continue
            hardware.Update()
            load = temp = None
            for sensor in hardware.Sensors:
                if sensor.Value is None:
                    continue
                stype = str(sensor.SensorType).lower()
                sname = str(sensor.Name).lower()
                if stype == "load" and "core" in sname and load is None:
                    load = round(float(sensor.Value), 1)
                elif stype == "temperature" and "hot" not in sname and temp is None:
                    temp = round(float(sensor.Value), 1)
            return {"name": str(hardware.Name), "load": load, "temp": temp, "present": True}
        return {"name": None, "load": None, "temp": None, "present": False}
    except Exception:
        return None


def close():
    computer = _state.get("computer")
    if computer is not None:
        try:
            computer.Close()
        except Exception:
            pass
        _state["computer"] = None


def available():
    return _init()
