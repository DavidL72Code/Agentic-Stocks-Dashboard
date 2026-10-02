"""Model-facing view of evidence.

The raw DTOs keep full precision - the grounding check needs it. But handing a
model `1.08591` for a percentage, `35082000000` for revenue and six margins at
once is what produces number soup: it echoes the precision it is given and
tries to use everything it is shown.

This renders the same facts the way a person would write them, BEFORE the model
sees them. Values stay groundable because ToolResult.numbers() already indexes
rounded and unit-scaled variants of every figure.
"""
from __future__ import annotations
from typing import Any

# fields that restate something another field already says, or that no sentence
# would ever quote - dropped from the model's view, kept in the evidence
NOISE_KEYS = {
    "market_state", "currency", "exchange", "is_stale", "note", "how_to_read",
    "observations", "unusual", "golden_cross", "beats_baseline",
    "significant_at_05", "elevated", "reading", "verdict", "caution",
}


def money(v: float) -> str:
    a = abs(v)
    if a >= 1e12:
        return f"${v/1e12:.2f}T"
    if a >= 1e9:
        return f"${v/1e9:.1f}B"
    if a >= 1e6:
        return f"${v/1e6:.1f}M"
    return f"${v:,.2f}"


def count(v: float) -> str:
    a = abs(v)
    if a >= 1e9:
        return f"{v/1e9:.1f}B"
    if a >= 1e6:
        return f"{v/1e6:.1f}M"
    if a >= 1e3:
        return f"{v/1e3:.0f}K"
    return f"{v:,.0f}"


def _num(key: str, v: float) -> Any:
    k = key.lower()
    if isinstance(v, bool):
        return v
    if abs(v) >= 1e6:
        return money(v) if any(w in k for w in
                               ("usd", "cap", "revenue", "income", "profit", "cash",
                                "debt", "value", "flow", "basis", "pnl", "target")) \
            else count(v)
    if any(w in k for w in ("pct", "percent", "margin", "yield", "growth", "roe",
                            "roa", "rate", "change")):
        return round(v, 1) if abs(v) >= 1 else round(v, 2)
    if abs(v) >= 1000:
        return round(v)
    return round(v, 2)


def present(data: Any, key: str = "") -> Any:
    """Recursively render one tool's data for the prompt."""
    if isinstance(data, bool):
        return data
    if isinstance(data, (int, float)):
        return _num(key, float(data))
    if isinstance(data, dict):
        out = {}
        for k, v in data.items():
            if k in NOISE_KEYS:
                continue
            r = present(v, k)
            if r not in (None, [], {}, ""):
                out[k] = r
        return out
    if isinstance(data, (list, tuple)):
        return [present(x, key) for x in data[:6]]     # long series add no argument
    return data
