import os
import sys


def _restore_redirected_output_for_child() -> None:
    """Bind QProcess' inherited pipe in a PyInstaller windowed child."""
    if len(sys.argv) <= 1 or sys.stdout is not None or os.name != "nt":
        return
    import ctypes
    import msvcrt

    handle = ctypes.windll.kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
    if handle in (0, -1):
        return
    descriptor = msvcrt.open_osfhandle(handle, os.O_WRONLY | os.O_TEXT)
    stream = os.fdopen(descriptor, "w", encoding="utf-8", errors="replace", buffering=1, closefd=False)
    sys.stdout = stream
    sys.stderr = stream


_restore_redirected_output_for_child()

from rokidhub_desktop_connector.cli import main as cli_main
from rokidhub_desktop_connector.gui import script_main as gui_main


raise SystemExit(cli_main() if len(sys.argv) > 1 else gui_main())
