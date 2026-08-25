from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from pathlib import Path

from .config import default_config_dir


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob_from_bytes(value: bytes) -> tuple[_DataBlob, object]:
    buffer = ctypes.create_string_buffer(value)
    blob = _DataBlob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    return blob, buffer


class DpapiTokenStore:
    """Encrypts the Connector bearer token for the current Windows user."""

    def __init__(self, directory: Path | None = None):
        self.directory = directory or default_config_dir()
        self.path = self.directory / "connector-token.dpapi"

    def save(self, token: str) -> None:
        if os.name != "nt":
            raise RuntimeError("DPAPI token storage is available only on Windows")
        raw_blob, raw_buffer = _blob_from_bytes(token.encode("utf-8"))
        encrypted_blob = _DataBlob()
        crypt32 = ctypes.windll.crypt32
        if not crypt32.CryptProtectData(
            ctypes.byref(raw_blob),
            "RokidHub Desktop Connector",
            None,
            None,
            None,
            0x1,
            ctypes.byref(encrypted_blob),
        ):
            raise ctypes.WinError()
        try:
            encrypted = ctypes.string_at(encrypted_blob.pbData, encrypted_blob.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(encrypted_blob.pbData)
            del raw_buffer
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_bytes(encrypted)
        temporary.replace(self.path)

    def load(self) -> str:
        if os.name != "nt":
            raise RuntimeError("DPAPI token storage is available only on Windows")
        if not self.path.exists():
            raise RuntimeError("Connector ещё не привязан. Запусти команду pair")
        encrypted_blob, encrypted_buffer = _blob_from_bytes(self.path.read_bytes())
        raw_blob = _DataBlob()
        crypt32 = ctypes.windll.crypt32
        if not crypt32.CryptUnprotectData(
            ctypes.byref(encrypted_blob),
            None,
            None,
            None,
            None,
            0x1,
            ctypes.byref(raw_blob),
        ):
            raise ctypes.WinError()
        try:
            raw = ctypes.string_at(raw_blob.pbData, raw_blob.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(raw_blob.pbData)
            del encrypted_buffer
        return raw.decode("utf-8")
