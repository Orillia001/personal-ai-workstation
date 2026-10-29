"""Protect small local secrets with Windows DPAPI under the current user."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _transform(data: bytes, *, decrypt: bool) -> bytes:
    if os.name != "nt":
        raise RuntimeError("登录链接加密仅支持当前 Windows 工作站")
    if not data:
        raise ValueError("登录链接不能为空")

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    input_bytes = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    input_blob = _DataBlob(len(data), input_bytes)
    output_blob = _DataBlob()
    blob_ptr = ctypes.POINTER(_DataBlob)
    if decrypt:
        operation = crypt32.CryptUnprotectData
        operation.argtypes = [blob_ptr, ctypes.POINTER(ctypes.c_wchar_p), blob_ptr,
                              ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, blob_ptr]
        args = (ctypes.byref(input_blob), None, None, None, None, 1, ctypes.byref(output_blob))
    else:
        operation = crypt32.CryptProtectData
        operation.argtypes = [blob_ptr, ctypes.c_wchar_p, blob_ptr,
                              ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, blob_ptr]
        args = (ctypes.byref(input_blob), "Personal AI Workstation site login", None,
                None, None, 1, ctypes.byref(output_blob))
    operation.restype = wintypes.BOOL
    if not operation(*args):
        raise OSError(ctypes.get_last_error(), "Windows DPAPI 处理登录链接失败")
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        kernel32.LocalFree(ctypes.cast(output_blob.pbData, ctypes.c_void_p))


def protect_text(value: str) -> bytes:
    return _transform(value.encode("utf-8"), decrypt=False)


def unprotect_text(value: bytes) -> str:
    return _transform(value, decrypt=True).decode("utf-8")
