import json
import os
import re
import ssl
import subprocess
import sys
import tempfile
import urllib.request

from PyQt6.QtCore import QThread, pyqtSignal

VERSION = "1.1.7"

GITHUB_REPO = "sdcgsdjkc/Check-List-Service-Com"


def _configured():
    return "/" in GITHUB_REPO and "your-username" not in GITHUB_REPO


def is_configured():
    return _configured()


def _ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        try:
            return ssl.create_default_context()
        except Exception:
            return None


def _api_url():
    return f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


def _version_tuple(value):
    return tuple(int(part) for part in re.findall(r"\d+", value or "")) or (0,)


def _is_newer(remote, local):
    remote_t = _version_tuple(remote)
    local_t = _version_tuple(local)
    length = max(len(remote_t), len(local_t))
    remote_t += (0,) * (length - len(remote_t))
    local_t += (0,) * (length - len(local_t))
    return remote_t > local_t


def origin_exe():
    origin = os.environ.get("SERVICECOM_ORIGIN")
    if origin and getattr(sys, "frozen", False):
        candidate = os.path.join(origin, os.path.basename(sys.executable))
        if os.path.exists(candidate):
            return candidate
    return None


def update_target():
    flash = origin_exe()
    if flash:
        return flash, False
    if getattr(sys, "frozen", False):
        return os.path.abspath(sys.executable), True
    return None, False


def can_update():
    return update_target()[0] is not None


def cleanup_old():
    for base in filter(None, [origin_exe(),
                              os.path.abspath(sys.executable) if getattr(sys, "frozen", False) else None]):
        try:
            old = base + ".old"
            if os.path.exists(old):
                os.remove(old)
        except OSError:
            pass


def check():
    if not _configured():
        return None
    try:
        context = _ssl_context()
        request = urllib.request.Request(
            _api_url(), headers={"User-Agent": "ServiceCom",
                                 "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(request, timeout=8, context=context) as response:
            data = json.loads(response.read().decode("utf-8"))
        tag = str(data.get("tag_name", "")).strip()
        asset = next((item for item in data.get("assets", [])
                      if str(item.get("name", "")).lower().endswith(".exe")), None)
        if tag and asset and _is_newer(tag, VERSION):
            notes = str(data.get("body", "")).strip()
            return {"version": tag, "url": asset["browser_download_url"], "notes": notes[:500]}
    except Exception:
        return None
    return None


def _swap_and_relaunch(target, temp):
    script = (
        "@echo off\r\n"
        "ping -n 2 127.0.0.1 >NUL\r\n"
        "set /a tries=0\r\n"
        ":trymove\r\n"
        f'move /y "{temp}" "{target}" >NUL 2>&1\r\n'
        f'if not exist "{temp}" goto done\r\n'
        "set /a tries+=1\r\n"
        "if %tries% GEQ 120 goto relaunch\r\n"
        "ping -n 2 127.0.0.1 >NUL\r\n"
        "goto trymove\r\n"
        ":done\r\n"
        ":relaunch\r\n"
        f'start "" "{target}"\r\n'
        'del "%~f0"\r\n'
    )
    bat = os.path.join(tempfile.gettempdir(), "scaa_update.bat")
    with open(bat, "w", encoding="ascii", errors="replace") as handle:
        handle.write(script)
    subprocess.Popen(["cmd", "/c", bat], close_fds=True, creationflags=0x00000008)


class UpdateDownloader(QThread):
    progress = pyqtSignal(int)
    done = pyqtSignal(bool, str)

    def __init__(self, url, parent=None):
        super().__init__(parent)
        self.url = url

    def run(self):
        target, _ = update_target()
        if not target:
            self.done.emit(False, "не удалось определить файл программы для обновления")
            return
        temp = target + ".new"
        try:
            context = _ssl_context()
            request = urllib.request.Request(self.url, headers={"User-Agent": "ServiceCom"})
            with urllib.request.urlopen(request, timeout=120, context=context) as response:
                total = int(response.getheader("Content-Length") or 0)
                got = 0
                with open(temp, "wb") as handle:
                    while True:
                        chunk = response.read(262144)
                        if not chunk:
                            break
                        handle.write(chunk)
                        got += len(chunk)
                        if total:
                            self.progress.emit(min(100, int(got * 100 / total)))
            if total and got != total:
                raise ValueError(f"закачка оборвалась ({got} из {total} байт)")
            if got < 100000:
                raise ValueError("загруженный файл повреждён")
            self.progress.emit(100)
            _swap_and_relaunch(target, temp)
            self.done.emit(True, target)
        except Exception as exc:
            try:
                if os.path.exists(temp):
                    os.remove(temp)
            except OSError:
                pass
            self.done.emit(False, str(exc))


class UpdateChecker(QThread):
    result = pyqtSignal(object)

    def run(self):
        self.result.emit(check())
