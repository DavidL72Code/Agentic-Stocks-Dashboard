"""Refuse to run a destructive probe against anything but a throwaway database.

The probes isolate themselves by setting DB_PATH to a temp file. That was not
enough: db.conn() gives TURSO_DATABASE_URL priority over DB_PATH, so once Turso
was configured in .env every probe quietly wrote its test users, portfolios and
positions into the LIVE hosted database - and the signup budget it exhausted
there is what finally surfaced it.

Setting the env correctly is the fix; this is the seatbelt. A probe that calls
require_throwaway_db() first cannot silently repeat the mistake, because it
dies instead.
"""
from __future__ import annotations
import os, sys


def require_throwaway_db() -> str:
    """Call before the first write. Exits non-zero with a reason if the target
    is not a local file created for this run.

    Loads .env first, exactly as app.main does. Without that the check reads a
    clean os.environ, passes, and only THEN does main.py load .env and point
    everything at Turso - which is how the first version of this guard sat in
    all four probes and caught nothing.
    """
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), ".env"))
    except ImportError:
        pass

    turso = os.environ.get("TURSO_DATABASE_URL", "").strip()
    if turso:
        host = turso.split("//")[-1].split("/")[0]
        print(f"REFUSING TO RUN: TURSO_DATABASE_URL is set ({host}), and it takes "
              f"priority over DB_PATH - this probe would write test users into a "
              f"hosted database. Clear TURSO_DATABASE_URL for the child process.",
              file=sys.stderr)
        sys.exit(2)

    path = os.environ.get("DB_PATH", "").strip()
    if not path:
        print("REFUSING TO RUN: DB_PATH is unset, so this would use the default "
              "data/monsoon.db - a real book.", file=sys.stderr)
        sys.exit(2)
    if os.path.abspath(path).startswith(os.path.abspath("data") + os.sep):
        print(f"REFUSING TO RUN: DB_PATH points inside data/ ({path}), which is "
              f"where the real database lives.", file=sys.stderr)
        sys.exit(2)
    return path
