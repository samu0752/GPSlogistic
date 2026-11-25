"""Importação de cadastro por CSV, reutilizando a validação do formulário."""

import csv
import io
import sqlite3

from . import db, services

FIELDS = ("sku", "brand", "manufacturer_code", "capacity", "unit", "modules", "area")
MAX_BYTES = 256 * 1024
MAX_ROWS = 500


def import_products(
    path: db.DatabasePath,
    actor: int,
    input_data: bytes,
) -> tuple[int, list[tuple[int, str]]]:
    if not input_data or len(input_data) > MAX_BYTES:
        raise services.RuleError("Envie um CSV de até 256 KiB.")
    try:
        source = input_data.decode("utf-8-sig")
        if "\x00" in source:
            raise services.RuleError("O CSV contém caracteres inválidos.")
        first_line = source.partition("\n")[0]
        delimiter = ";" if ";" in first_line else ","
        reader = csv.reader(io.StringIO(source, newline=""), delimiter=delimiter, strict=True)
        header = next(reader, [])
        if len(header) != len(FIELDS) or set(header) != set(FIELDS):
            raise services.RuleError("Use o cabeçalho do modelo de CSV.")
        records: list[tuple[int, list[str]]] = []
        while len(records) <= MAX_ROWS:
            line = reader.line_num + 1
            values = next(reader, None)
            if values is None:
                break
            records.append((line, values))
    except (UnicodeDecodeError, csv.Error) as error:
        raise services.RuleError("O CSV deve ser válido e codificado em UTF-8.") from error
    if len(records) > MAX_ROWS:
        raise services.RuleError("O CSV deve ter no máximo 500 linhas de produtos.")

    imported = 0
    errors = []
    with db.transaction(path) as connection:
        services.authorize(connection, actor, "supervisor")
        for line, values in records:
            if len(values) != len(header) or any(not field.strip() for field in values):
                errors.append((line, "Preencha todos os campos do modelo."))
                continue
            connection.execute("SAVEPOINT product_row")
            try:
                services.insert_product(connection, actor, dict(zip(header, values, strict=True)))
            except (services.RuleError, sqlite3.IntegrityError) as error:
                connection.execute("ROLLBACK TO product_row")
                message = (
                    str(error)
                    if isinstance(error, services.RuleError)
                    else ("SKU ou código do fabricante já cadastrado nesta marca.")
                )
                errors.append((line, message))
            else:
                imported += 1
            finally:
                connection.execute("RELEASE product_row")
    return imported, errors
