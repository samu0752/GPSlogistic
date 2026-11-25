"""SQLite e transações. O livro de movimentações alimenta o saldo automaticamente."""

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Literal, overload

DatabasePath = str | Path

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
LEGACY_COLUMNS = {
    "ALTER TABLE users ADD COLUMN must_change_password": "must_change_password",
    "ALTER TABLE users ADD COLUMN auth_version": "auth_version",
}


def connect(path: DatabasePath) -> sqlite3.Connection:
    connection = sqlite3.connect(str(path), timeout=15, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA recursive_triggers=ON")
    connection.execute("PRAGMA busy_timeout=15000")
    return connection


def _statements(path: Path) -> Iterator[str]:
    statement = ""
    for line in path.read_text(encoding="utf-8").splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            yield statement.strip()
            statement = ""
    if statement.strip():
        raise RuntimeError(f"Migração SQL incompleta: {path.name}")


def initialize(path: DatabasePath) -> None:
    """Aplica migrações pendentes juntas, preservando o esquema legado."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    connection = connect(path)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
    finally:
        connection.close()

    files = {int(file.name[:3]): file for file in sorted(MIGRATIONS.glob("[0-9][0-9][0-9]_*.sql"))}
    with transaction(path) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS schema_version(
                version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        applied = {
            row["version"] for row in connection.execute("SELECT version FROM schema_version")
        }
        if not files or applied.difference(files):
            raise RuntimeError("Versão de banco incompatível. Faça backup antes de migrar.")
        previous = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='metadata'"
        ).fetchone()
        if previous:
            legacy = connection.execute(
                "SELECT value FROM metadata WHERE key='schema_version'"
            ).fetchone()
            if legacy and legacy[0] != "1":
                raise RuntimeError("Versão legada incompatível. Faça backup antes de migrar.")
        for version, file in files.items():
            if version in applied:
                continue
            if version == 2:
                columns = {row["name"] for row in connection.execute("PRAGMA table_info(users)")}
            else:
                columns = set()
            for statement in _statements(file):
                if any(
                    statement.startswith(prefix) and column in columns
                    for prefix, column in LEGACY_COLUMNS.items()
                ):
                    continue
                connection.execute(statement)
            connection.execute("INSERT INTO schema_version(version) VALUES (?)", (version,))
        connection.execute("INSERT OR IGNORE INTO metadata VALUES('schema_version','1')")


@contextmanager
def transaction(path: DatabasePath) -> Iterator[sqlite3.Connection]:
    """Reserva a escrita antes de ler saldos: duas saídas não consomem a mesma unidade."""
    connection = connect(path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


@overload
def query(
    path: DatabasePath,
    sql: str,
    params: Sequence[object] = (),
    one: Literal[False] = False,
) -> list[sqlite3.Row]: ...


@overload
def query(
    path: DatabasePath,
    sql: str,
    params: Sequence[object],
    one: Literal[True],
) -> sqlite3.Row | None: ...


@overload
def query(
    path: DatabasePath,
    sql: str,
    *,
    one: Literal[True],
) -> sqlite3.Row | None: ...


def query(
    path: DatabasePath,
    sql: str,
    params: Sequence[object] = (),
    one: bool = False,
) -> sqlite3.Row | list[sqlite3.Row] | None:
    connection = connect(path)
    try:
        cursor = connection.execute(sql, params)
        return cursor.fetchone() if one else cursor.fetchall()
    finally:
        connection.close()


def reconcile(path: DatabasePath) -> list[str]:
    """Confere integridade, saldo acumulado e continuidade do livro, sem alterar dados."""
    connection = connect(path)
    try:
        connection.execute("BEGIN")
        issues = []
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            issues.append("Falha na integridade SQLite")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            issues.append("Referências inválidas")
        expected: dict[tuple[str, str], int] = {}
        for entry in connection.execute("SELECT * FROM entries ORDER BY id"):
            key = (entry["sku"], entry["location"])
            if expected.get(key, 0) != entry["before_qty"]:
                issues.append(f"Quebra na sequência do lançamento {entry['id']}")
            expected[key] = entry["after_qty"]
        actual = {
            (r["sku"], r["location"]): r["quantity"]
            for r in connection.execute("SELECT * FROM balances")
        }
        if actual != expected:
            issues.append("Saldos diferentes do histórico")
        if connection.execute(
            "SELECT id FROM operations WHERE id NOT IN (SELECT operation_id FROM entries)"
        ).fetchone():
            issues.append("Operação sem lançamentos")
        return issues
    finally:
        connection.close()
