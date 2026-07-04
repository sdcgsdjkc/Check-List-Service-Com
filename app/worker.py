import math


def cpu_burn(stop_event):
    x = 0.0001
    while not stop_event.is_set():
        for _ in range(50000):
            x = math.sin(x) + math.sqrt(x * x + 1.0)
        x = 0.0001
