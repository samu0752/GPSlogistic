"""Mede estoque, histórico por SKU e histórico geral em dados simulados."""

import argparse
import json
from pathlib import Path
from statistics import median, quantiles
from tempfile import TemporaryDirectory
from time import perf_counter

from gps import db, history, services
from gps.app import ROOT

FILTERED = (
    " FROM entries e JOIN operations o ON o.id=e.operation_id JOIN users u ON u.id=o.user_id WHERE "
)
SKU, PLACE = "RAM-177", "A05-COR-047"


def timed(action):
    samples = []
    for _ in range(30):
        start = perf_counter()
        action()
        samples.append((perf_counter() - start) * 1000)
    return {"p50_ms": round(median(samples), 3), "p95_ms": round(quantiles(samples, n=20)[18], 3)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--volumes", nargs="+", type=int, default=[0, 1000, 10000])
    args = parser.parse_args()
    if min(args.volumes) < 0:
        parser.error("Informe volumes a partir de zero.")
    with TemporaryDirectory() as directory:
        path = Path(directory) / "benchmark.db"
        db.initialize(path)
        catalog = json.loads((ROOT / "data/catalogo.json").read_text(encoding="utf-8-sig"))
        services.seed(path, catalog, "credencial-ficticia-para-testes")
        prior = 0
        for volume in sorted(set(args.volumes)):
            # Entrada e saída alternadas mantêm a base em 8.000 nas etapas pares.
            with db.transaction(path) as connection:
                for i in range(prior, volume):
                    kind, delta = ("in", 1) if i % 2 == 0 else ("out", -1)
                    result = connection.execute(
                        """
                        INSERT INTO operations(
                            kind,user_id,created_at,reason,request_key,payload_hash
                        )
                        VALUES (?,1,?,'Benchmark',?,'benchmark')
                    """,
                        (kind, services.now(), f"benchmark-{i}"),
                    )
                    services.add_entry(connection, result.lastrowid, SKU, PLACE, delta)
            prior = volume
            units = db.query(path, "SELECT SUM(quantity) FROM balances", one=True)[0]
            print(
                json.dumps(
                    {
                        "skus": 400,
                        "movements": volume,
                        "units": units,
                        "stock": timed(
                            lambda: db.query(path, "SELECT * FROM balances WHERE sku=?", (SKU,))
                        ),
                        "by_sku": timed(
                            lambda: history.window(path, FILTERED + "e.sku=?", [SKU], None)
                        ),
                        "history": timed(lambda: history.window(path, FILTERED + "1=1", [], None)),
                    }
                )
            )
        if db.reconcile(path):
            raise SystemExit("Foram encontradas divergências no banco do benchmark.")


if __name__ == "__main__":
    main()
