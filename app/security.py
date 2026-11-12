"""Security primitives: password hashing, API key generation, rate limiting."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque, Dict, Optional

PBKDF2_ALGORITHM = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 260_000
SALT_BYTES = 16
API_KEY_PREFIX = "urbg"
API_KEY_BYTES = 32


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------
def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(raw: str) -> bytes:
    padding = "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(raw + padding)


def hash_password(password: str, *, salt: Optional[bytes] = None, iterations: int = PBKDF2_ITERATIONS) -> str:
    """Hash a password with PBKDF2-HMAC-SHA256.

    Format: ``pbkdf2_sha256$<iterations>$<salt_b64>$<hash_b64>``
    """
    if salt is None:
        salt = secrets.token_bytes(SALT_BYTES)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{PBKDF2_ALGORITHM}${iterations}${_b64encode(salt)}${_b64encode(dk)}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Constant-time verification of a password against a stored hash."""
    if not stored_hash:
        return False
    try:
        algorithm, iterations_raw, salt_b64, hash_b64 = stored_hash.split("$")
        if algorithm != PBKDF2_ALGORITHM:
            return False
        iterations = int(iterations_raw)
        salt = _b64decode(salt_b64)
        expected = _b64decode(hash_b64)
    except (ValueError, TypeError):
        return False

    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(candidate, expected)


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------
def generate_api_key() -> tuple[str, str, str, str]:
    """Create a new API key.

    Returns ``(plaintext_key, sha256_hash, display_prefix, last4)``.
    The plaintext is shown to the administrator exactly once; only the hash is
    ever persisted.
    """
    secret = secrets.token_urlsafe(API_KEY_BYTES)
    plain = f"{API_KEY_PREFIX}_{secret}"
    return plain, hash_api_key(plain), f"{API_KEY_PREFIX}_{secret[:6]}", secret[-4:]


def hash_api_key(plaintext: str) -> str:
    """SHA-256 hash of an API key (fast lookup hash for a high-entropy secret)."""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------
@dataclass
class RateLimitResult:
    allowed: bool
    remaining: int
    retry_after: int
    limit: int


class SlidingWindowLimiter:
    """In-memory sliding window limiter (per process)."""

    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = max(0, limit)
        self.window_seconds = max(1, window_seconds)
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> Deque[float]:
        bucket = self._hits[key]
        cutoff = now - self.window_seconds
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        return bucket

    def hit(self, key: str, count: int = 1) -> RateLimitResult:
        now = time.monotonic()
        with self._lock:
            bucket = self._prune(key, now)
            if self.limit <= 0:
                return RateLimitResult(True, -1, 0, 0)
            if len(bucket) + count > self.limit:
                retry_after = max(1, int(self.window_seconds - (now - bucket[0])))
                return RateLimitResult(False, 0, retry_after, self.limit)
            for _ in range(count):
                bucket.append(now)
            return RateLimitResult(True, self.limit - len(bucket), 0, self.limit)

    def peek(self, key: str) -> RateLimitResult:
        now = time.monotonic()
        with self._lock:
            bucket = self._prune(key, now)
            if self.limit <= 0:
                return RateLimitResult(True, -1, 0, 0)
            remaining = max(0, self.limit - len(bucket))
            retry_after = 0
            if remaining == 0:
                retry_after = max(1, int(self.window_seconds - (now - bucket[0])))
            return RateLimitResult(remaining > 0, remaining, retry_after, self.limit)

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)


class LoginThrottle:
    """Failed-login tracker with automatic lockout.

    Tracks failures per ``identifier`` (IP + username).  After
    ``max_attempts`` failures inside ``window_seconds`` the identifier is
    locked for ``lockout_seconds``.
    """

    def __init__(self, max_attempts: int, window_seconds: int, lockout_seconds: int) -> None:
        self.max_attempts = max(1, max_attempts)
        self.window_seconds = max(1, window_seconds)
        self.lockout_seconds = max(0, lockout_seconds)
        self._failures: Dict[str, Deque[float]] = defaultdict(deque)
        self._locked_until: Dict[str, float] = {}
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> Deque[float]:
        bucket = self._failures[key]
        cutoff = now - self.window_seconds
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        return bucket

    def is_locked(self, key: str) -> tuple[bool, int]:
        """Return ``(locked, retry_after_seconds)``."""
        now = time.monotonic()
        with self._lock:
            until = self._locked_until.get(key)
            if until is None:
                return False, 0
            if now >= until:
                self._locked_until.pop(key, None)
                self._failures.pop(key, None)
                return False, 0
            return True, max(1, int(until - now))

    def record_failure(self, key: str) -> int:
        """Register a failed attempt and return the current failure count."""
        now = time.monotonic()
        with self._lock:
            bucket = self._prune(key, now)
            bucket.append(now)
            count = len(bucket)
            if count >= self.max_attempts and self.lockout_seconds > 0:
                self._locked_until[key] = now + self.lockout_seconds
            return count

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)
            self._locked_until.pop(key, None)
