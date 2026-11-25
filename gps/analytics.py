"""Análises de leitura sobre saldos e histórico. Não altera nenhum dado."""

from datetime import UTC, datetime, timedelta, timezone

from . import db

LOCAL = timezone(timedelta(hours=-3))  # mesmo fuso usado nos filtros de data
PERIOD_DAYS = 14
COVERAGE_DAYS = 30


def abc_curve(path):
    """Curva ABC por unidades em estoque: A até 80%, B até 95%, C o restante."""
    rows = db.query(
        path,
        "SELECT p.sku,p.brand,COALESCE(SUM(b.quantity),0) AS quantity FROM products p "
        "LEFT JOIN balances b ON b.sku=p.sku WHERE p.active=1 GROUP BY p.sku "
        "HAVING quantity>0 ORDER BY quantity DESC, p.sku",
    )
    total = sum(r["quantity"] for r in rows)
    items, accumulated = [], 0
    for r in rows:
        before = accumulated / total if total else 0
        accumulated += r["quantity"]
        share = accumulated / total if total else 0
        letter = "A" if before < 0.80 else "B" if before < 0.95 else "C"
        items.append(
            {
                "sku": r["sku"],
                "brand": r["brand"],
                "quantity": r["quantity"],
                "share": share,
                "letter": letter,
            }
        )
    summary = {
        c: {
            "products": sum(1 for i in items if i["letter"] == c),
            "units": sum(i["quantity"] for i in items if i["letter"] == c),
        }
        for c in "ABC"
    }
    return {"total_units": total, "total_products": len(items), "items": items, "summary": summary}


def _effective_kind(kind, original_kind):
    """Estorno conta como o tipo da operação original, com sinal contrário."""
    return original_kind if kind == "reversal" else kind


def _movements(path, since):
    return db.query(
        path,
        "SELECT o.created_at,o.kind,orig.kind AS original_kind,e.sku,e.delta FROM entries e "
        "JOIN operations o ON o.id=e.operation_id LEFT JOIN operations orig ON "
        "orig.id=o.reversal_of "
        "WHERE o.kind!='initial' AND o.created_at>=? ORDER BY e.id",
        (since,),
    )


def daily_movements(path, today=None):
    """Entradas e saídas líquidas (com estornos) por dia, nos últimos 14 dias."""
    today = today or datetime.now(UTC)
    first = (today.astimezone(LOCAL) - timedelta(days=PERIOD_DAYS - 1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    days = {
        (first + timedelta(days=i)).date(): {"in": 0, "out": 0, "operations": 0}
        for i in range(PERIOD_DAYS)
    }
    for r in _movements(path, first.astimezone(UTC).isoformat(timespec="microseconds")):
        day = datetime.fromisoformat(r["created_at"]).astimezone(LOCAL).date()
        if day not in days:
            continue
        kind = _effective_kind(r["kind"], r["original_kind"])
        if kind == "in":
            days[day]["in"] += r["delta"]
        elif kind == "out":
            days[day]["out"] -= r["delta"]
    for r in db.query(
        path,
        "SELECT created_at FROM operations WHERE kind!='initial' AND created_at>=?",
        (first.astimezone(UTC).isoformat(timespec="microseconds"),),
    ):
        day = datetime.fromisoformat(r["created_at"]).astimezone(LOCAL).date()
        if day in days:
            days[day]["operations"] += 1
    rows = [{"day": d, **v} for d, v in days.items()]
    peak = max([max(r["in"], r["out"]) for r in rows] + [1])
    return {"rows": rows, "peak": peak}


def coverage(path, today=None, limit=15):
    """Dias de cobertura = saldo atual / média diária de saída líquida nos últimos 30 dias."""
    today = today or datetime.now(UTC)
    since = (today - timedelta(days=COVERAGE_DAYS)).isoformat(timespec="microseconds")
    out = {}
    for r in _movements(path, since):
        if _effective_kind(r["kind"], r["original_kind"]) == "out":
            out[r["sku"]] = out.get(r["sku"], 0) - r["delta"]
    stock = {
        r["sku"]: r["quantity"]
        for r in db.query(path, "SELECT sku,SUM(quantity) AS quantity FROM balances GROUP BY sku")
    }
    items = []
    for sku, total_out in out.items():
        if total_out <= 0:
            continue
        daily = total_out / COVERAGE_DAYS
        items.append(
            {
                "sku": sku,
                "stock": stock.get(sku, 0),
                "out_30d": total_out,
                "daily": daily,
                "days": stock.get(sku, 0) / daily,
            }
        )
    items.sort(key=lambda i: (i["days"], i["sku"]))
    return items[:limit]


def build(path, today=None):
    return {
        "abc": abc_curve(path),
        "daily": daily_movements(path, today),
        "coverage": coverage(path, today),
        "coverage_days": COVERAGE_DAYS,
    }
