"""Regras de negócio independentes do navegador; todas as escritas são atômicas."""

import hashlib
import json
import re
import secrets
import sqlite3
import time
from collections.abc import Mapping
from datetime import UTC, datetime, timezone
from typing import Any, Literal, overload

from werkzeug.security import check_password_hash, generate_password_hash

from .db import DatabasePath, transaction

KINDS = {
    "initial": "Carga inicial",
    "in": "Entrada",
    "out": "Saída",
    "transfer": "Transferência",
    "count": "Contagem física",
    "reversal": "Estorno",
}
ROLES = {"operador": 0, "supervisor": 1, "admin": 2}
MAX_QTY = 1_000_000_000


class RuleError(ValueError):
    pass


class PermissionDenied(RuleError):
    pass


class LoginLimited(RuleError):
    pass


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def text(value: object, label: str, minimum: int = 1, maximum: int = 240) -> str:
    value = str(value or "").strip()
    if not minimum <= len(value) <= maximum:
        raise RuleError(f"{label}: informe entre {minimum} e {maximum} caracteres.")
    return value


def quantity(value: object, zero: bool = False) -> int:
    raw = str(value).strip()
    if not re.fullmatch(r"[0-9]{1,10}", raw):
        raise RuleError("A quantidade deve ser um número inteiro, sem sinal ou casas decimais.")
    amount = int(raw)
    if not (0 if zero else 1) <= amount <= MAX_QTY:
        raise RuleError("Quantidade fora do limite permitido.")
    return amount


def authorize(
    connection: sqlite3.Connection,
    user_id: int,
    role: str = "operador",
    *,
    allow_pending: bool = False,
) -> sqlite3.Row:
    user = connection.execute("SELECT * FROM users WHERE id=? AND active=1", (user_id,)).fetchone()
    if not user or ROLES[user["role"]] < ROLES[role]:
        raise PermissionDenied("Seu perfil não tem permissão para esta ação.")
    if user["must_change_password"] and not allow_pending:
        raise PermissionDenied("Defina sua senha pessoal antes de usar o sistema.")
    return user


def event(connection: sqlite3.Connection, user_id: int | None, action: str, details: str) -> None:
    connection.execute(
        "INSERT INTO events(user_id,created_at,action,details) VALUES(?,?,?,?)",
        (user_id, now(), action, details),
    )


def balance(connection: sqlite3.Connection, sku: str, location: str) -> int:
    row = connection.execute(
        "SELECT quantity FROM balances WHERE sku=? AND location=?", (sku, location)
    ).fetchone()
    return row[0] if row else 0


def compatible(connection: sqlite3.Connection, sku: str, location: str) -> sqlite3.Row:
    product = connection.execute(
        "SELECT * FROM products WHERE sku=? AND active=1", (sku,)
    ).fetchone()
    place = connection.execute(
        "SELECT l.*,a.category,a.type FROM locations l JOIN areas a ON a.code=l.area "
        "WHERE l.code=? AND l.active=1",
        (location,),
    ).fetchone()
    if not product or not place:
        raise RuleError("Produto ou locação inexistente/inativo.")
    if (product["brand"], product["category"], product["type"]) != (
        place["brand"],
        place["category"],
        place["type"],
    ):
        raise RuleError("A locação precisa pertencer ao tipo e à marca do produto.")
    return product


def resolve_sku(connection: sqlite3.Connection, value: str) -> str:
    """Aceita o SKU interno ou o código do fabricante (ex.: lido por leitor de código de barras)."""
    if connection.execute("SELECT 1 FROM products WHERE sku=?", (value,)).fetchone():
        return value
    found = connection.execute(
        "SELECT sku FROM products WHERE UPPER(manufacturer_code)=?", (value,)
    ).fetchall()
    if len(found) > 1:
        raise RuleError(
            "Código do fabricante repetido em mais de um produto. Informe o SKU interno."
        )
    return found[0]["sku"] if found else value


def add_entry(
    connection: sqlite3.Connection, operation: int | None, sku: str, location: str, delta: int
) -> None:
    if operation is None:
        raise RuntimeError("O SQLite não retornou o identificador da operação.")
    before = balance(connection, sku, location)
    after = before + delta
    if not 0 <= after <= MAX_QTY:
        raise RuleError(
            f"Saldo insuficiente ou limite excedido em {location}. Saldo atual: {before}."
        )
    connection.execute(
        "INSERT INTO entries(operation_id,sku,location,before_qty,delta,after_qty) VALUES(?,?,"
        "?,?,?,?)",
        (operation, sku, location, before, delta, after),
    )


