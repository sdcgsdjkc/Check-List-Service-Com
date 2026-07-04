import json
import os

FILENAME = "servicecom_settings.json"


def _candidate_dirs():
    dirs = []
    origin = os.environ.get("SERVICECOM_ORIGIN")
    if origin:
        dirs.append(origin)
    appdata = os.environ.get("APPDATA")
    if appdata:
        dirs.append(os.path.join(appdata, "ServiceCom"))
    dirs.append(os.path.join(os.path.expanduser("~"), ".servicecom"))
    return dirs


def load():
    for directory in _candidate_dirs():
        path = os.path.join(directory, FILENAME)
        try:
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as handle:
                    data = json.load(handle)
                if isinstance(data, dict):
                    return data
        except Exception:
            continue
    return {}


def save(data):
    for directory in _candidate_dirs():
        try:
            os.makedirs(directory, exist_ok=True)
            path = os.path.join(directory, FILENAME)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
            return path
        except Exception:
            continue
    return None
