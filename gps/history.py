"""Consulta do livro de estoque compartilhada por tela, API e benchmark."""

import sqlite3
from pathlib import Path

from . import db

PAGE_SIZE = 40
FIELDS = (
    "e.id,e.operation_id,e.sku,e.location,e.before_qty,e.delta,e.after_qty,"
    "o.kind,o.reason,o.created_at,o.reversal_of,u.name"
)


def window(
    path: str | Path,
    filtered_sql: str,
    values: list[str | int],
    before: int | None,
    size: int = PAGE_SIZE,
) -> tuple[list[sqlite3.Row], int | None]:
    sql = "SELECT " + FIELDS + filtered_sql
    parameters = list(values)
    if before is not None:
        sql += " AND e.id < ?"
        parameters.append(before)
    sql += " ORDER BY e.id DESC LIMIT ?"
    rows = db.query(path, sql, [*parameters, size + 1])
    return rows[:size], rows[size - 1]["id"] if len(rows) > size else None
