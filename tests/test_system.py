"""Casos críticos do estoque, permissões, HTTP e recuperação. Sem rede externa."""

import csv
import io
import json
import secrets
import sqlite3
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from gps import db
from gps import services as s
from gps.app import create_app
from manage import backup
from manage import main as manage

SKU = "RAM-177"
LOC = "A05-COR-047"
DEST = "A05-COR-101"
PASSWORD = "senha-apenas-para-testes-123"


class SystemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base_dir = tempfile.TemporaryDirectory()
        cls.base = Path(cls.base_dir.name) / "base.db"
        db.initialize(cls.base)
        catalog = json.loads((ROOT / "data" / "catalogo.json").read_text(encoding="utf-8-sig"))
        s.seed(cls.base, catalog, PASSWORD)
        s.create_user(cls.base, 1, "operador", "Operador de teste", PASSWORD, "operador")
        s.create_user(cls.base, 1, "supervisor", "Supervisor de teste", PASSWORD, "supervisor")
        s.create_location(cls.base, 1, "A05", "Corsair", 101)

    @classmethod
    def tearDownClass(cls):
        cls.base_dir.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "test.db"
        backup(self.base, self.path)
        self.app = create_app(self.path, "test-secret-only", testing=True)
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp.cleanup()

    def q(self, sql, params=(), one=False):
        return db.query(self.path, sql, params, one)

    def stock(self, loc=LOC):
        row = self.q("SELECT quantity FROM balances WHERE sku=? AND location=?", (SKU, loc), True)
        return row[0] if row else 0

    def move(self, kind="out", amount=2, **kwargs):
        return s.operate(
            self.path,
            kwargs.pop("user", 1),
            kwargs.pop("key", secrets.token_urlsafe(24)),
            kind,
            SKU,
            LOC,
            amount,
            kwargs.pop("reason", "Movimento de teste"),
            **kwargs,
        )

    def auth(self, user=1):
        with self.client.session_transaction() as session:
            session["user_id"] = user
            session["csrf"] = "csrf-test"

    def test_seed_catalog_and_reconciliation(self):
        self.assertEqual(self.q("SELECT COUNT(*) FROM products", one=True)[0], 400)
        self.assertEqual(self.q("SELECT SUM(quantity) FROM balances", one=True)[0], 8000)
        self.assertEqual(self.stock(), 36)
        self.assertEqual(
            self.q("SELECT unit,modules FROM products WHERE sku=?", (SKU,), True)[:],
            ("kit fechado", 2),
        )
        self.assertEqual(db.reconcile(self.path), [])
        with self.assertRaises(s.RuleError):
            s.seed(self.path, {}, PASSWORD)

    def test_outflow_preserves_previous_and_next_balance(self):
        operation = self.move()
        row = self.q("SELECT * FROM entries WHERE operation_id=?", (operation,), True)
        self.assertEqual((row["before_qty"], row["delta"], row["after_qty"]), (36, -2, 34))
        self.move(amount=3)
        self.assertEqual(self.stock(), 31)
        self.assertEqual(db.reconcile(self.path), [])

    def test_exact_balance_withdrawal_is_allowed(self):
        self.move(amount=36)
        self.assertEqual(self.stock(), 0)

    def test_insufficient_and_invalid_quantities_do_not_write(self):
        for amount in ("-1", "0", "2.5", "abc", "1e3", "1000000001", "", 37):
            with self.subTest(amount=amount), self.assertRaises(s.RuleError):
                self.move(amount=amount)
        self.assertEqual(self.stock(), 36)
        self.assertEqual(self.q("SELECT COUNT(*) FROM operations", one=True)[0], 1)

    def test_transfer_conserves_stock_and_records_two_entries(self):
        operation = self.move("transfer", 7, destination=DEST)
        self.assertEqual((self.stock(), self.stock(DEST)), (29, 7))
        self.assertEqual(
            self.q(
                "SELECT SUM(delta),COUNT(*) FROM entries WHERE operation_id=?", (operation,), True
            )[:],
            (0, 2),
        )
        self.assertEqual(self.q("SELECT SUM(quantity) FROM balances", one=True)[0], 8000)

    def test_transfer_rolls_back_origin_if_destination_overflows(self):
        s.operate(
            self.path,
            1,
            secrets.token_urlsafe(24),
            "in",
            SKU,
            DEST,
            1_000_000_000,
            "Preparar limite máximo",
        )
        with self.assertRaises(s.RuleError):
            self.move("transfer", 3, destination=DEST)
        self.assertEqual(self.stock(), 36)
        self.assertEqual(self.stock(DEST), 1_000_000_000)
        self.assertEqual(db.reconcile(self.path), [])

    def test_location_type_brand_and_same_destination_are_validated(self):
        for destination in (LOC, "A01-KIN-001", "NAO-EXISTE"):
            with self.subTest(destination=destination), self.assertRaises(s.RuleError):
                self.move("transfer", 1, destination=destination)
        self.assertEqual(self.stock(), 36)

    def test_idempotency_and_reused_key_with_other_payload(self):
        key = secrets.token_urlsafe(24)
        operation = self.move(key=key)
        self.assertEqual(self.move(key=key), operation)
        self.assertEqual(self.stock(), 34)
        with self.assertRaises(s.RuleError):
            self.move(amount=3, key=key)
        with self.assertRaises(s.RuleError):
            self.move(key=key, user=2)

    def test_concurrent_outflows_cannot_consume_same_units(self):
        barrier = threading.Barrier(2)

        def withdraw():
            barrier.wait()
            try:
                self.move(amount=30)
                return "ok"
            except s.RuleError:
                return "blocked"

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: withdraw(), range(2)))
        self.assertCountEqual(results, ["ok", "blocked"])
        self.assertEqual(self.stock(), 6)
        self.assertEqual(db.reconcile(self.path), [])

    def test_concurrent_repeated_request_creates_one_operation(self):
        key = secrets.token_urlsafe(24)
        with ThreadPoolExecutor(max_workers=2) as pool:
            operations = list(pool.map(lambda _: self.move(key=key), range(2)))
        self.assertEqual(operations[0], operations[1])
        self.assertEqual(self.stock(), 34)

    def test_reversal_preserves_intervening_movements(self):
        original = self.move(amount=2)
        self.move(amount=3)
        correction = s.reverse(
            self.path,
            1,
            original,
            secrets.token_urlsafe(24),
            "Saída inicial registrada por engano",
            {SKU + "|" + LOC: 31},
            True,
        )
        self.assertEqual(self.stock(), 33)
        self.assertEqual(
            self.q("SELECT reversal_of FROM operations WHERE id=?", (correction,), True)[0],
            original,
        )
        self.assertEqual(
            self.q("SELECT after_qty FROM entries WHERE operation_id=?", (original,), True)[0], 34
        )
        with self.assertRaises(s.RuleError):
            s.reverse(
                self.path,
                1,
                original,
                secrets.token_urlsafe(24),
                "Repetir estorno indevidamente",
                {SKU + "|" + LOC: 33},
                True,
            )

    def test_reversal_preview_stale_or_missing_confirmation(self):
        original = self.move()
        with self.assertRaises(s.RuleError):
            s.reverse(
                self.path,
                1,
                original,
                secrets.token_urlsafe(24),
                "Sem confirmação física",
                {SKU + "|" + LOC: 34},
                False,
            )
        self.move()
        with self.assertRaises(s.RuleError):
            s.reverse(
                self.path,
                1,
                original,
                secrets.token_urlsafe(24),
                "Prévia desatualizada",
                {SKU + "|" + LOC: 34},
                True,
            )
        self.assertEqual(self.stock(), 32)

    def test_reversal_cannot_create_negative_balance(self):
        original = self.move("in", 10)
        self.move(amount=44)
        with self.assertRaises(s.RuleError):
            s.reverse(
                self.path,
                1,
                original,
                secrets.token_urlsafe(24),
                "Entrada duplicada confirmada",
                {SKU + "|" + LOC: 2},
                True,
            )
        self.assertEqual(self.stock(), 2)

    def test_transfer_reversal_is_atomic(self):
        original = self.move("transfer", 4, destination=DEST)
        s.reverse(
            self.path,
            1,
            original,
            secrets.token_urlsafe(24),
            "Transferência incorreta conferida",
            {SKU + "|" + LOC: 32, SKU + "|" + DEST: 4},
            True,
        )
        self.assertEqual((self.stock(), self.stock(DEST)), (36, 0))

    def test_count_zero_and_recovery_preserve_history(self):
        original = self.move("count", 0, expected=36, confirmed=True)
        self.assertEqual(self.stock(), 0)
        self.move(
            "count", 36, expected=0, confirmed=True, reason="Recontagem física confirma 36 kits"
        )
        self.assertEqual(self.stock(), 36)
        self.assertEqual(
            self.q(
                "SELECT before_qty,after_qty FROM entries WHERE operation_id=?", (original,), True
            )[:],
            (36, 0),
        )

    def test_count_rejects_stale_expected_balance(self):
        self.move()
        with self.assertRaises(s.RuleError):
            self.move("count", 0, expected=36, confirmed=True)
        self.assertEqual(self.stock(), 34)

    def test_operator_permissions_checked_in_service(self):
        with self.assertRaises(s.PermissionDenied):
            self.move("count", 0, user=2, expected=36, confirmed=True)
        with self.assertRaises(s.PermissionDenied):
            s.create_location(self.path, 2, "A05", "Corsair", 102)
        with self.assertRaises(s.PermissionDenied):
            s.create_user(self.path, 3, "hacker", "Teste", PASSWORD, "admin")
        self.move(user=2)
        self.assertEqual(self.stock(), 34)

    def test_history_rejects_update_and_delete(self):
        for table in ["entries", "operations", "events"]:
            for sql in [f"DELETE FROM {table}", f"UPDATE {table} SET id=id"]:
                with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                    with db.transaction(self.path) as connection:
                        connection.execute(sql)

    def test_reconcile_detects_direct_balance_tampering(self):
        with db.transaction(self.path) as connection:
            connection.execute(
                "UPDATE balances SET quantity=9 WHERE sku=? AND location=?", (SKU, LOC)
            )
        self.assertIn("Saldos diferentes do histórico", db.reconcile(self.path))

    def test_inactive_master_blocks_operations_and_cannot_hide_stock(self):
        with self.assertRaises(s.RuleError):
            s.toggle_master(self.path, 1, "products", SKU)
        s.toggle_master(self.path, 1, "locations", DEST)
        with self.assertRaises(s.RuleError):
            self.move("transfer", 1, destination=DEST)

    def test_user_deactivation_revokes_access(self):
        self.auth(2)
        s.toggle_user(self.path, 1, 2)
        self.assertEqual(self.client.get("/").status_code, 302)
        with self.assertRaises(s.PermissionDenied):
            self.move(user=2)
        with self.assertRaises(s.RuleError):
            s.toggle_user(self.path, 1, 1)

    def test_authentication_and_throttle(self):
        self.assertEqual(s.login(self.path, "samuel", PASSWORD), 1)
        for _ in range(5):
            with self.assertRaises(s.RuleError):
                s.login(self.path, "samuel", "errada")
        with self.assertRaisesRegex(s.RuleError, "5 minutos"):
            s.login(self.path, "samuel", PASSWORD)

    def test_http_pages_filters_and_exports(self):
        self.auth()
        for path in [
            "/",
            "/estoque",
            "/estoque?q=RAM-177",
            "/estoque?area=A07&brand=Corsair",
            "/estoque?low=1",
            "/estoque?page=2",
            "/produtos/RAM-177",
            "/movimentar?sku=RAM-177&location=A05-COR-047",
            "/movimentar?kind=count",
            "/movimentar?kind=transfer",
            "/historico",
            "/historico?kind=initial",
            "/historico?start=2026-01-01&end=2026-12-31",
            "/operacoes/1",
            "/cadastros",
            "/locacoes",
            "/usuarios",
            "/conta",
            "/auditoria",
            "/exportar/estoque.csv",
            "/exportar/historico.csv?kind=initial",
            "/health",
        ]:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200, response.data[:500])

    def test_http_csrf_permissions_and_missing_record(self):
        self.assertEqual(self.client.get("/estoque").status_code, 302)
        self.auth(2)
        self.assertEqual(self.client.get("/usuarios").status_code, 403)
        self.assertEqual(self.client.get("/movimentar?kind=count").status_code, 403)
        self.assertEqual(self.client.post("/movimentar", data={"kind": "out"}).status_code, 400)
        self.assertEqual(self.client.post("/usuarios", data={"csrf": "csrf-test"}).status_code, 403)
        self.assertEqual(self.client.get("/produtos/INEXISTENTE").status_code, 404)
        self.assertEqual(self.stock(), 36)

    def test_http_movement_double_submission_and_csv_formula_escape(self):
        self.auth()
        data = dict(
            csrf="csrf-test",
            key=secrets.token_urlsafe(24),
            kind="out",
            sku=SKU,
            location=LOC,
            quantity="2",
            reason="=1+1 motivo de teste",
        )
        self.assertEqual(self.client.post("/movimentar", data=data).status_code, 302)
        self.assertEqual(self.client.post("/movimentar", data=data).status_code, 302)
        self.assertEqual(self.stock(), 34)
        response = self.client.get("/exportar/historico.csv?kind=out")
        rows = list(csv.reader(io.StringIO(response.data.decode("utf-8-sig")), delimiter=";"))
        self.assertEqual(rows[1][-1], "'=1+1 motivo de teste")
        self.assertEqual(len(rows), 2)

    def test_http_login_logout_and_password_change(self):
        page = self.client.get("/login")
        self.assertEqual(page.status_code, 200)
        with self.client.session_transaction() as session:
            token = session["csrf"]
        response = self.client.post(
            "/login", data={"csrf": token, "username": "samuel", "password": PASSWORD}
        )
        self.assertEqual(response.status_code, 302)
        self.client.get("/conta")
        with self.client.session_transaction() as session:
            token = session["csrf"]
        self.assertEqual(
            self.client.post(
                "/conta", data={"csrf": token, "old": PASSWORD, "new": "nova-senha-de-testes-456"}
            ).status_code,
            302,
        )
        self.assertEqual(self.client.get("/estoque").status_code, 302)
        self.assertEqual(s.login(self.path, "samuel", "nova-senha-de-testes-456"), 1)

    def test_backup_restore_to_new_file_and_preserve_existing(self):
        self.move()
        copy = Path(self.temp.name) / "backup.sqlite3"
        restored = Path(self.temp.name) / "restored.db"
        backup(self.path, copy)
        self.move()
        self.assertEqual(manage(["restore", str(copy), "--to", str(restored)]), 0)
        self.assertEqual(db.reconcile(restored), [])
        self.assertEqual(
            db.query(
                restored,
                "SELECT quantity FROM balances WHERE sku=? AND location=?",
                (SKU, LOC),
                True,
            )[0],
            34,
        )
        self.assertEqual(self.stock(), 32)
        self.assertEqual(manage(["restore", str(copy), "--to", str(restored)]), 1)

    def test_new_web_user_must_set_password_before_accessing_stock(self):
        self.auth()
        temporary = "senha-temporaria-teste-123"
        personal = "senha-pessoal-teste-456"
        created = self.client.post(
            "/usuarios",
            data={
                "csrf": "csrf-test",
                "username": "novo-operador",
                "name": "Novo operador",
                "role": "operador",
                "password": temporary,
            },
        )
        self.assertEqual(created.status_code, 302)

        def sign_in(client, password):
            client.get("/login")
            with client.session_transaction() as login_session:
                token = login_session["csrf"]
            return client.post(
                "/login", data={"csrf": token, "username": "novo-operador", "password": password}
            )

        user = self.app.test_client()
        another_session = self.app.test_client()
        for client in (user, another_session):
            self.assertEqual(sign_in(client, temporary).location, "/conta")
            self.assertEqual(client.get("/estoque").location, "/conta")
        row = self.q("SELECT id, role FROM users WHERE username='novo-operador'", one=True)
        with self.assertRaises(s.PermissionDenied):
            self.move(user=row["id"])
        page = user.get("/conta")
        self.assertIn(b"Defina sua senha", page.data)
        self.assertNotIn(b'aria-label="Menu principal"', page.data)
        with user.session_transaction() as session:
            token = session["csrf"]

        form = {"csrf": token, "old": temporary, "new": personal, "confirm": "incorreta"}
        self.assertEqual(user.post("/conta", data=form).status_code, 400)
        reused = dict(form, new=temporary, confirm=temporary)
        self.assertEqual(user.post("/conta", data=reused).status_code, 400)
        self.assertEqual(user.post("/conta", data=dict(form, confirm=personal)).location, "/login")
        self.assertEqual(another_session.get("/estoque").location, "/login")
        self.assertEqual(sign_in(user, temporary).status_code, 200)
        self.assertEqual(sign_in(user, personal).location, "/")
        self.assertEqual(user.get("/estoque").status_code, 200)
        self.assertEqual(user.get("/usuarios").status_code, 403)

    def test_new_product_and_location_start_at_zero(self):
        s.create_product(
            self.path,
            1,
            {
                "sku": "RAM-181",
                "brand": "Corsair",
                "manufacturer_code": "TESTE-NAO-COMERCIAL",
                "capacity": "16 GB",
                "unit": "modulo",
                "modules": 1,
                "area": "A05",
            },
        )
        self.assertEqual(
            self.q("SELECT verification FROM products WHERE sku='RAM-181'", one=True)[0],
            "Cadastro manual; especificações não conferidas",
        )
        self.assertIsNone(self.q("SELECT * FROM balances WHERE sku='RAM-181'", one=True))
        self.assertEqual(s.create_location(self.path, 1, "A05", "Corsair", 102), "A05-COR-102")


if __name__ == "__main__":
    unittest.main()
