"""Reproduz 100 saídas concorrentes pela rota Flask em banco temporário."""

import json
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from gps import db, services
from gps.app import ROOT, create_app

SKU = "RAM-177"
LOCATION = "A05-COR-047"
REQUESTS = 100


def main() -> None:
    with TemporaryDirectory() as directory:
        database = Path(directory) / "concurrency.db"
        db.initialize(database)
        catalog = json.loads((ROOT / "data/catalogo.json").read_text(encoding="utf-8-sig"))
        services.seed(database, catalog, "credencial-ficticia-para-testes")
        app = create_app(database, "chave-somente-deste-testador", testing=True)
        barrier = threading.Barrier(REQUESTS, timeout=60)

        def withdraw(index: int) -> int:
            client = app.test_client()
            with client.session_transaction() as session:
                session.update(user_id=1, csrf="teste")
            barrier.wait()
            result = client.post(
                "/movimentar",
                data={
                    "csrf": "teste",
                    "key": f"concorrencia-http-gps-{index}",
                    "kind": "out",
                    "sku": SKU,
                    "location": LOCATION,
                    "quantity": "1",
                    "reason": "Teste isolado de concorrência HTTP",
                },
            )
            return result.status_code

        start = perf_counter()
        with ThreadPoolExecutor(max_workers=REQUESTS) as executor:
            statuses = Counter(executor.map(withdraw, range(REQUESTS)))
        elapsed = perf_counter() - start
        issues = db.reconcile(database)
        remaining = db.query(
            database,
            "SELECT quantity FROM balances WHERE sku=? AND location=?",
            (SKU, LOCATION),
            one=True,
        )[0]
        summary = {
            "requests": REQUESTS,
            "status": dict(statuses),
            "balance": remaining,
            "differences": len(issues),
            "seconds": round(elapsed, 3),
        }
        print(json.dumps(summary, ensure_ascii=False))
        if statuses != {302: 36, 400: 64} or remaining != 0 or issues:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
