#!/usr/bin/env python3
"""Authentication helpers for the remotely exposed GStudio workbench."""
from __future__ import annotations
from ..deployment import runtime_root as _deployment_root

import base64
import hashlib
import hmac
import os
import secrets


PBKDF2_ROUNDS = 310_000


def password_record(password: str, *, salt: bytes | None = None) -> str:
    if not password:
        raise ValueError("password must not be empty")
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, record: str) -> bool:
    try:
        scheme, rounds, salt, expected = record.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt), int(rounds)
        ).hex()
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def basic_credentials(header: str) -> tuple[str, str] | None:
    if not header.startswith("Basic "):
        return None
    try:
        decoded = base64.b64decode(header[6:], validate=True).decode("utf-8")
        username, password = decoded.split(":", 1)
    except (ValueError, UnicodeDecodeError):
        return None
    return username, password


def valid_ui_authorization(header: str) -> bool:
    credentials = basic_credentials(header)
    username = os.environ.get("GSTUDIO_CENTRAL_USERNAME", "")
    record = os.environ.get("GSTUDIO_CENTRAL_PASSWORD_HASH", "")
    return bool(
        credentials
        and username
        and record
        and hmac.compare_digest(credentials[0], username)
        and verify_password(credentials[1], record)
    )


def valid_bridge_authorization(header: str) -> bool:
    configured = os.environ.get("GSTUDIO_BRIDGE_TOKEN", "")
    supplied = header[7:] if header.startswith("Bearer ") else ""
    return bool(configured and supplied and hmac.compare_digest(configured, supplied))


if __name__ == "__main__":
    import getpass

    first = getpass.getpass("GStudio central password: ")
    second = getpass.getpass("Confirm password: ")
    if first != second:
        raise SystemExit("passwords do not match")
    print(password_record(first))
