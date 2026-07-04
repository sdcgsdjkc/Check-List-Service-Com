GRADE_COLORS = {"ok": "pass", "warn": "skip", "bad": "fail", "": "notrun"}
GRADE_LABELS = {"ok": "норма", "warn": "внимание", "bad": "критично", "": ""}


def battery_grade(wear_percent):
    if wear_percent < 20:
        return "ok"
    if wear_percent < 40:
        return "warn"
    return "bad"


def temperature_grade(celsius):
    if celsius < 85:
        return "ok"
    if celsius < 95:
        return "warn"
    return "bad"


def read_speed_grade(mb_per_sec):
    if mb_per_sec >= 250:
        return "ok"
    if mb_per_sec >= 90:
        return "warn"
    return "bad"


def smart_grade(healthy, reallocated=0, read_errors=0):
    if not healthy or reallocated > 0:
        return "bad"
    if read_errors > 0:
        return "warn"
    return "ok"


def power_on_hours_grade(hours):
    if hours < 15000:
        return "ok"
    if hours < 30000:
        return "warn"
    return "bad"
