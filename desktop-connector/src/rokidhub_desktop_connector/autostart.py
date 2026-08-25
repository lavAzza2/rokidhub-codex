from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "RokidHubDesktopConnector"


def build_autostart_command(config_dir: Path) -> str:
    """Build a per-user, background GUI command without embedding any secret."""
    executable = Path(sys.executable)
    if not getattr(sys, "frozen", False):
        pythonw = executable.with_name("pythonw.exe")
        if os.name == "nt" and pythonw.is_file():
            executable = pythonw
        arguments = [
            str(executable),
            "-m",
            "rokidhub_desktop_connector",
            "--config-dir",
            str(config_dir),
            "gui",
            "--minimized",
            "--auto-start",
        ]
    else:
        arguments = [
            str(executable),
            "--config-dir",
            str(config_dir),
            "gui",
            "--minimized",
            "--auto-start",
        ]
    return subprocess.list2cmdline(arguments)


def is_autostart_enabled() -> bool:
    if os.name != "nt":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return bool(str(value).strip())
    except FileNotFoundError:
        return False


def set_autostart(enabled: bool, config_dir: Path) -> None:
    """Change only this connector's HKCU Run value, on an explicit UI action."""
    if os.name != "nt":
        raise RuntimeError("Автозагрузка поддерживается только в Windows")
    import winreg

    if enabled:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, build_autostart_command(config_dir))
        return
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, VALUE_NAME)
    except FileNotFoundError:
        return
