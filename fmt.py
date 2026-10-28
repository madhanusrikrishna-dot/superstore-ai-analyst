"""fmt.py - number formatting used everywhere, so every number looks the same."""

import math


def money(v: float) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    sign = "-" if v < 0 else ""
    v = abs(v)
    if v >= 1_000_000:
        return f"{sign}${v / 1_000_000:.2f}M"
    if v >= 10_000:
        return f"{sign}${v / 1_000:.1f}K"
    if v >= 100:
        return f"{sign}${v:,.0f}"
    return f"{sign}${v:,.2f}"


def pct(v: float, signed: bool = False) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    return f"{v * 100:+.1f}%" if signed else f"{v * 100:.1f}%"


def count(v: float) -> str:
    return f"{int(round(v)):,}"


def value(metric: str, v: float) -> str:
    """Format a value by its metric."""
    if metric in ("margin", "discount"):
        return pct(v)
    if metric in ("orders", "customers", "quantity"):
        return count(v)
    return money(v)


def growth(old: float, new: float) -> float:
    """% change that keeps the right direction when the old value is negative (e.g. a loss shrinking)."""
    if not old or (isinstance(old, float) and math.isnan(old)):
        return float("nan")
    return (new - old) / abs(old)


def change(metric: str, old: float, new: float) -> str:
    """Change between two values: % for normal metrics, percentage points for ratios.
    When a value is a loss, % change is confusing, so the money difference is shown instead."""
    if metric in ("margin", "discount"):
        return f"{(new - old) * 100:+.1f} pts"
    if old < 0 or new < 0:
        diff = new - old
        return ("+" if diff >= 0 else "") + money(diff)
    if not old:
        return "—"
    return pct(growth(old, new), signed=True)
