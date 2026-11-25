import io
import json
import re
import sqlite3
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from gps import db, services
from gps.app import ROOT, create_app
from manage import main

SKU = "RAM-177"
LOCATION = "A05-COR-047"


class ReleaseFlows(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "release.db"
        db.initialize(self.path)
        data = json.loads((ROOT / "data/catalogo.json").read_text(encoding="utf-8-sig"))
        services.seed(self.path, data, "credencial-ficticia-para-testes")
        self.client = create_app(self.path, "segredo-ficticio", testing=True).test_client()

    def authenticate(self):
        with self.client.session_transaction() as session:
            session.update(user_id=1, csrf="teste")

    def test_api_rejects_anonymous_and_paginates(self):
        self.assertEqual(self.client.get("/api/v1/estoque").status_code, 401)
        self.authenticate()
        self.assertEqual(self.client.get("/api/v1/estoque?limit=x").status_code, 400)
        response = self.client.get("/api/v1/estoque?limit=1")
        self.assertEqual(len(response.json["items"]), 1)
        self.assertEqual(response.json["next_page"], 2)
        path = "/api/v1/movimentacoes?limit=2"
        first = self.client.get(path).json
        second = self.client.get(f"{path}&before={first['next_before']}").json
        self.assertLess(second["items"][0]["id"], first["items"][-1]["id"])
        self.assertTrue(all("name" not in item for item in first["items"]))

    def test_csv_import_reports_bad_rows(self):
        self.authenticate()
        contents = (
            b"sku;brand;manufacturer_code;capacity;unit;modules;area\n"
            b"SKU-CSV;Corsair;CSV-VALIDO;16 GB;modulo;1;A05\n"
            b"SKU-CSV;Corsair;CSV-DUPLO;16 GB;modulo;1;A05\n"
        )
        response = self.client.post(
            "/cadastros/produtos/importar",
            data={
                "csrf": "teste",
                "products": (io.BytesIO(contents), "test.csv"),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"1 importado(s)", response.data)
        self.assertIn(b"1 erro(s)", response.data)
        self.assertEqual(db.query(self.path, "SELECT COUNT(*) FROM products", one=True)[0], 401)

    def test_report_and_reversal_audit(self):
        self.authenticate()
        op = services.operate(
            self.path,
            1,
            "audit-entrada-123456789",
            "in",
            SKU,
            LOCATION,
            1,
            "Entrada para auditoria",
        )
        reversal = services.reverse(
            self.path,
            1,
            op,
            "audit-estorno-123456789",
            "Revisão da entrada",
            {SKU + "|" + LOCATION: 37},
            True,
        )
        event = db.query(self.path, "SELECT * FROM events WHERE action='reversal'", one=True)
        self.assertEqual(event["user_id"], 1)
        self.assertIn(f"#{reversal} da operação #{op}", event["details"])
        with self.assertRaises(sqlite3.IntegrityError), db.transaction(self.path) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO events VALUES(?,1,?,'reversal','alterado')",
                (event["id"], services.now()),
            )
        services.operate(
            self.path,
            1,
            "accuracy-123456789000",
            "count",
            SKU,
            LOCATION,
            34,
            "Conferência física",
            expected=36,
            confirmed=True,
        )
        report = self.client.get("/inventario/acuracidade")
        self.assertEqual(report.status_code, 200)
        self.assertIn(b"94.4%", report.data)

    def test_first_run_prints_once_with_no_plaintext_file(self):
        new = self.path.with_name("fresh.db")
        calls = ["--database", str(new), "init", "--generate-password"]
        terminal = io.StringIO()
        with redirect_stdout(terminal):
            self.assertEqual(main(calls), 0)
            self.assertEqual(main(calls), 0)
        credentials = re.findall(r"Senha temporária: (\S+)", terminal.getvalue())
        self.assertEqual(len(credentials), 1)
        self.assertFalse((new.parent / "ACESSO_LOCAL.txt").exists())
        self.assertEqual(
            services.login(new, "samuel", credentials[0], with_session_state=True)[2], 1
        )

    def test_peer_limit_and_https_headers(self):
        with self.client.session_transaction() as session:
            session["csrf"] = "teste"
        with (
            patch("gps.services.time") as clock,
            patch(
                "gps.services.check_password_hash",
                return_value=False,
            ),
        ):
            clock.time.return_value = 1_800_000_000
            for _ in range(30):
                result = self.client.post("/login", data={"csrf": "teste", "username": "peer"})
                self.assertEqual(result.status_code, 200)
            result = self.client.post("/login", data={"csrf": "teste", "username": "peer"})
            self.assertEqual(result.status_code, 429)
        self.assertIn(
            "Strict-Transport-Security",
            self.client.get("/health", base_url="https://localhost").headers,
        )
