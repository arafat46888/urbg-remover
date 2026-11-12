"""Administrator authentication helpers."""

from __future__ import annotations

import secrets

from ..config import get_settings
from ..database import get_db, utcnow
from ..security import hash_password, verify_password


def sync_admin_password() -> None:
    """Make sure the stored admin hash matches the environment configuration."""
    settings = get_settings()
    if settings.admin_password_hash:
        stored_hash = settings.admin_password_hash
    elif settings.admin_password:
        stored_hash = hash_password(settings.admin_password)
    else:
        raise RuntimeError(
            "ADMIN_PASSWORD (or ADMIN_PASSWORD_HASH) must be set to run UrBG Remover."
        )

    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            "SELECT password_hash FROM admin_users WHERE username = ?",
            (settings.admin_username,),
        )
        row = cur.fetchone()

    if row is None or row["password_hash"] != stored_hash:
        with db.transaction() as cur:
            cur.execute(
                "INSERT INTO admin_users (username, password_hash, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(username) DO UPDATE SET password_hash = excluded.password_hash, "
                "updated_at = excluded.updated_at",
                (settings.admin_username, stored_hash, utcnow()),
            )


def verify_admin_password(password: str) -> bool:
    """Verify the submitted password against the stored PBKDF2 hash."""
    if not password:
        return False
    settings = get_settings()
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            "SELECT password_hash FROM admin_users WHERE username = ?",
            (settings.admin_username,),
        )
        row = cur.fetchone()

    if row is not None:
        return verify_password(password, row["password_hash"])

    # Fallback: compare directly against the environment variable.
    if settings.admin_password:
        return secrets.compare_digest(password, settings.admin_password)
    return False
