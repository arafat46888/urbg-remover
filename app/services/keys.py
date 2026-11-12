"""API key management and usage accounting."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from ..database import get_db, utcnow
from ..security import generate_api_key, hash_api_key


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------
def create_key(name: str) -> dict[str, Any]:
    """Create an API key. The plaintext value is returned exactly once."""
    name = (name or "").strip() or "Untitled key"
    if len(name) > 80:
        name = name[:80]
    plain, key_hash, prefix, last4 = generate_api_key()
    now = utcnow()
    with get_db().transaction() as cur:
        cur.execute(
            "INSERT INTO api_keys (name, key_hash, key_prefix, key_last4, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (name, key_hash, prefix, last4, now),
        )
        key_id = int(cur.lastrowid)
    return {
        "id": key_id,
        "name": name,
        "key": plain,
        "prefix": prefix,
        "last4": last4,
        "created_at": now,
    }


def list_keys() -> list[dict[str, Any]]:
    with get_db().cursor() as cur:
        cur.execute(
            "SELECT id, name, key_prefix, key_last4, created_at, last_used_at, revoked, "
            "revoked_at, request_count, image_count, bytes_in, bytes_out "
            "FROM api_keys ORDER BY id DESC"
        )
        rows = [dict(row) for row in cur.fetchall()]
    for row in rows:
        row["revoked"] = bool(row["revoked"])
        row["active"] = not row["revoked"]
    return rows


def get_key(key_id: int) -> Optional[dict[str, Any]]:
    with get_db().cursor() as cur:
        cur.execute(
            "SELECT id, name, key_prefix, key_last4, created_at, last_used_at, revoked, "
            "revoked_at, request_count, image_count, bytes_in, bytes_out "
            "FROM api_keys WHERE id = ?",
            (key_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    data = dict(row)
    data["revoked"] = bool(data["revoked"])
    data["active"] = not data["revoked"]
    return data


def revoke_key(key_id: int) -> bool:
    with get_db().transaction() as cur:
        cur.execute(
            "UPDATE api_keys SET revoked = 1, revoked_at = ? WHERE id = ? AND revoked = 0",
            (utcnow(), key_id),
        )
        return cur.rowcount > 0


def restore_key(key_id: int) -> bool:
    with get_db().transaction() as cur:
        cur.execute(
            "UPDATE api_keys SET revoked = 0, revoked_at = NULL WHERE id = ?",
            (key_id,),
        )
        return cur.rowcount > 0


def delete_key(key_id: int) -> bool:
    with get_db().transaction() as cur:
        cur.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))
        return cur.rowcount > 0


def find_active_key(plaintext: str) -> Optional[dict[str, Any]]:
    """Look up an API key by its plaintext value (hash comparison)."""
    key_hash = hash_api_key(plaintext)
    with get_db().cursor() as cur:
        cur.execute(
            "SELECT id, name, key_prefix, key_last4, created_at, last_used_at, revoked, "
            "revoked_at, request_count, image_count, bytes_in, bytes_out "
            "FROM api_keys WHERE key_hash = ?",
            (key_hash,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    data = dict(row)
    data["revoked"] = bool(data["revoked"])
    return data


def touch_key(key_id: int, *, bytes_in: int = 0, bytes_out: int = 0, processed_image: bool = False) -> None:
    """Update last-used metadata and per-key counters."""
    db = get_db()
    with db.transaction() as cur:
        cur.execute(
            "UPDATE api_keys SET last_used_at = ?, request_count = request_count + 1, "
            "bytes_in = bytes_in + ?, bytes_out = bytes_out + ?, "
            "image_count = image_count + ? WHERE id = ?",
            (utcnow(), max(0, bytes_in), max(0, bytes_out), 1 if processed_image else 0, key_id),
        )


# ---------------------------------------------------------------------------
# Request log
# ---------------------------------------------------------------------------
def record_request(
    *,
    api_key_id: Optional[int],
    key_label: str,
    endpoint: str,
    method: str,
    status_code: int,
    success: bool,
    bytes_in: int = 0,
    bytes_out: int = 0,
    duration_ms: int = 0,
    source: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    db = get_db()
    with db.transaction() as cur:
        cur.execute(
            "INSERT INTO api_requests (api_key_id, key_label, endpoint, method, source, "
            "status_code, success, bytes_in, bytes_out, duration_ms, error, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                api_key_id,
                key_label,
                endpoint,
                method,
                source,
                int(status_code),
                1 if success else 0,
                int(bytes_in),
                int(bytes_out),
                int(duration_ms),
                error,
                utcnow(),
            ),
        )
    db.increment_counter("api_requests", 1)
    if success and (
        endpoint.startswith("/api/v1/remove") or endpoint.startswith("/admin/remove")
    ):
        db.increment_counter("images_processed", 1)


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------
def overview_stats() -> dict[str, Any]:
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN revoked = 0 THEN 1 ELSE 0 END) AS active, "
            "SUM(request_count) AS requests FROM api_keys"
        )
        key_row = cur.fetchone()
        cur.execute(
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS success, "
            "SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS failed, "
            "SUM(bytes_out) AS bytes_out, "
            "AVG(duration_ms) AS avg_ms FROM api_requests"
        )
        req_row = cur.fetchone()
        cur.execute(
            "SELECT COUNT(*) AS total FROM api_requests WHERE created_at >= ?",
            ((datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),),
        )
        day_row = cur.fetchone()

    images_processed = db.get_counter("images_processed")
    total_requests = db.get_counter("api_requests")
    return {
        "images_processed": images_processed,
        "total_requests": total_requests,
        "active_keys": int(key_row["active"] or 0),
        "total_keys": int(key_row["total"] or 0),
        "successful_requests": int(req_row["success"] or 0),
        "failed_requests": int(req_row["failed"] or 0),
        "bytes_out": int(req_row["bytes_out"] or 0),
        "avg_duration_ms": int(req_row["avg_ms"] or 0),
        "requests_last_24h": int(day_row["total"] or 0),
        "key_requests": int(key_row["requests"] or 0),
    }


def usage_timeseries(days: int = 30) -> list[dict[str, Any]]:
    days = max(1, min(365, int(days)))
    start = (datetime.now(timezone.utc) - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    with get_db().cursor() as cur:
        cur.execute(
            "SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS requests, "
            "SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS success, "
            "SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS failed, "
            "SUM(bytes_out) AS bytes_out, AVG(duration_ms) AS avg_ms "
            "FROM api_requests WHERE substr(created_at, 1, 10) >= ? "
            "GROUP BY day ORDER BY day ASC",
            (start,),
        )
        rows = [dict(row) for row in cur.fetchall()]

    by_day = {row["day"]: row for row in rows}
    series: list[dict[str, Any]] = []
    today = datetime.now(timezone.utc).date()
    for offset in range(days - 1, -1, -1):
        day = (today - timedelta(days=offset)).strftime("%Y-%m-%d")
        row = by_day.get(day)
        series.append(
            {
                "day": day,
                "requests": int(row["requests"]) if row else 0,
                "success": int(row["success"]) if row else 0,
                "failed": int(row["failed"]) if row else 0,
                "bytes_out": int(row["bytes_out"]) if row else 0,
                "avg_ms": int(row["avg_ms"]) if row else 0,
            }
        )
    return series


def endpoint_breakdown(limit: int = 10) -> list[dict[str, Any]]:
    with get_db().cursor() as cur:
        cur.execute(
            "SELECT endpoint, COUNT(*) AS requests, "
            "SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS success, "
            "SUM(bytes_out) AS bytes_out, AVG(duration_ms) AS avg_ms "
            "FROM api_requests GROUP BY endpoint ORDER BY requests DESC LIMIT ?",
            (max(1, min(100, int(limit))),),
        )
        return [dict(row) for row in cur.fetchall()]


def recent_requests(limit: int = 25) -> list[dict[str, Any]]:
    with get_db().cursor() as cur:
        cur.execute(
            "SELECT id, key_label, endpoint, method, source, status_code, success, "
            "bytes_out, duration_ms, error, created_at FROM api_requests "
            "ORDER BY id DESC LIMIT ?",
            (max(1, min(200, int(limit))),),
        )
        return [dict(row) for row in cur.fetchall()]
