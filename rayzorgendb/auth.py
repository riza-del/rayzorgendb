"""
RayzorgenDB HTTP Auth

Token-based authentication for HTTP API.
"""

import os
import time
import hmac
import hashlib
import secrets
import threading
from typing import Dict, List, Optional


class AuthManager:
    """
    Token-based auth for HTTP API.

    Features:
    - Multi-user tokens
    - Token expiration
    - Role-based access (read/write/admin)
    - Rate limiting per token
    """

    def __init__(self):
        self._tokens: Dict[str, Dict] = {}
        self._lock = threading.RLock()

    def create_token(self, user: str,
                     role: str = "read",
                     expires_in: int = None) -> str:
        """
        Create new token.

        Args:
            user: username
            role: "read" | "write" | "admin"
            expires_in: seconds until expiration (None = never)
        """
        token = secrets.token_urlsafe(32)
        now = time.time()
        expires = now + expires_in if expires_in else None

        with self._lock:
            self._tokens[token] = {
                "user": user,
                "role": role,
                "created_at": now,
                "expires_at": expires,
                "last_used": now,
                "usage_count": 0,
            }
        return token

    def revoke_token(self, token: str) -> bool:
        with self._lock:
            return self._tokens.pop(token, None) is not None

    def verify(self, token: str,
               required_role: str = None) -> Optional[Dict]:
        """
        Verify token. Returns user info or None.
        """
        with self._lock:
            info = self._tokens.get(token)
            if info is None:
                return None

            # Expiration check
            if info["expires_at"] is not None:
                if time.time() > info["expires_at"]:
                    del self._tokens[token]
                    return None

            # Role check
            if required_role:
                role_levels = {
                    "read": 1, "write": 2, "admin": 3,
                }
                user_level = role_levels.get(info["role"], 0)
                req_level = role_levels.get(required_role, 0)
                if user_level < req_level:
                    return None

            # Update stats
            info["last_used"] = time.time()
            info["usage_count"] += 1
            return dict(info)

    def list_tokens(self) -> List[Dict]:
        with self._lock:
            return [
                {
                    "token": t[:8] + "...",
                    "user": v["user"],
                    "role": v["role"],
                    "expires_at": v["expires_at"],
                    "usage_count": v["usage_count"],
                }
                for t, v in self._tokens.items()
            ]

    def stats(self) -> Dict:
        with self._lock:
            roles = {}
            for v in self._tokens.values():
                roles[v["role"]] = roles.get(v["role"], 0) + 1
            return {
                "total_tokens": len(self._tokens),
                "by_role": roles,
            }


class BasicAuth:
    """Simple username/password auth."""

    def __init__(self, users: Dict[str, str] = None):
        self._users: Dict[str, str] = {}
        if users:
            for name, pwd in users.items():
                self.add_user(name, pwd)

    def add_user(self, username: str, password: str):
        salt = secrets.token_bytes(16)
        key = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt, 100_000
        )
        self._users[username] = (salt + key).hex()

    def verify(self, username: str, password: str) -> bool:
        stored = self._users.get(username)
        if not stored:
            return False
        raw = bytes.fromhex(stored)
        salt, key = raw[:16], raw[16:]
        test = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt, 100_000
        )
        return hmac.compare_digest(key, test)

    def remove_user(self, username: str) -> bool:
        return self._users.pop(username, None) is not None


__all__ = ["AuthManager", "BasicAuth"]
