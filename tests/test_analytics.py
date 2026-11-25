"""Análises (ABC, movimentação, cobertura) e busca por código do fabricante. Sem rede externa."""

import json
import re
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from gps import analytics, db
from gps import services as s
from gps.app import create_app
from manage import backup

SKU = "RAM-177"
LOC = "A05-COR-047"
MAKER_CODE = "CMK64GX5M2B5600C40"
PASSWORD = "senha-apenas-para-testes-123"


class AnalyticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base_dir = tempfile.TemporaryDirectory()
        cls.base = Path(cls.base_dir.name) / "base.db"
        db.initialize(cls.base)
        catalog = json.loads((ROOT / "data" / "catalogo.json").read_text(encoding="utf-8-sig"))
        s.seed(cls.base, catalog, PASSWORD)

    @classmethod
    def tearDownClass(cls):
        cls.base_dir.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "test.db"
        backup(self.base, self.path)

    def tearDown(self):
        self.temp.cleanup()

    def out(self, amount, key):
        return s.operate(self.path, 1, key, "out", SKU, LOC, amount, "Saída para teste de análise")

    def total(self):
        return db.query(self.path, "SELECT SUM(quantity) FROM balances WHERE sku=?", (SKU,), True)[
            0
        ]

    def test_abc_covers_all_stock_and_is_ordered(self):
        abc = analytics.abc_curve(self.path)
        self.assertEqual(abc["total_units"], 8000)
        self.assertEqual(sum(v["units"] for v in abc["summary"].values()), 8000)
        self.assertEqual(sum(v["products"] for v in abc["summary"].values()), abc["total_products"])
        quantities = [i["quantity"] for i in abc["items"]]
        self.assertEqual(quantities, sorted(quantities, reverse=True))
        self.assertEqual(abc["items"][0]["letter"], "A")
        self.assertAlmostEqual(abc["items"][-1]["share"], 1.0)

    def test_coverage_uses_net_outflow(self):
        self.assertEqual(analytics.coverage(self.path), [])
        self.out(6, "chave-cobertura-0001")
        item = analytics.coverage(self.path)[0]
        self.assertEqual((item["sku"], item["out_30d"]), (SKU, 6))
        self.assertAlmostEqual(item["days"], self.total() / (6 / analytics.COVERAGE_DAYS))

    def test_reversal_cancels_outflow_in_coverage_and_daily(self):
        operation = self.out(4, "chave-estorno-analise-1")
        s.reverse(
            self.path,
            1,
            operation,
            "chave-estorno-analise-2",
            "Estorno para teste de análise",
            {f"{SKU}|{LOC}": 32},
            True,
        )
        self.assertEqual(analytics.coverage(self.path), [])
        today = analytics.daily_movements(self.path)["rows"][-1]
        self.assertEqual((today["out"], today["in"], today["operations"]), (0, 0, 2))

    def test_daily_movements_counts_in_out_and_operations(self):
        timestamp = datetime.now(UTC)
        with patch.object(s, "now", return_value=timestamp.isoformat(timespec="microseconds")):
            self.out(2, "chave-diaria-0000001")
            s.operate(
                self.path, 1, "chave-diaria-0000002", "in", SKU, LOC, 5, "Entrada para teste diário"
            )
        data = analytics.daily_movements(self.path, today=timestamp)
        self.assertEqual(len(data["rows"]), analytics.PERIOD_DAYS)
        today = data["rows"][-1]
        self.assertEqual((today["out"], today["in"], today["operations"]), (2, 5, 2))
        self.assertEqual(data["peak"], 5)

    def test_old_outflow_is_ignored(self):
        self.out(3, "chave-antiga-00000001")
        future = datetime.now(UTC) + timedelta(days=analytics.COVERAGE_DAYS + 5)
        self.assertEqual(analytics.coverage(self.path, today=future), [])

    def test_manufacturer_code_resolves_to_sku(self):
        before = self.total()
        s.operate(
            self.path,
            1,
            "chave-codigo-fabricante",
            "out",
            MAKER_CODE.lower(),
            LOC,
            1,
            "Saída lida pelo código do fabricante",
        )
        self.assertEqual(self.total(), before - 1)
        row = db.query(self.path, "SELECT sku FROM entries ORDER BY id DESC LIMIT 1", one=True)
        self.assertEqual(row["sku"], SKU)

    def test_unknown_code_is_still_rejected(self):
        with self.assertRaises(s.RuleError):
            s.operate(
                self.path,
                1,
                "chave-codigo-invalido",
                "out",
                "CODIGO-INEXISTENTE",
                LOC,
                1,
                "Código que não existe",
            )
        self.assertEqual(
            self.total(),
            36
            + sum(
                r[0]
                for r in db.query(
                    self.path,
                    "SELECT quantity FROM balances WHERE sku=? AND location!=?",
                    (SKU, LOC),
                )
            ),
        )

    def test_page_requires_login_and_renders(self):
        app = create_app(self.path, "test-secret-only", testing=True)
        client = app.test_client()
        self.assertEqual(client.get("/analises").status_code, 302)
        token = re.search(
            r'name="csrf" value="([^"]+)"', client.get("/login").get_data(as_text=True)
        ).group(1)
        self.assertEqual(
            client.post(
                "/login", data={"csrf": token, "username": "samuel", "password": PASSWORD}
            ).status_code,
            302,
        )
        self.out(2, "chave-pagina-0000001")
        page = client.get("/analises")
        html = page.get_data(as_text=True)
        self.assertEqual(page.status_code, 200)
        for text in ("CURVA ABC", "Cobertura estimada", "Últimos 14 dias", SKU):
            self.assertIn(text, html)
        self.assertNotIn("style=", html)  # a política de segurança bloqueia estilo inline


if __name__ == "__main__":
    unittest.main()
