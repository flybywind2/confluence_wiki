from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass

from sqlalchemy import select

from app.core.config import Settings
from app.db.models import User

ROLE_RANK = {"viewer": 1, "editor": 2, "admin": 3}


@dataclass(frozen=True)
class BootstrapUser:
    username: str
    password: str
    role: str


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    iterations = 120_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations_value, salt_hex, digest_hex = password_hash.split("$", 3)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt_hex),
        int(iterations_value),
    )
    return hmac.compare_digest(digest.hex(), digest_hex)


def role_allows(user_role: str, required_role: str) -> bool:
    return ROLE_RANK.get(str(user_role or "").strip(), 0) >= ROLE_RANK.get(str(required_role or "").strip(), 0)


def authenticate_user(session, username: str, password: str) -> User | None:
    normalized_username = str(username or "").strip()
    if not normalized_username or not password:
        return None
    user = session.scalar(select(User).where(User.username == normalized_username))
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def ensure_bootstrap_users(session, settings: Settings) -> None:
    users = [
        BootstrapUser(settings.auth_bootstrap_admin_username, settings.auth_bootstrap_admin_password, "admin"),
        BootstrapUser(settings.auth_bootstrap_editor_username, settings.auth_bootstrap_editor_password, "editor"),
        BootstrapUser(settings.auth_bootstrap_viewer_username, settings.auth_bootstrap_viewer_password, "viewer"),
    ]
    for candidate in users:
        if not candidate.username or not candidate.password:
            continue
        user = session.scalar(select(User).where(User.username == candidate.username))
        if user is None:
            session.add(
                User(
                    username=candidate.username,
                    password_hash=hash_password(candidate.password),
                    role=candidate.role,
                    is_active=True,
                )
            )


def create_user(session, *, username: str, password: str, role: str) -> User:
    normalized_username = str(username or "").strip()
    normalized_role = str(role or "").strip().lower()
    if not normalized_username or not password:
        raise ValueError("username and password are required")
    if normalized_role not in ROLE_RANK:
        raise ValueError("invalid role")
    existing = session.scalar(select(User).where(User.username == normalized_username))
    if existing is not None:
        raise ValueError("username already exists")
    user = User(
        username=normalized_username,
        password_hash=hash_password(password),
        role=normalized_role,
        is_active=True,
    )
    session.add(user)
    return user
