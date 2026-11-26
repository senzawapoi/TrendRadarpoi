"""Expose bounded SQLite result codes without exception text or database details."""

from __future__ import annotations

import sqlite3

_PRIMARY_NAMES = {
    5: "SQLITE_BUSY",
    6: "SQLITE_LOCKED",
    8: "SQLITE_READONLY",
    10: "SQLITE_IOERR",
    11: "SQLITE_CORRUPT",
    13: "SQLITE_FULL",
}


def error_fields(exc: BaseException) -> dict[str, int | str | None]:
    """Read only SQLite's integer code; Python 3.10 may not supply this attribute."""
    code = getattr(exc, "sqlite_errorcode", None) if isinstance(exc, sqlite3.Error) else None
    if type(code) is not int or not 0 <= code < 2**31:
        return {"sqlite_code": None, "sqlite_primary": "UNKNOWN"}
    return {"sqlite_code": code, "sqlite_primary": _PRIMARY_NAMES.get(code & 255, "SQLITE_OTHER")}
