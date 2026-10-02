"""Password hashing and login throttling.

argon2id, which is what you want for passwords in 2026: memory-hard, so a GPU
farm cannot brute-force it the way it can SHA-256. Falls back to stdlib scrypt
if argon2-cffi is unavailable, which is still memory-hard and still fine.

A password is NEVER stored, logged, or returned. Only the hash is persisted,
and the hash embeds its own salt and parameters so it can be re-tuned later.
"""
from __future__ import annotations
import hashlib, hmac, os, re, secrets, time
from . import db

try:
    from argon2 import PasswordHasher
    from argon2.exceptions import InvalidHashError, VerifyMismatchError
    _ph = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)
    BACKEND = "argon2id"
except ImportError:                      # stdlib fallback, no dependency
    _ph = None
    BACKEND = "scrypt"

MIN_LEN = 10
# Login throttle. The counters live in SQLite (see db.login_fails) rather than
# in a dict here, because a dict is per-process: two workers would each give an
# attacker a fresh five guesses, and a restart would wipe the lockout entirely.
MAX_FAILS, WINDOW, LOCKOUT = 5, 900.0, 900.0
# A whole office or campus can share one address, so the per-IP budget has to be
# much looser than the per-account one or five typos lock out the building. It
# exists to stop spraying many usernames from one host, not to police one user.
MAX_FAILS_IP = 50


def hash_password(pw: str) -> str:
    if _ph:
        return _ph.hash(pw)
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$" + salt.hex() + "$" + dk.hex()


def verify_password(pw: str, stored: str) -> bool:
    """Constant-time where it matters; never raises on a malformed hash."""
    if not stored:
        return False
    try:
        if stored.startswith("scrypt$"):
            _, salt_hex, dk_hex = stored.split("$", 2)
            dk = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt_hex),
                                n=2**14, r=8, p=1, dklen=32)
            return hmac.compare_digest(dk.hex(), dk_hex)
        if _ph:
            _ph.verify(stored, pw)
            return True
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False
    except Exception:
        return False
    return False


def needs_rehash(stored: str) -> bool:
    """True when the stored hash used weaker parameters than we use now."""
    if _ph and stored and not stored.startswith("scrypt$"):
        try:
            return _ph.check_needs_rehash(stored)
        except Exception:
            return False
    return bool(_ph) and stored.startswith("scrypt$")


def strength_problem(pw: str) -> str | None:
    """Length first - it dominates. Then reject the obviously guessable."""
    if len(pw) < MIN_LEN:
        return f"Use at least {MIN_LEN} characters."
    if len(pw) > 256:
        return "That is longer than 256 characters."
    low = pw.lower()
    if re.fullmatch(r"(.)\1+", pw):
        return "That is a single repeated character."
    for bad in ("password", "12345678", "qwerty", "letmein", "monsoon",
                "iloveyou", "admin123", "welcome1"):
        if bad in low:
            return "That contains a very common password."
    if re.fullmatch(r"\d+", pw):
        return "Digits alone are easy to guess - add letters."
    return None


# ───────────────────────── throttling ─────────────────────────
def locked_for(key: str) -> int:
    """Seconds remaining before this identifier may try again, 0 if allowed."""
    key = key.lower()
    hits = db.recent_fails(key, WINDOW)
    limit = MAX_FAILS_IP if key.startswith("ip:") else MAX_FAILS
    if len(hits) < limit:
        return 0
    return max(0, int(LOCKOUT - (time.time() - hits[-1])))


def fail_count(key: str) -> list[float]:
    """Raw hits in the window - used where the budget is not a lockout
    (signups per address, for instance)."""
    return db.recent_fails(key.lower(), WINDOW)


def record_failure(key: str) -> None:
    db.add_fail(key.lower(), WINDOW)


def clear_failures(key: str) -> None:
    db.clear_fails(key.lower())


# One throwaway hash, computed once, so the unknown-user path costs exactly one
# verify - the same as the wrong-password path. Hashing here instead would cost
# two and make "no such user" measurably slower, which is the leak this is
# meant to close.
_DUMMY: str | None = None


def dummy_verify() -> None:
    """Burn the same time as a real check when the user does not exist, so
    response timing does not reveal which usernames are registered."""
    global _DUMMY
    if _DUMMY is None:
        _DUMMY = hash_password(secrets.token_urlsafe(24))
    verify_password("not-the-password", _DUMMY)
