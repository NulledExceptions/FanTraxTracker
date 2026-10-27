"""Helpers for Fantrax's UI-shaped table payloads (``header.cells`` + ``rows[].cells``)."""

from __future__ import annotations

from typing import Any


def header_cells(table: dict[str, Any]) -> list[dict[str, Any]]:
    header = table.get("header") or table.get("tableHeader") or {}
    cells = header.get("cells") if isinstance(header, dict) else None
    return [c for c in cells if isinstance(c, dict)] if isinstance(cells, list) else []


def column_index(
    cells: list[dict[str, Any]], *, short_name: str | None = None, key: str | None = None
) -> int | None:
    for i, cell in enumerate(cells):
        if short_name is not None and cell.get("shortName") == short_name:
            return i
        if key is not None and cell.get("key") == key:
            return i
    return None


def cell_text(row: dict[str, Any], index: int | None) -> str | None:
    if index is None:
        return None
    cells = row.get("cells") or []
    if index >= len(cells) or not isinstance(cells[index], dict):
        return None
    content = cells[index].get("content")
    return str(content) if content is not None else None


def player_rows(table: dict[str, Any]) -> list[dict[str, Any]]:
    """Rows that carry a ``scorer`` (skips the "Reserve spot(s) available" filler rows)."""
    rows = table.get("rows") or table.get("statsTable") or []
    return [r for r in rows if isinstance(r, dict) and isinstance(r.get("scorer"), dict)]


def first_table(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    tables = payload.get("tables")
    if isinstance(tables, list) and tables and isinstance(tables[0], dict):
        return tables[0]
    if "statsTable" in payload:  # player-pool payload: header at top level, rows in statsTable
        return {"header": payload.get("tableHeader") or {}, "rows": payload.get("statsTable") or []}
    return None
