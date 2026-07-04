import multiprocessing
import os
import shutil
import subprocess
import sys
import tempfile

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
             "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_var, "1")

_mutex_handle = []


def acquire_single_instance():
    if sys.platform != "win32":
        return True
    import ctypes
    handle = ctypes.windll.kernel32.CreateMutexW(None, False, "Global\\ServiceComDiag_SingleInstance")
    if not handle or ctypes.windll.kernel32.GetLastError() == 183:
        return False
    _mutex_handle.append(handle)
    return True


def splash_text(text):
    try:
        import pyi_splash
        pyi_splash.update_text(text)
    except Exception:
        pass


def close_splash():
    try:
        import pyi_splash
        pyi_splash.close()
    except Exception:
        pass


def relaunch_from_temp():
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    if os.environ.get("SERVICECOM_RELAUNCHED") == "1":
        return
    import ctypes
    exe = os.path.abspath(sys.executable)
    drive = os.path.splitdrive(exe)[0] + "\\"
    if ctypes.windll.kernel32.GetDriveTypeW(drive) != 2:
        return
    target_dir = os.path.join(tempfile.gettempdir(), "ServiceCom")
    os.makedirs(target_dir, exist_ok=True)
    target = os.path.join(target_dir, os.path.basename(exe))
    try:
        if not (os.path.exists(target) and os.path.getsize(target) == os.path.getsize(exe)):
            shutil.copy2(exe, target)
    except OSError:
        return
    env = dict(os.environ)
    env["SERVICECOM_RELAUNCHED"] = "1"
    env["SERVICECOM_ORIGIN"] = os.path.dirname(exe)
    subprocess.Popen([target], env=env, close_fds=True, cwd=target_dir, creationflags=0x00000008)
    sys.exit(0)


def main():
    import traceback
    from PyQt6.QtWidgets import QApplication, QMessageBox
    from app import config
    from app.main_window import MainWindow
    from app.theme import stylesheet
    try:
        os.chdir(tempfile.gettempdir())
    except OSError:
        pass

    def handle_exception(exc_type, exc_value, exc_tb):
        message = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        try:
            log_path = os.path.join(tempfile.gettempdir(), "servicecom_error.log")
            with open(log_path, "a", encoding="utf-8") as handle:
                handle.write(message + "\n")
        except OSError:
            log_path = "недоступен"
        try:
            QMessageBox.critical(None, "Сервис • Com — ошибка",
                                 "Произошла ошибка в одном из тестов, но программа продолжит работу.\n"
                                 f"Журнал: {log_path}")
        except Exception:
            pass

    sys.excepthook = handle_exception
    if not acquire_single_instance():
        close_splash()
        sys.exit(0)
    splash_text("Запуск интерфейса...")
    app = QApplication(sys.argv)
    app.setApplicationName("SCAA — Service Com Auto Analyze")
    theme_name = config.load().get("theme", "dark")
    if theme_name not in ("dark", "light"):
        theme_name = "dark"
    app.setStyleSheet(stylesheet(theme_name))
    splash_text("Загрузка тестов...")
    window = MainWindow(theme_name)
    app.installEventFilter(window)
    window.show()
    close_splash()
    sys.exit(app.exec())


if __name__ == "__main__":
    multiprocessing.freeze_support()
    relaunch_from_temp()
    main()
