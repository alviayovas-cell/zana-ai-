import os
import winreg

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from tests.fakes import wait_until
from zana import startup
from zana.single_instance import SingleInstance

TEST_KEY = r"Software\ZanaTest\Run"


@pytest.fixture(autouse=True)
def clean_key():
    yield
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, TEST_KEY)
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r"Software\ZanaTest")
    except OSError:
        pass


def test_command_is_absolute_quoted_and_background():
    cmd = startup.launch_command()
    assert cmd.startswith('"') and cmd.endswith(startup.BACKGROUND_FLAG)
    assert "main.py" in cmd and ":\\" in cmd


def test_enable_disable_roundtrip():
    assert not startup.is_enabled(TEST_KEY)
    startup.enable(TEST_KEY)
    assert startup.is_enabled(TEST_KEY)
    assert startup.current_command(TEST_KEY) == startup.launch_command()
    startup.disable(TEST_KEY)
    assert not startup.is_enabled(TEST_KEY)
    startup.disable(TEST_KEY)  # already off is fine


def test_sync_repairs_stale_path_and_respects_disabled():
    startup.enable(TEST_KEY, command='"C:\\old\\Zana.exe" --background')
    startup.sync(True, TEST_KEY)
    assert startup.current_command(TEST_KEY) == startup.launch_command()
    startup.disable(TEST_KEY)
    startup.sync(False, TEST_KEY)
    assert not startup.is_enabled(TEST_KEY)


def test_writes_only_current_user_hive():
    # HKCU never needs administrator rights; make sure we never touch HKLM.
    import inspect
    src = inspect.getsource(startup)
    assert "HKEY_LOCAL_MACHINE" not in src


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_second_instance_is_refused_and_wakes_first(app):
    name = f"ZanaTest-{os.getpid()}"
    first, second = SingleInstance(name), SingleInstance(name)
    woke = []
    first.activated.connect(lambda: woke.append(1))
    try:
        assert first.acquire() is True
        assert second.acquire() is False
        assert wait_until(lambda: woke == [1], app=app)
    finally:
        first.release()


def test_instance_can_be_reacquired_after_release(app):
    name = f"ZanaTest2-{os.getpid()}"
    a = SingleInstance(name)
    assert a.acquire()
    a.release()
    b = SingleInstance(name)
    assert b.acquire()
    b.release()