def request(
    connection: sqlite3.Connection, key: str, user_id: int, payload: list[object]
) -> tuple[str, int | None]:
    key = text(key, "Identificador da operação", 20, 100)
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    existing = connection.execute("SELECT * FROM operations WHERE request_key=?", (key,)).fetchone()
    if existing:
        if existing["user_id"] != user_id or existing["payload_hash"] != digest:
            raise RuleError(
                "Este formulário já foi utilizado com outros dados. Abra um novo formulário."
            )
        return digest, existing["id"]
    return digest, None


def operate(
    path: DatabasePath,
    user_id: int,
    key: str,
    kind: str,
    sku: str,
    location: str,
    amount: object,
    reason: str,
    destination: str = "",
    expected: object = None,
    confirmed: bool = False,
) -> int:
    if kind not in {"in", "out", "transfer", "count"}:
        raise RuleError("Tipo de operação inválido.")
    units = quantity(amount, zero=kind == "count")
    reason = text(reason, "Motivo", 8, 500)
    sku, location, destination = (
        sku.strip().upper(),
        location.strip().upper(),
        destination.strip().upper(),
    )
    expected = quantity(expected, zero=True) if kind == "count" else None
    payload = [kind, sku, location, units, reason, destination, expected, bool(confirmed)]
    with transaction(path) as connection:
        authorize(connection, user_id, "supervisor" if kind == "count" else "operador")
        digest, existing = request(connection, key, user_id, payload)
        if existing:
            return existing
        sku = resolve_sku(connection, sku)
        compatible(connection, sku, location)
        before = balance(connection, sku, location)
        if kind == "count":
            if not confirmed:
                raise RuleError("Confirme que realizou a contagem física desta locação.")
            if before != expected:
                raise RuleError(
                    "O saldo mudou desde a consulta. Atualize a página e faça nova conferência."
                )
            delta = units - before
        else:
            delta = units if kind == "in" else -units
        if kind == "transfer":
            if location == destination:
                raise RuleError("Origem e destino devem ser diferentes.")
            compatible(connection, sku, destination)
        operation = connection.execute(
            "INSERT INTO operations(kind,user_id,created_at,reason,request_key,payload_hash) "
            "VALUES(?,?,?,?,?,?)",
            (kind, user_id, now(), reason, key, digest),
        ).lastrowid
        add_entry(connection, operation, sku, location, delta)
        if kind == "transfer":
            add_entry(connection, operation, sku, destination, units)
        if operation is None:
            raise RuntimeError("O SQLite não retornou o identificador da operação.")
        return operation


def reverse(
    path: DatabasePath,
    user_id: int,
    operation_id: int,
    key: str,
    reason: str,
    expected: object,
    confirmed: bool,
) -> int:
    reason = text(reason, "Motivo do estorno", 8, 500)
    with transaction(path) as connection:
        authorize(connection, user_id, "supervisor")
        digest, existing = request(
            connection, key, user_id, ["reversal", operation_id, reason, expected, bool(confirmed)]
        )
        if existing:
            return existing
        original = connection.execute(
            "SELECT * FROM operations WHERE id=?", (operation_id,)
        ).fetchone()
        if not original or original["kind"] not in {"in", "out", "transfer"}:
            raise RuleError(
                "Só entradas, saídas e transferências podem ser estornadas. Para contagens, "
                "faça nova contagem."
            )
        if connection.execute(
            "SELECT id FROM operations WHERE reversal_of=?", (operation_id,)
        ).fetchone():
            raise RuleError("Esta operação já foi estornada.")
        if not confirmed or not isinstance(expected, dict):
            raise RuleError("Confira os saldos previstos e confirme a verificação física.")
        entries = connection.execute(
            "SELECT * FROM entries WHERE operation_id=? ORDER BY id", (operation_id,)
        ).fetchall()
        for entry in entries:
            compatible(connection, entry["sku"], entry["location"])
            snapshot_key = entry["sku"] + "|" + entry["location"]
            if expected.get(snapshot_key) != balance(connection, entry["sku"], entry["location"]):
                raise RuleError(
                    "O saldo mudou após a prévia do estorno. Atualize e confira novamente."
                )
        operation = connection.execute(
            "INSERT INTO operations(kind,user_id,created_at,reason,request_key,payload_hash,"
            "reversal_of) VALUES(?,?,?,?,?,?,?)",
            ("reversal", user_id, now(), reason, key, digest, operation_id),
        ).lastrowid
        for entry in entries:
            add_entry(connection, operation, entry["sku"], entry["location"], -entry["delta"])
        if operation is None:
            raise RuntimeError("O SQLite não retornou o identificador da operação.")
        return operation


