"""Os saldos materializados devem seguir o livro até sob operações rejeitadas."""

import json
import tempfile
import unittest
from pathlib import Path

from gps import db, services

try:
    from hypothesis import given, settings
    from hypothesis import strategies as st
except ModuleNotFoundError as error:
    if error.name != "hypothesis":
        raise
    raise unittest.SkipTest("Instale requirements-dev.txt para testar propriedades.") from error

SKU = "RAM-177"
ORIGIN = "A05-COR-047"
DESTINATION = "A05-COR-101"
CATALOG = Path(__file__).resolve().parents[1] / "data" / "catalogo.json"


class LedgerProperties(unittest.TestCase):
    @settings(max_examples=25, deadline=None)
    @given(
        st.lists(
            st.tuples(
                st.sampled_from(("in", "out", "transfer", "count")),
                st.integers(min_value=0, max_value=100),
                st.booleans(),
            ),
            min_size=1,
            max_size=24,
        )
    )
    def test_balances_match_ledger_and_never_go_negative(self, movements):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "property.db"
            db.initialize(path)
            catalog = json.loads(CATALOG.read_text(encoding="utf-8-sig"))
            catalog["produtos"] = [row for row in catalog["produtos"] if row["sku"] == SKU]
            catalog["locacoes"] = [row for row in catalog["locacoes"] if row["codigo"] == ORIGIN]
            catalog["saldos_iniciais_simulados"] = [
                row for row in catalog["saldos_iniciais_simulados"] if row["sku"] == SKU
            ]
            services.seed(path, catalog, "credencial-ficticia-para-testes")
            services.create_location(path, 1, "A05", "Corsair", 101)
            model = {ORIGIN: 36, DESTINATION: 0}
            for index, (kind, quantity, swap) in enumerate(movements):
                start, end = (DESTINATION, ORIGIN) if swap else (ORIGIN, DESTINATION)
                arguments = (
                    path,
                    1,
                    f"propriedade-hypothesis-{index}",
                    kind,
                    SKU,
                    start,
                    quantity,
                    "Movimentação de propriedade",
                )
                options = {"destination": end, "expected": model[start], "confirmed": True}
                rejected = kind != "count" and (
                    quantity == 0 or (kind in {"out", "transfer"} and quantity > model[start])
                )
                if rejected:
                    with self.assertRaises(services.RuleError):
                        services.operate(*arguments, **options)
                else:
                    services.operate(*arguments, **options)
                    if kind == "count":
                        model[start] = quantity
                    elif kind == "in":
                        model[start] += quantity
                    else:
                        model[start] -= quantity
                        if kind == "transfer":
                            model[end] += quantity
                totals = {
                    row["location"]: row["total"]
                    for row in db.query(
                        path,
                        """
                    SELECT location, SUM(delta) AS total FROM entries
                    WHERE sku=? GROUP BY location
                """,
                        (SKU,),
                    )
                }
                actual = {
                    row["location"]: row["quantity"]
                    for row in db.query(
                        path, "SELECT location, quantity FROM balances WHERE sku=?", (SKU,)
                    )
                }
                for location, expected in model.items():
                    self.assertEqual(actual.get(location, 0), expected)
                    self.assertEqual(totals.get(location, 0), expected)
                    self.assertGreaterEqual(expected, 0)
            self.assertEqual(db.reconcile(path), [])
