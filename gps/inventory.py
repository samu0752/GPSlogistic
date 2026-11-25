"""Indicadores de acuracidade a partir de contagens físicas registradas."""

from . import db


def accuracy(path: db.DatabasePath) -> dict[str, object]:
    rows = db.query(
        path,
        """
        SELECT e.sku, p.brand, COUNT(*) AS counted,
               SUM(e.delta=0) AS exact, SUM(ABS(e.delta)) AS gap,
               SUM(MAX(e.before_qty,e.after_qty)) AS compared,
               SUM(e.before_qty) AS expected, SUM(e.after_qty) AS physical
        FROM operations o JOIN entries e ON e.operation_id=o.id
        JOIN products p ON p.sku=e.sku WHERE o.kind='count'
        GROUP BY e.sku,p.brand ORDER BY gap DESC,e.sku
    """,
    )
    counts = sum(row["counted"] for row in rows)
    exact = sum(row["exact"] for row in rows)
    compared = sum(row["compared"] for row in rows)
    gap = sum(row["gap"] for row in rows)
    return {
        "counts": counts,
        "exact": exact,
        "gap": gap,
        "exact_pct": 100 * exact / counts if counts else None,
        "units_pct": 100 * (1 - gap / compared) if compared else (100 if counts else None),
        "ranking": [row for row in rows if row["gap"] > 0][:30],
    }