def seed(
    path: DatabasePath,
    catalog: Mapping[str, list[dict[str, Any]]],
    password: str,
    *,
    temporary: bool = False,
) -> None:
    if len(password) < 12:
        raise RuleError("Use uma senha de pelo menos 12 caracteres.")
    with transaction(path) as connection:
        if connection.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            raise RuleError("Banco já inicializado; seus dados foram preservados.")
        user_id = connection.execute(
            "INSERT INTO users(username,name,password_hash,role,must_change_password) "
            "VALUES(?,?,?,?,?)",
            ("samuel", "Samuel", generate_password_hash(password), "admin", temporary),
        ).lastrowid
        for area in catalog["areas"]:
            connection.execute(
                "INSERT INTO areas VALUES(?,?,?)", (area["codigo"], area["categoria"], area["tipo"])
            )
        for brand in catalog["marcas"]:
            connection.execute("INSERT INTO brands VALUES(?,?)", (brand["codigo"], brand["nome"]))
        for product in catalog["produtos"]:
            connection.execute(
                "INSERT INTO products(sku,brand,manufacturer_code,description,category,type,"
                "capacity,unit,modules,source,verification) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    product["sku"],
                    product["marca"],
                    product["codigo_fabricante"],
                    product["descricao"],
                    product["categoria"],
                    product["tipo"],
                    product["capacidade"],
                    product["unidade_comercial"],
                    product.get("modulos_por_unidade", 1),
                    product["fonte_oficial"],
                    product["verificacao"],
                ),
            )
        for loc in catalog["locacoes"]:
            connection.execute(
                "INSERT INTO locations(code,area,brand) VALUES(?,?,?)",
                (loc["codigo"], loc["area"], loc["marca"]),
            )
        operation = connection.execute(
            "INSERT INTO operations(kind,user_id,created_at,reason,request_key,payload_hash) "
            "VALUES(?,?,?,?,?,?)",
            (
                "initial",
                user_id,
                now(),
                "Carga inicial: 8.000 unidades comerciais simuladas para demonstração.",
                secrets.token_urlsafe(24),
                "seed-v1",
            ),
        ).lastrowid
        for stock in catalog["saldos_iniciais_simulados"]:
            compatible(connection, stock["sku"], stock["locacao"])
            add_entry(connection, operation, stock["sku"], stock["locacao"], stock["quantidade"])
        event(
            connection,
            user_id,
            "initialization",
            "Catálogo real importado; empresa e saldos simulados.",
        )


