import json
import os
import re
import ssl
import sys
import urllib.request

from PyQt6.QtCore import QThread, pyqtSignal

VERSION = "1.1.3"

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
    return _version_tuple(remote) > _version_tuple(local)


def origin_exe():
    origin = os.environ.get("SERVICECOM_ORIGIN")
    if origin and getattr(sys, "frozen", False):
        candidate = os.path.join(origin, os.path.basename(sys.executable))
        if os.path.exists(candidate):
            return candidate
    return None


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


def download_and_install(url):
    target = origin_exe()
    if not target:
        return False, "флешка (исходный диск) недоступна для записи"
    temp = target + ".new"
    try:
        context = _ssl_context()
        request = urllib.request.Request(url, headers={"User-Agent": "ServiceCom"})
        with urllib.request.urlopen(request, timeout=120, context=context) as response:
            data = response.read()
        if len(data) < 100000:
            return False, "загруженный файл повреждён"
        with open(temp, "wb") as handle:
            handle.write(data)
        os.replace(temp, target)
        return True, target
    except Exception as exc:
        try:
            if os.path.exists(temp):
                os.remove(temp)
        except OSError:
            pass
        return False, str(exc)


class UpdateChecker(QThread):
    result = pyqtSignal(object)

    def run(self):
        self.result.emit(check())


class UpdateDownloader(QThread):
    done = pyqtSignal(bool, str)

    def __init__(self, url, parent=None):
        super().__init__(parent)
        self.url = url

    def run(self):
        ok, message = download_and_install(self.url)
        self.done.emit(ok, message)
