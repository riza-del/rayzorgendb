"""
RayzorgenDB Shell Authentication
Simple password-based login for the shell.
"""

import os
import json
import hmac
import hashlib
import time


CONFIG_DIR = os.path.expanduser("~/.rayzorgen")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")


def _ensure_dir():
    os.makedirs(CONFIG_DIR, exist_ok=True)


def _load() -> dict:
    if not os.path.exists(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except (IOError, json.JSONDecodeError):
        return {}


def _save(data: dict):
    _ensure_dir()
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)
    try:
        os.chmod(CONFIG_FILE, 0o600)
    except Exception:
        pass


def is_first_time() -> bool:
    """True if no account has been created yet."""
    return not _load().get("password_hash")


def _hash_password(password: str) -> str:
    salt = os.urandom(16)
    key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        100_000,
    )
    return (salt + key).hex()


def _verify_password(password: str, stored: str) -> bool:
    try:
        raw = bytes.fromhex(stored)
    except ValueError:
        return False
    if len(raw) < 16:
        return False
    salt, key = raw[:16], raw[16:]
    test = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        100_000,
    )
    return hmac.compare_digest(key, test)


def create_account(password: str) -> bool:
    """Create account (first time)."""
    if len(password) < 4:
        return False
    _save({
        "password_hash": _hash_password(password),
        "created_at": time.time(),
    })
    return True


def login(password: str) -> bool:
    """Verify password."""
    data = _load()
    stored = data.get("password_hash", "")
    if not stored:
        return False
    return _verify_password(password, stored)


def change_password(old: str, new: str) -> bool:
    if not login(old):
        return False
    if len(new) < 4:
        return False
    return create_account(new)


def reset():
    """Delete account."""
    if os.path.exists(CONFIG_FILE):
        try:
            os.remove(CONFIG_FILE)
            return True
        except OSError:
            return False
    return True


__all__ = [
    "is_first_time", "create_account", "login",
    "change_password", "reset",
]
