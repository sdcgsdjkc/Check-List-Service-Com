from app.tests.ports import PortsPage
from app.tests.drivers import DriversPage
from app.tests.keyboard import KeyboardPage
from app.tests.touchpad import TouchpadPage
from app.tests.storage import StoragePage
from app.tests.memory import MemoryPage
from app.tests.stress import StressPage
from app.tests.userdata import UserDataPage
from app.tests.avtest import AvPage
from app.tests.network import NetworkPage
from app.tests.display import DisplayPage

PAGE_CLASSES = [
    PortsPage,
    DriversPage,
    KeyboardPage,
    TouchpadPage,
    StoragePage,
    MemoryPage,
    StressPage,
    UserDataPage,
    AvPage,
    NetworkPage,
    DisplayPage,
]
