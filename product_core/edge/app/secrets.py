# -*- coding: utf-8 -*-
"""Kho bí mật cục bộ dùng Windows DPAPI, không lưu mật khẩu dạng rõ."""
import base64
import ctypes
import json
import os
from ctypes import wintypes


class SecretStoreError(RuntimeError):
    pass


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(data):
    raw = bytes(data)
    buffer = ctypes.create_string_buffer(raw)
    return _DataBlob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def _protect(value):
    if os.name != "nt":
        raise SecretStoreError("Kho mật khẩu an toàn chỉ hỗ trợ Windows DPAPI.")
    source, keep = _blob(str(value).encode("utf-8"))
    output = _DataBlob()
    # Tham số thứ 2 là szDataDescr (mô tả), KHÔNG phải pOptionalEntropy — đổi
    # chuỗi này không ảnh hưởng khả năng giải mã các blob đã lưu từ trước.
    if not ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(source), "MSB Radar Edge", None, None, None, 0,
            ctypes.byref(output)):
        raise SecretStoreError("Windows không mã hóa được mật khẩu.")
    try:
        return base64.b64encode(ctypes.string_at(output.pbData, output.cbData)).decode("ascii")
    finally:
        ctypes.windll.kernel32.LocalFree(output.pbData)
        del keep


def _unprotect(value):
    if os.name != "nt":
        return ""
    try:
        encrypted = base64.b64decode(value)
        source, keep = _blob(encrypted)
        output = _DataBlob()
        if not ctypes.windll.crypt32.CryptUnprotectData(
                ctypes.byref(source), None, None, None, None, 0,
                ctypes.byref(output)):
            return ""
        try:
            return ctypes.string_at(output.pbData, output.cbData).decode("utf-8")
        finally:
            ctypes.windll.kernel32.LocalFree(output.pbData)
            del keep
    except Exception:
        return ""


class SecretStore:
    def __init__(self, path):
        self.path = path

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, data):
        folder = os.path.dirname(self.path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        temporary = self.path + ".tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=True, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.path)

    def get(self, key):
        return _unprotect(self._load().get(str(key), ""))

    def has(self, key):
        return bool(self.get(key))

    def set(self, key, value):
        data = self._load()
        if value:
            data[str(key)] = _protect(value)
        else:
            data.pop(str(key), None)
        self._save(data)