def peer_permitted(connection: sqlite3.Connection, peer: str, timestamp: float) -> bool:
    window = int(timestamp // 60)
    digest = hashlib.sha256(peer.encode()).hexdigest()
    connection.execute("DELETE FROM login_peer_limits WHERE window < ?", (window,))
    change = connection.execute(
        """
        INSERT INTO login_peer_limits(peer,window,attempts) VALUES (?,?,1)
        ON CONFLICT(peer,window) DO UPDATE SET attempts=attempts+1
        WHERE login_peer_limits.attempts < 30
    """,
        (digest, window),
    )
    return change.rowcount == 1


@overload
def login(
    path: DatabasePath,
    username: str,
    password: str,
    *,
    with_session_state: Literal[False] = False,
    peer: str | None = None,
) -> int: ...


@overload
def login(
    path: DatabasePath,
    username: str,
    password: str,
    *,
    with_session_state: Literal[True],
    peer: str | None = None,
) -> tuple[int, int, int]: ...


def login(
    path: DatabasePath,
    username: str,
    password: str,
    *,
    with_session_state: bool = False,
    peer: str | None = None,
) -> int | tuple[int, int, int]:
    username = str(username).strip().lower()[:80]
    login_name = username if re.fullmatch(r"[a-z0-9._-]{1,40}", username) else "inválido"
    current = time.time()
    error, user = None, None
    if peer:
        with transaction(path) as connection:
            allowed = peer_permitted(connection, peer, current)
            if not allowed:
                event(connection, None, "login_rate_limited", f"Identificador: {login_name}")
        if not allowed:
            raise LoginLimited("Muitas tentativas deste endereço. Tente daqui a um minuto.")
    with transaction(path) as connection:
        limit = connection.execute(
            "SELECT * FROM login_limits WHERE username=?", (username,)
        ).fetchone()
        if limit and limit["locked_until"] > current:
            event(connection, None, "login_locked", f"Identificador: {login_name}")
            error = "Muitas tentativas. Aguarde 5 minutos antes de tentar novamente."
        else:
            user = connection.execute(
                "SELECT * FROM users WHERE username=? AND active=1", (username,)
            ).fetchone()
            password_hash = user["password_hash"] if user else DUMMY_HASH
            valid = len(password) <= 128 and check_password_hash(password_hash, password)
            if user and valid:
                connection.execute("DELETE FROM login_limits WHERE username=?", (username,))
                event(connection, user["id"], "login", f"Acesso autorizado: {login_name}")
            else:
                failures = (limit["failures"] if limit and limit["locked_until"] == 0 else 0) + 1
                connection.execute(
                    "INSERT INTO login_limits VALUES(?,?,?) ON CONFLICT(username) DO UPDATE "
                    "SET failures=excluded.failures,locked_until=excluded.locked_until",
                    (username, failures, current + 300 if failures >= 5 else 0),
                )
                event(
                    connection,
                    user["id"] if user else None,
                    "login_failed",
                    f"Tentativa recusada: {login_name}",
                )
                error = "Usuário ou senha inválidos."
    if error:
        raise RuleError(error)
    if user is None:
        raise RuleError("Usuário ou senha inválidos.")
    if with_session_state:
        return user["id"], user["auth_version"], user["must_change_password"]
    return user["id"]


DUMMY_HASH = generate_password_hash(secrets.token_urlsafe(24))


def create_user(
    path: DatabasePath,
    actor: int,
    username: str | None,
    name: str | None,
    password: str,
    role: str,
    *,
    temporary: bool = False,
) -> None:
    username = text(username, "Login", 3, 40).lower()
    if not re.fullmatch("[a-z0-9._-]+", username) or role not in ROLES:
        raise RuleError("Login ou perfil inválido.")
    name = text(name, "Nome", 2, 80)
    if not 12 <= len(password) <= 128:
        raise RuleError("A senha deve conter entre 12 e 128 caracteres.")
    with transaction(path) as connection:
        authorize(connection, actor, "admin")
        connection.execute(
            "INSERT INTO users(username,name,password_hash,role,must_change_password) VALUES(?,"
            "?,?,?,?)",
            (username, name, generate_password_hash(password), role, temporary),
        )
        event(connection, actor, "create_user", f"{username}: {role}")


def toggle_user(path: DatabasePath, actor: int, target: int) -> None:
    with transaction(path) as connection:
        authorize(connection, actor, "admin")
        if actor == target:
            raise RuleError("Você não pode desativar sua própria conta.")
        user = connection.execute("SELECT * FROM users WHERE id=?", (target,)).fetchone()
        if not user:
            raise RuleError("Usuário não encontrado.")
        connection.execute(
            "UPDATE users SET active=1-active, auth_version=auth_version+1 WHERE id=?", (target,)
        )
        event(connection, actor, "toggle_user", f"{user['username']}: ativo={1 - user['active']}")


def change_password(path: DatabasePath, actor: int, old: str, new: str) -> None:
    if not 12 <= len(new) <= 128:
        raise RuleError("A nova senha deve conter entre 12 e 128 caracteres.")
    with transaction(path) as connection:
        user = authorize(connection, actor, allow_pending=True)
        if not check_password_hash(user["password_hash"], old):
            raise RuleError("Senha atual incorreta.")
        if user["must_change_password"] and new == old:
            raise RuleError("Escolha uma senha diferente da senha temporária.")
        connection.execute(
            "UPDATE users SET password_hash=?, must_change_password=0, "
            "auth_version=auth_version+1 WHERE id=?",
            (generate_password_hash(new), actor),
        )
        event(connection, actor, "change_password", "Senha alterada pelo próprio usuário")


def create_product(path: DatabasePath, actor: int, data: Mapping[str, Any]) -> None:
    with transaction(path) as connection:
        authorize(connection, actor, "supervisor")
        insert_product(connection, actor, data)


def insert_product(connection: sqlite3.Connection, actor: int, data: Mapping[str, Any]) -> None:
    sku = text(data.get("sku"), "SKU", 3, 40).upper()
    if not re.fullmatch("[A-Z0-9-]+", sku):
        raise RuleError("SKU deve usar apenas letras, números e hífen.")
    brand = text(data.get("brand"), "Marca")
    code = text(data.get("manufacturer_code"), "Código do fabricante", 2, 100).upper()
    capacity = text(data.get("capacity"), "Capacidade", 1, 80)
    unit = data.get("unit")
    modules = quantity(data.get("modules", 1))
    if (
        unit not in {"modulo", "kit fechado", "unidade"}
        or (unit != "kit fechado" and modules != 1)
        or modules > 16
    ):
        raise RuleError("Unidade ou quantidade de módulos inválida.")
    area = connection.execute("SELECT * FROM areas WHERE code=?", (data.get("area"),)).fetchone()
    if not area or not connection.execute("SELECT 1 FROM brands WHERE name=?", (brand,)).fetchone():
        raise RuleError("Tipo ou marca inválidos.")
    if area["category"] != "RAM" and (unit != "unidade" or modules != 1):
        raise RuleError("SSDs e HDs são contados por unidade.")
    description = f"{brand} {area['category']} {area['type']} {capacity} — {code}"
    connection.execute(
        "INSERT INTO products(sku,brand,manufacturer_code,description,category,type,"
        "capacity,unit,modules,verification) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            sku,
            brand,
            code,
            description,
            area["category"],
            area["type"],
            capacity,
            unit,
            modules,
            "Cadastro manual; especificações não conferidas",
        ),
    )
    event(connection, actor, "create_product", sku)


