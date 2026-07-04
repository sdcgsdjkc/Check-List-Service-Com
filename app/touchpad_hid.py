import ctypes
import sys
from ctypes import wintypes

from PyQt6.QtCore import QAbstractNativeEventFilter, QObject, pyqtSignal

WM_INPUT = 0x00FF
RID_INPUT = 0x10000003
RIDI_PREPARSEDDATA = 0x20000005
RIM_TYPEHID = 2
RIDEV_INPUTSINK = 0x00000100
RIDEV_REMOVE = 0x00000001
HIDP_INPUT = 0
HIDP_STATUS_SUCCESS = 0x00110000
UP_GENERIC = 0x01
USAGE_X = 0x30
USAGE_Y = 0x31
UP_DIGITIZER = 0x0D
USAGE_TOUCHPAD = 0x05

_available = sys.platform == "win32"
if _available:
    try:
        _user32 = ctypes.WinDLL("user32", use_last_error=True)
        _hid = ctypes.WinDLL("hid", use_last_error=True)
    except Exception:
        _available = False


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [("usUsagePage", wintypes.USHORT),
                ("usUsage", wintypes.USHORT),
                ("dwFlags", wintypes.DWORD),
                ("hwndTarget", wintypes.HWND)]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [("dwType", wintypes.DWORD),
                ("dwSize", wintypes.DWORD),
                ("hDevice", wintypes.HANDLE),
                ("wParam", wintypes.WPARAM)]


class MSG(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND),
                ("message", wintypes.UINT),
                ("wParam", wintypes.WPARAM),
                ("lParam", wintypes.LPARAM),
                ("time", wintypes.DWORD),
                ("pt_x", wintypes.LONG),
                ("pt_y", wintypes.LONG)]


if _available:
    _user32.RegisterRawInputDevices.argtypes = [ctypes.c_void_p, wintypes.UINT, wintypes.UINT]
    _user32.RegisterRawInputDevices.restype = wintypes.BOOL
    _user32.GetRawInputData.argtypes = [wintypes.HANDLE, wintypes.UINT, ctypes.c_void_p,
                                        ctypes.POINTER(wintypes.UINT), wintypes.UINT]
    _user32.GetRawInputData.restype = wintypes.UINT
    _user32.GetRawInputDeviceInfoW.argtypes = [wintypes.HANDLE, wintypes.UINT, ctypes.c_void_p,
                                               ctypes.POINTER(wintypes.UINT)]
    _user32.GetRawInputDeviceInfoW.restype = wintypes.UINT
    _hid.HidP_GetUsageValue.argtypes = [ctypes.c_int, wintypes.USHORT, wintypes.USHORT,
                                        wintypes.USHORT, ctypes.POINTER(wintypes.ULONG),
                                        ctypes.c_void_p, ctypes.c_char_p, wintypes.ULONG]
    _hid.HidP_GetUsageValue.restype = wintypes.LONG


class TouchpadTracker(QAbstractNativeEventFilter, QObject):
    contact = pyqtSignal(float, float)
    active = pyqtSignal()

    def __init__(self, parent=None):
        QObject.__init__(self, parent)
        QAbstractNativeEventFilter.__init__(self)
        self._hwnd = None
        self._preparsed = {}
        self._xmin = self._xmax = None
        self._ymin = self._ymax = None
        self._got = False

    def start(self, hwnd):
        if not _available:
            return False
        self._hwnd = wintypes.HWND(int(hwnd))
        device = RAWINPUTDEVICE(UP_DIGITIZER, USAGE_TOUCHPAD, RIDEV_INPUTSINK, self._hwnd)
        ok = _user32.RegisterRawInputDevices(ctypes.byref(device), 1, ctypes.sizeof(RAWINPUTDEVICE))
        return bool(ok)

    def stop(self):
        if not _available or self._hwnd is None:
            return
        device = RAWINPUTDEVICE(UP_DIGITIZER, USAGE_TOUCHPAD, RIDEV_REMOVE, None)
        try:
            _user32.RegisterRawInputDevices(ctypes.byref(device), 1, ctypes.sizeof(RAWINPUTDEVICE))
        except Exception:
            pass
        self._hwnd = None

    def _preparsed_for(self, hdevice):
        key = int(hdevice)
        if key in self._preparsed:
            return self._preparsed[key]
        size = wintypes.UINT(0)
        _user32.GetRawInputDeviceInfoW(hdevice, RIDI_PREPARSEDDATA, None, ctypes.byref(size))
        if size.value == 0:
            self._preparsed[key] = None
            return None
        buffer = (ctypes.c_byte * size.value)()
        _user32.GetRawInputDeviceInfoW(hdevice, RIDI_PREPARSEDDATA, buffer, ctypes.byref(size))
        self._preparsed[key] = buffer
        return buffer

    def _value(self, preparsed, usage, report, length):
        result = wintypes.ULONG(0)
        status = _hid.HidP_GetUsageValue(HIDP_INPUT, UP_GENERIC, 0, usage,
                                         ctypes.byref(result), preparsed, report, length)
        if status == HIDP_STATUS_SUCCESS:
            return result.value
        return None

    def _normalize(self, value, low, high):
        span = high - low
        if span <= 0:
            return 0.5
        return min(1.0, max(0.0, (value - low) / span))

    def _handle(self, lparam):
        size = wintypes.UINT(0)
        _user32.GetRawInputData(wintypes.HANDLE(lparam), RID_INPUT, None,
                                ctypes.byref(size), ctypes.sizeof(RAWINPUTHEADER))
        if size.value == 0:
            return
        buffer = (ctypes.c_byte * size.value)()
        if _user32.GetRawInputData(wintypes.HANDLE(lparam), RID_INPUT, buffer,
                                   ctypes.byref(size), ctypes.sizeof(RAWINPUTHEADER)) == 0xFFFFFFFF:
            return
        header = RAWINPUTHEADER.from_buffer(buffer)
        if header.dwType != RIM_TYPEHID:
            return
        preparsed = self._preparsed_for(header.hDevice)
        if preparsed is None:
            return
        base = ctypes.sizeof(RAWINPUTHEADER)
        raw = bytes(buffer)
        size_hid = int.from_bytes(raw[base:base + 4], "little")
        count = int.from_bytes(raw[base + 4:base + 8], "little")
        offset = base + 8
        for _ in range(count):
            report = raw[offset:offset + size_hid]
            offset += size_hid
            if not report:
                continue
            report_c = ctypes.c_char_p(report)
            x = self._value(preparsed, USAGE_X, report_c, size_hid)
            y = self._value(preparsed, USAGE_Y, report_c, size_hid)
            if x is None or y is None:
                continue
            self._xmin = x if self._xmin is None else min(self._xmin, x)
            self._xmax = x if self._xmax is None else max(self._xmax, x)
            self._ymin = y if self._ymin is None else min(self._ymin, y)
            self._ymax = y if self._ymax is None else max(self._ymax, y)
            if not self._got:
                self._got = True
                self.active.emit()
            xn = self._normalize(x, self._xmin, self._xmax)
            yn = self._normalize(y, self._ymin, self._ymax)
            self.contact.emit(xn, yn)

    def nativeEventFilter(self, event_type, message):
        try:
            if event_type == b"windows_generic_MSG":
                msg = MSG.from_address(int(message))
                if msg.message == WM_INPUT:
                    self._handle(msg.lParam)
        except Exception:
            pass
        return False, 0


def is_supported():
    return _available
