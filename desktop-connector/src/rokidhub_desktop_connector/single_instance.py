from __future__ import annotations

import ctypes
import os


ERROR_ALREADY_EXISTS = 183
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258


class SingleInstance:
    """Own a per-session Windows mutex for the lifetime of the GUI process."""

    def __init__(self, name: str):
        self.name = name
        self._handle: int | None = None
        self._show_event_handle: int | None = None

    def acquire(self) -> bool:
        if os.name != "nt":
            return True
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CreateEventW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_bool, ctypes.c_wchar_p]
        kernel32.CreateEventW.restype = ctypes.c_void_p
        kernel32.SetEvent.argtypes = [ctypes.c_void_p]
        kernel32.SetEvent.restype = ctypes.c_bool
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_bool
        handle = kernel32.CreateMutexW(None, False, self.name)
        if not handle:
            raise ctypes.WinError()
        already_exists = kernel32.GetLastError() == ERROR_ALREADY_EXISTS
        show_event_handle = kernel32.CreateEventW(None, False, False, f"{self.name}.Show")
        if not show_event_handle:
            kernel32.CloseHandle(handle)
            raise ctypes.WinError()
        if already_exists:
            kernel32.SetEvent(show_event_handle)
            kernel32.CloseHandle(show_event_handle)
            kernel32.CloseHandle(handle)
            return False
        self._handle = int(handle)
        self._show_event_handle = int(show_event_handle)
        return True

    def consume_show_request(self) -> bool:
        """Return true once when another GUI launch asks this instance to open."""

        if self._show_event_handle is None or os.name != "nt":
            return False
        kernel32 = ctypes.windll.kernel32
        kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel32.WaitForSingleObject.restype = ctypes.c_uint32
        result = kernel32.WaitForSingleObject(ctypes.c_void_p(self._show_event_handle), 0)
        if result == WAIT_OBJECT_0:
            return True
        if result == WAIT_TIMEOUT:
            return False
        raise ctypes.WinError()

    def close(self) -> None:
        if os.name != "nt":
            return
        kernel32 = ctypes.windll.kernel32
        if self._show_event_handle is not None:
            kernel32.CloseHandle(ctypes.c_void_p(self._show_event_handle))
            self._show_event_handle = None
        if self._handle is not None:
            kernel32.CloseHandle(ctypes.c_void_p(self._handle))
            self._handle = None
