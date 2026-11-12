"""Process-wide facts /api/health reports - so start-up cost on the host can be
read without access to its logs - and request activity, so background work can
wait for a quiet moment."""
import time

WARM: dict = {}
ACTIVITY = {"last": time.time(), "inflight": 0}
