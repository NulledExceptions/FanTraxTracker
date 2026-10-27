"""Scoring categories and value parsing for Fantrax table payloads."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# Categories where a lower total is better. Everything else is higher-is-better.
LOWER_IS_BETTER: frozenset[str] = frozenset({"TO"})

_NUMBER_RE = re.compile(r"-?\d*\.?\d+")


@dataclass(frozen=True)
class Category:
    key: str  # short name as Fantrax shows it: FG%, 3PTM, FT%, PTS, REB, AST, ST, BLK, TO
    name: str
    higher_is_better: bool
    is_rate: bool  # percentage categories (FG%, FT%) — averaged, not summed

    def better(self, a: float, b: float) -> int:
        """-1 if ``a`` is worse than ``b``, 0 if equal, 1 if better (per this category's direction)."""
        if a == b:
            return 0
        return (1 if a > b else -1) * (1 if self.higher_is_better else -1)


def make_category(key: str, name: str | None = None) -> Category:
    return Category(
        key=key,
        name=name or key,
        higher_is_better=key not in LOWER_IS_BETTER,
        is_rate="%" in key,
    )


def categories_from_header(cells: list[dict[str, Any]]) -> list[Category]:
    """Categories in table order from a Fantrax header whose scoring cells use ``key == "scip"``
    (standings tables) or a ``<group>#<stat>#<pos>`` key (roster / player tables)."""
    out: list[Category] = []
    for cell in cells:
        key = str(cell.get("key", ""))
        short = cell.get("shortName")
        if not isinstance(short, str) or not short:
            continue
        if key == "scip" or "#" in key:
            if short == "GP":  # games played is a column, not a scoring category
                continue
            out.append(make_category(short, cell.get("name") if isinstance(cell.get("name"), str) else None))
    return out


def parse_number(text: Any) -> float | None:
    """``".457"`` → 0.457, ``"1,234"`` → 1234.0, ``""`` / ``"-"`` → None. HTML is stripped first."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    cleaned = re.sub(r"<[^>]+>", " ", str(text)).replace(",", "").strip()
    match = _NUMBER_RE.search(cleaned)
    return float(match.group(0)) if match else None


def format_value(category: Category, value: float | None, *, per_game: bool = False) -> str:
    if value is None:
        return "-"
    if category.is_rate:
        return f"{value:.3f}".lstrip("0") if value < 1 else f"{value:.3f}"
    if per_game:
        return f"{value:.1f}"
    return f"{value:,.0f}" if abs(value - round(value)) < 1e-9 else f"{value:,.1f}"