def create_location(
    path: DatabasePath, actor: int, area: str | None, brand: str | None, position: object
) -> str:
    slot = quantity(position)
    if slot > 999:
        raise RuleError("A posição deve estar entre 1 e 999.")
    with transaction(path) as connection:
        authorize(connection, actor, "supervisor")
        brand_row = connection.execute("SELECT code FROM brands WHERE name=?", (brand,)).fetchone()
        if (
            not brand_row
            or not connection.execute("SELECT 1 FROM areas WHERE code=?", (area,)).fetchone()
        ):
            raise RuleError("Área ou marca inválida.")
        code = f"{area}-{brand_row[0]}-{slot:03d}"
        connection.execute(
            "INSERT INTO locations(code,area,brand) VALUES(?,?,?)", (code, area, brand)
        )
        event(connection, actor, "create_location", code)
        return code


def toggle_master(
    path: DatabasePath, actor: int, entity: str | None, identifier: str | None
) -> None:
    if entity == "products":
        find_master = "SELECT active FROM products WHERE sku=?"
        find_balance = "SELECT 1 FROM balances WHERE sku=? AND quantity>0"
        toggle = "UPDATE products SET active=1-active WHERE sku=?"
    elif entity == "locations":
        find_master = "SELECT active FROM locations WHERE code=?"
        find_balance = "SELECT 1 FROM balances WHERE location=? AND quantity>0"
        toggle = "UPDATE locations SET active=1-active WHERE code=?"
    else:
        raise RuleError("Cadastro inválido.")
    with transaction(path) as connection:
        authorize(connection, actor, "supervisor")
        row = connection.execute(find_master, (identifier,)).fetchone()
        if not row:
            raise RuleError("Cadastro não encontrado.")
        if row["active"] and connection.execute(find_balance, (identifier,)).fetchone():
            raise RuleError("Transfira ou regularize o saldo antes de inativar este cadastro.")
        connection.execute(toggle, (identifier,))
        event(connection, actor, "toggle_" + entity, f"{identifier}: ativo={1 - row['active']}")


def set_minimum(path: DatabasePath, actor: int, sku: str, value: object) -> None:
    minimum = quantity(value, zero=True)
    with transaction(path) as connection:
        authorize(connection, actor, "supervisor")
        product = connection.execute("SELECT minimum FROM products WHERE sku=?", (sku,)).fetchone()
        if not product:
            raise RuleError("Produto não encontrado.")
        if product["minimum"] == minimum:
            return
        connection.execute("UPDATE products SET minimum=? WHERE sku=?", (minimum, sku))
        event(connection, actor, "product_minimum", f"{sku}: {product['minimum']} → {minimum}")


def review_count(path: DatabasePath, actor: int, entry_id: int, note: str | None) -> None:
    note = text(note, "Observação da revisão", 8, 500)
    action = f"review_count:{entry_id}"
    with transaction(path) as connection:
        authorize(connection, actor, "supervisor")
        discrepancy = connection.execute(
            "SELECT e.id FROM entries e JOIN operations o ON o.id=e.operation_id "
            "WHERE e.id=? AND o.kind='count' AND e.delta<>0",
            (entry_id,),
        ).fetchone()
        if not discrepancy:
            raise RuleError("Divergência de contagem não encontrada.")
        if connection.execute("SELECT 1 FROM events WHERE action=?", (action,)).fetchone():
            return
        event(connection, actor, action, note)
