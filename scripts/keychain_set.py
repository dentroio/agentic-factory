#!/usr/bin/env python3
"""Set a macOS Keychain generic password. The secret is read from stdin (AF-10).

Never pass the secret on argv — ``security add-generic-password -w`` is visible
to any local ``ps``.
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import c_char_p, c_uint32, c_void_p, POINTER, byref

ERR_SEC_SUCCESS = 0
ERR_SEC_ITEM_NOT_FOUND = -25300


def _security():
    return ctypes.cdll.LoadLibrary(
        "/System/Library/Frameworks/Security.framework/Security"
    )


def set_generic_password(service: str, account: str, secret: bytes) -> None:
    if sys.platform != "darwin":
        raise RuntimeError("macOS Keychain only")
    sec = _security()
    sec.SecKeychainFindGenericPassword.argtypes = [
        c_void_p, c_uint32, c_char_p, c_uint32, c_char_p,
        POINTER(c_uint32), POINTER(c_void_p), POINTER(c_void_p),
    ]
    sec.SecKeychainFindGenericPassword.restype = ctypes.c_int32
    sec.SecKeychainItemDelete.argtypes = [c_void_p]
    sec.SecKeychainItemDelete.restype = ctypes.c_int32
    sec.SecKeychainItemFreeContent.argtypes = [c_void_p, c_void_p]
    sec.SecKeychainItemFreeContent.restype = ctypes.c_int32
    sec.SecKeychainAddGenericPassword.argtypes = [
        c_void_p, c_uint32, c_char_p, c_uint32, c_char_p,
        c_uint32, c_char_p, POINTER(c_void_p),
    ]
    sec.SecKeychainAddGenericPassword.restype = ctypes.c_int32

    service_b = service.encode("utf-8")
    account_b = account.encode("utf-8")
    item = c_void_p()
    pw_len = c_uint32()
    pw_data = c_void_p()
    found = sec.SecKeychainFindGenericPassword(
        None,
        len(service_b), service_b,
        len(account_b), account_b,
        byref(pw_len), byref(pw_data), byref(item),
    )
    if found == ERR_SEC_SUCCESS:
        if pw_data.value:
            sec.SecKeychainItemFreeContent(None, pw_data)
        deleted = sec.SecKeychainItemDelete(item)
        if deleted != ERR_SEC_SUCCESS:
            raise RuntimeError(f"SecKeychainItemDelete failed: {deleted}")
    elif found != ERR_SEC_ITEM_NOT_FOUND:
        raise RuntimeError(f"SecKeychainFindGenericPassword failed: {found}")

    added = sec.SecKeychainAddGenericPassword(
        None,
        len(service_b), service_b,
        len(account_b), account_b,
        len(secret), secret,
        None,
    )
    if added != ERR_SEC_SUCCESS:
        raise RuntimeError(f"SecKeychainAddGenericPassword failed: {added}")


def delete_generic_password(service: str, account: str) -> None:
    """Delete a generic password. No-op if the item is missing."""
    if sys.platform != "darwin":
        raise RuntimeError("macOS Keychain only")
    sec = _security()
    sec.SecKeychainFindGenericPassword.argtypes = [
        c_void_p, c_uint32, c_char_p, c_uint32, c_char_p,
        POINTER(c_uint32), POINTER(c_void_p), POINTER(c_void_p),
    ]
    sec.SecKeychainFindGenericPassword.restype = ctypes.c_int32
    sec.SecKeychainItemDelete.argtypes = [c_void_p]
    sec.SecKeychainItemDelete.restype = ctypes.c_int32
    sec.SecKeychainItemFreeContent.argtypes = [c_void_p, c_void_p]
    sec.SecKeychainItemFreeContent.restype = ctypes.c_int32

    service_b = service.encode("utf-8")
    account_b = account.encode("utf-8")
    item = c_void_p()
    pw_len = c_uint32()
    pw_data = c_void_p()
    found = sec.SecKeychainFindGenericPassword(
        None,
        len(service_b), service_b,
        len(account_b), account_b,
        byref(pw_len), byref(pw_data), byref(item),
    )
    if found == ERR_SEC_ITEM_NOT_FOUND:
        return
    if found != ERR_SEC_SUCCESS:
        raise RuntimeError(f"SecKeychainFindGenericPassword failed: {found}")
    if pw_data.value:
        sec.SecKeychainItemFreeContent(None, pw_data)
    deleted = sec.SecKeychainItemDelete(item)
    if deleted != ERR_SEC_SUCCESS:
        raise RuntimeError(f"SecKeychainItemDelete failed: {deleted}")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args[:1] == ["--delete"] and len(args) == 3:
        delete_generic_password(args[1], args[2])
        return 0
    if len(args) != 2:
        print(
            "usage: keychain_set.py <service> <account>           # secret on stdin\n"
            "       keychain_set.py --delete <service> <account>",
            file=sys.stderr,
        )
        return 2
    service, account = args
    secret = sys.stdin.buffer.read()
    if secret.endswith(b"\n"):
        secret = secret[:-1]
    if not secret:
        print("keychain_set.py: empty secret on stdin", file=sys.stderr)
        return 1
    set_generic_password(service, account, secret)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
