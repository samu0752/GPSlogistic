"""Interface web. Validação de acesso aqui e também na camada de negócio."""

import csv
import io
import json
import logging
import os
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter

from flask import (
    Flask,
    Response,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from flask.logging import default_handler
from werkzeug.middleware.proxy_fix import ProxyFix

from . import analytics, db, inventory
from . import history as ledger
from . import imports as product_import
from . import services as svc

ROOT = Path(__file__).resolve().parent.parent


def private_file(path: str, flags: int) -> int:
    return os.open(path, flags, 0o600)


def create_app(
    database: db.DatabasePath | None = None,
    secret: str | None = None,
    testing: bool = False,
) -> Flask:
    app = Flask(__name__)
    app.logger.setLevel(logging.INFO)
    if default_handler in app.logger.handlers:
        app.logger.removeHandler(default_handler)
        stream = logging.StreamHandler()
        stream.setFormatter(logging.Formatter("%(message)s"))
        app.logger.addHandler(stream)
    path = Path(database or os.getenv("GPS_DATABASE") or ROOT / "instance" / "gpslogistic.db")
    instance = path.parent
    instance.mkdir(parents=True, exist_ok=True)
    secret = secret or os.getenv("GPS_SECRET_KEY")
    if secret is None:
        secret_path = instance / "session.key"
        if not secret_path.exists():
            try:
                with open(secret_path, "x", encoding="utf-8", opener=private_file) as file:
                    file.write(secrets.token_hex(32))
            except FileExistsError:
                pass
        secret = secret_path.read_text(encoding="utf-8").strip()
    app.config.update(
        SECRET_KEY=secret,
        DATABASE=str(path),
        TESTING=testing,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_SECURE=os.getenv("GPS_COOKIE_SECURE") == "1",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        MAX_CONTENT_LENGTH=32 * 1024,
    )
    if os.getenv("GPS_TRUST_PROXY") == "1":
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
    if path.is_file():
        db.initialize(app.config["DATABASE"])

    def q(sql, params=(), one=False):
        return db.query(app.config["DATABASE"], sql, params, one)

    def csrf():
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(32)
        return session["csrf"]

    def require(role="operador"):
        if not g.user or svc.ROLES[g.user["role"]] < svc.ROLES[role]:
            abort(403)

    @app.before_request
    def access():
        g.user = None
        g.started = perf_counter()
        if request.endpoint in {"static", "health"}:
            return
        if not Path(app.config["DATABASE"]).exists():
            return render_template(
                "error.html",
                title="Banco não inicializado",
                message="Execute python manage.py init antes de abrir o sistema.",
            ), 503
        if session.get("user_id"):
            g.user = q("SELECT * FROM users WHERE id=? AND active=1", (session["user_id"],), True)
            if not g.user or g.user["auth_version"] != session.get("auth_version", 0):
                g.user = None
                session.clear()
        if request.endpoint == "import_products":
            request.max_content_length = product_import.MAX_BYTES + 16 * 1024
        if request.method == "POST":
            supplied = request.form.get("csrf", "").encode()
            expected = session.get("csrf", "").encode()
            if not supplied or not secrets.compare_digest(supplied, expected):
                abort(
                    400, description="Formulário expirado. Recarregue a página e tente novamente."
                )
        if request.path.startswith("/api/v1/"):
            if not g.user:
                return {"error": "Autenticação necessária."}, 401
            if g.user["must_change_password"]:
                return {"error": "Defina a senha pessoal em /conta."}, 403
        if not g.user and request.endpoint not in {"login", "health", "openapi"}:
            return redirect(url_for("login"))
        if (
            g.user
            and g.user["must_change_password"]
            and request.endpoint not in {"account", "logout", "login", "health"}
        ):
            return redirect(url_for("account"))

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(self), microphone=(), geolocation=()"
        if request.is_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; "
            "frame-ancestors 'none'; form-action 'self'; base-uri 'self'; object-src 'none'"
        )
        response.headers["Cache-Control"] = "no-store"
        if not testing and request.endpoint != "static":
            app.logger.info(
                json.dumps(
                    {
                        "event": "http.request",
                        "at": svc.now(),
                        "endpoint": request.endpoint,
                        "method": request.method,
                        "status": response.status_code,
                        "duration_ms": round((perf_counter() - g.started) * 1000, 2),
                    }
                )
            )
        return response

    @app.context_processor
    def context():
        return dict(
            csrf=csrf,
            request_key=lambda: secrets.token_urlsafe(24),
            kinds=svc.KINDS,
            supervisor=bool(g.user and svc.ROLES[g.user["role"]] >= 1),
            administrator=bool(g.user and g.user["role"] == "admin"),
        )

    @app.template_filter("localdate")
    def localdate(value):
        if not value:
            return "—"
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(timezone(timedelta(hours=-3))).strftime("%d/%m/%Y %H:%M:%S")

    @app.template_filter("number")
    def number(value):
        return f"{value:,}".replace(",", ".")

    def wants_json() -> bool:
        if request.path.startswith(("/api/v1/", "/health")):
            return True
        best = request.accept_mimetypes.best_match(["application/json", "text/html"])
        return best == "application/json" and (
            request.accept_mimetypes[best] > request.accept_mimetypes["text/html"]
        )

    def render_error(status: int, title: str, message: str):
        if wants_json():
            return {"code": status, "title": title, "error": message}, status
        return render_template("error.html", code=status, title=title, message=message), status

    @app.errorhandler(svc.PermissionDenied)
    def denied(error):
        return render_error(403, "Acesso restrito", str(error))

    @app.errorhandler(svc.RuleError)
    def rule(error):
        return render_error(400, "Operação não realizada", str(error))

    @app.errorhandler(sqlite3.IntegrityError)
    def conflict(error):
        app.logger.warning("Restrição de integridade: %s", error)
        return render_error(
            409,
            "Cadastro ou operação recusada",
            (
                "Há um código já cadastrado ou uma regra de integridade não atendida. "
                "Nenhuma alteração parcial foi salva."
            ),
        )

    @app.errorhandler(sqlite3.OperationalError)
    def database_error(error):
        app.logger.exception("Falha no banco de dados")
        return render_error(
            503,
            "Banco temporariamente indisponível",
            "Tente novamente. Se o problema persistir, consulte o guia de operação.",
        )

    for status in (400, 403, 404, 405, 409, 413, 422, 429, 500):

        def http_error(error, status=status):
            catalog = {
                400: ("Requisição inválida", "Formulário inválido ou expirado. Reabra a tela."),
                403: ("Acesso restrito", "Seu perfil não permite esta ação."),
                404: ("Não encontrado", "O registro ou a página não foi encontrado."),
                405: ("Método não permitido", "Esta rota não aceita o método enviado."),
                409: ("Conflito de operação", "O estado atual impediu a conclusão da operação."),
                413: ("Envio muito grande", "Formulário ou arquivo maior que o limite permitido."),
                422: ("Dados inválidos", "Não foi possível processar os dados enviados."),
                429: ("Muitas tentativas", "Aguarde alguns minutos antes de tentar novamente."),
                500: (
                    "Erro interno do servidor",
                    "Ocorreu um erro interno. Consulte os registros técnicos.",
                ),
            }
            title, message = catalog[status]
            return render_error(status, title, message)

        app.register_error_handler(status, http_error)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = None
        if request.method == "POST":
            try:
                user_id, version, pending = svc.login(
                    app.config["DATABASE"],
                    request.form.get("username", ""),
                    request.form.get("password", ""),
                    with_session_state=True,
                    peer=request.remote_addr,
                )
                session.clear()
                session["user_id"] = user_id
                session["auth_version"] = version
                session.permanent = True
                return redirect(url_for("account" if pending else "dashboard"))
            except svc.LoginLimited as exc:
                response = Response(render_template("login.html", error=str(exc)), status=429)
                response.headers["Retry-After"] = "60"
                return response
            except svc.RuleError as exc:
                error = str(exc)
        return render_template("login.html", error=error)

    @app.post("/logout")
    def logout():
        with db.transaction(app.config["DATABASE"]) as connection:
            svc.event(connection, g.user["id"], "logout", "Sessão encerrada")
        session.clear()
        return redirect(url_for("login"))

    @app.get("/health")
    def health():
        result = {"status": "ok", "app": "GPSlogistic", "version": "1.0.0"}
        path = app.config["DATABASE"]
        if not Path(path).is_file():
            return {**result, "status": "unavailable"}, 503
        try:
            if not q("SELECT 1 FROM users LIMIT 1", one=True):
                return {**result, "status": "unavailable"}, 503
            q("SELECT MAX(version) FROM schema_version", one=True)
        except sqlite3.Error:
            return {**result, "status": "unavailable"}, 503
        return result

    @app.get("/")
    def dashboard():
        stats = {
            "products": q("SELECT COUNT(*) FROM products WHERE active=1", one=True)[0],
            "units": q("SELECT COALESCE(SUM(quantity),0) FROM balances", one=True)[0],
            "locations": q("SELECT COUNT(*) FROM locations WHERE active=1", one=True)[0],
            "operations": q("SELECT COUNT(*) FROM operations WHERE kind!='initial'", one=True)[0],
            "low": q(
                "SELECT COUNT(*) FROM products p WHERE active=1 AND COALESCE((SELECT "
                "SUM(quantity) FROM balances b WHERE b.sku=p.sku),0)<p.minimum",
                one=True,
            )[0],
        }
        areas = q(
            "SELECT a.*,COUNT(DISTINCT l.code) AS positions,COALESCE(SUM(b.quantity),0) AS "
            "quantity FROM areas a "
            "LEFT JOIN locations l ON l.area=a.code LEFT JOIN balances b ON b.location=l.code "
            "GROUP BY a.code ORDER BY a.code"
        )
        recent = q(
            "SELECT o.*,u.name FROM operations o JOIN users u ON u.id=o.user_id ORDER BY o.id "
            "DESC LIMIT 6"
        )
        return render_template("dashboard.html", stats=stats, areas=areas, recent=recent)

    def stock_query():
        search = request.args.get("q", "").strip()[:100]
        area = request.args.get("area", "")
        brand = request.args.get("brand", "")
        conditions = ["1=1"]
        values = []
        if search:
            conditions.append(
                "(p.sku LIKE ? OR p.manufacturer_code LIKE ? OR p.description LIKE ? OR l.code "
                "LIKE ?)"
            )
            values.extend(["%" + search + "%"] * 4)
        if area:
            conditions.append("l.area=?")
            values.append(area)
        if brand:
            conditions.append("p.brand=?")
            values.append(brand)
        if request.args.get("low") == "1":
            conditions.append(
                "COALESCE((SELECT SUM(x.quantity) FROM balances x WHERE x.sku=p.sku),"
                "0)<p.minimum AND p.active=1"
            )
        sql = (
            " FROM products p LEFT JOIN balances b ON p.sku=b.sku LEFT JOIN locations l ON "
            "l.code=b.location WHERE " + " AND ".join(conditions)
        )
        return sql, values

    @app.get("/estoque")
    def stock():
        sql, values = stock_query()
        total = q("SELECT COUNT(*)" + sql, values, True)[0]
        page = min(max(1, request.args.get("page", 1, type=int)), max(1, (total + 39) // 40))
        rows = q(
            "SELECT p.*,l.code AS location,COALESCE(b.quantity,0) AS quantity"
            + sql
            + " ORDER BY p.sku,l.code LIMIT 40 OFFSET ?",
            values + [(page - 1) * 40],
        )
        args = {k: request.args[k] for k in ("q", "area", "brand", "low") if k in request.args}
        return render_template(
            "stock.html",
            rows=rows,
            total=total,
            page=page,
            args=args,
            areas=q("SELECT * FROM areas ORDER BY code"),
            brands=q("SELECT * FROM brands ORDER BY name"),
        )

    @app.get("/produtos/<sku>")
    def product(sku):
        item = q("SELECT * FROM products WHERE sku=?", (sku,), True)
        if not item:
            abort(404)
        balances = q("SELECT * FROM balances WHERE sku=? ORDER BY location", (sku,))
        return render_template("product.html", item=item, balances=balances)

    @app.post("/produtos/<sku>/minimo")
    def product_minimum(sku):
        require("supervisor")
        svc.set_minimum(app.config["DATABASE"], g.user["id"], sku, request.form.get("minimum"))
        flash("Estoque mínimo atualizado.", "success")
        return redirect(url_for("product", sku=sku))

    @app.get("/divergencias")
    def discrepancies():
        require("supervisor")
        reviewed = request.args.get("reviewed") == "1"
        rows = q(
            """SELECT e.*, o.reason, o.created_at, u.name, review.details AS review_note,
                            reviewer.name AS reviewer, review.created_at AS reviewed_at
                     FROM entries e JOIN operations o ON o.id=e.operation_id
                     JOIN users u ON u.id=o.user_id
                     LEFT JOIN events review ON review.action='review_count:' || e.id
                     LEFT JOIN users reviewer ON reviewer.id=review.user_id
                     WHERE o.kind='count' AND e.delta<>0 AND (review.id IS NOT NULL)=?
                     ORDER BY e.id DESC""",
            (reviewed,),
        )
        return render_template("discrepancies.html", rows=rows, reviewed=reviewed)

    @app.post("/divergencias/<int:entry_id>/revisar")
    def review_discrepancy(entry_id):
        require("supervisor")
        svc.review_count(app.config["DATABASE"], g.user["id"], entry_id, request.form.get("note"))
        flash("Revisão registrada.", "success")
        return redirect(url_for("discrepancies"))

    @app.get("/inventario/acuracidade")
    def inventory_accuracy():
        require("supervisor")
        return render_template("accuracy.html", report=inventory.accuracy(app.config["DATABASE"]))

    @app.get("/analises")
    def analytics_page():
        require()
        return render_template("analytics.html", data=analytics.build(app.config["DATABASE"]))

    @app.route("/movimentar", methods=["GET", "POST"])
    def movement():
        require()
        if request.method == "POST":
            f = request.form
            operation = svc.operate(
                app.config["DATABASE"],
                g.user["id"],
                f.get("key", ""),
                f.get("kind", ""),
                f.get("sku", ""),
                f.get("location", ""),
                f.get("quantity", ""),
                f.get("reason", ""),
                f.get("destination", ""),
                f.get("expected"),
                f.get("confirmed") == "yes",
            )
            flash(f"Operação #{operation} registrada. Saldo e histórico salvos juntos.", "success")
            return redirect(url_for("operation_detail", operation_id=operation))
        kind = request.args.get("kind", "out")
        if kind not in {"in", "out", "transfer", "count"}:
            abort(400)
        if kind == "count":
            require("supervisor")
        selected = request.args.get("sku", "")
        place = request.args.get("location", "")
        products = q(
            "SELECT sku,manufacturer_code,description,unit,brand,type FROM products WHERE "
            "active=1 ORDER BY sku"
        )
        locations = q(
            "SELECT l.*,a.type FROM locations l JOIN areas a ON a.code=l.area WHERE l.active=1 "
            "ORDER BY l.code"
        )
        balances = q("SELECT * FROM balances")
        return render_template(
            "movement.html",
            kind=kind,
            selected=selected,
            place=place,
            products=products,
            locations=locations,
            balance_data=[dict(r) for r in balances],
            collector=request.args.get("collector") == "1",
        )

    def history_query():
        conditions = ["1=1"]
        values = []
        search = request.args.get("q", "").strip()[:100]
        if search:
            conditions.append("(e.sku LIKE ? OR e.location LIKE ? OR o.reason LIKE ?)")
            values.extend(["%" + search + "%"] * 3)
        for field in ("sku", "location"):
            value = request.args.get(field, "").strip().upper()[:100]
            if value:
                conditions.append(f"e.{field}=?")
                values.append(value)
        if request.args.get("kind"):
            conditions.append("o.kind=?")
            values.append(request.args["kind"])
        for field, operator, suffix in [
            ("start", ">=", "T00:00:00-03:00"),
            ("end", "<", "T00:00:00-03:00"),
        ]:
            value = request.args.get(field, "")
            if value:
                try:
                    day = datetime.strptime(value, "%Y-%m-%d")
                    if field == "end":
                        day += timedelta(days=1)
                    instant = (
                        datetime.fromisoformat(day.strftime("%Y-%m-%d") + suffix)
                        .astimezone(UTC)
                        .isoformat(timespec="microseconds")
                    )
                except (ValueError, OverflowError) as error:
                    raise svc.RuleError("Data de filtro inválida.") from error
                conditions.append(f"o.created_at {operator} ?")
                values.append(instant)
        sql = (
            " FROM entries e JOIN operations o ON o.id=e.operation_id JOIN users u ON "
            "u.id=o.user_id WHERE " + " AND ".join(conditions)
        )
        return sql, values

    @app.get("/historico")
    def history():
        sql, values = history_query()
        args = {
            k: request.args[k]
            for k in ("q", "sku", "location", "kind", "start", "end")
            if k in request.args
        }
        page = None
        next_cursor = None
        if "page" in request.args and "before" not in request.args:
            total = q("SELECT COUNT(*)" + sql, values, True)[0]
            page = min(max(1, request.args.get("page", 1, type=int)), max(1, (total + 39) // 40))
            rows = q(
                "SELECT " + ledger.FIELDS + sql + " ORDER BY e.id DESC LIMIT 40 OFFSET ?",
                [*values, (page - 1) * 40],
            )
        else:
            total = None
            next_before = request.args.get("before", type=int)
            if "before" in request.args and (
                next_before is None or not 1 <= next_before <= 2**63 - 1
            ):
                abort(400)
            rows, next_cursor = ledger.window(app.config["DATABASE"], sql, values, next_before)
        return render_template(
            "history.html",
            rows=rows,
            total=total,
            page=page,
            args=args,
            next_cursor=next_cursor,
        )

    def api_number(key: str, default: int, maximum: int) -> int:
        value = request.args.get(key, default, type=int)
        raw = request.args.get(key)
        if (raw is not None and not raw.isascii()) or not 1 <= value <= maximum:
            raise svc.RuleError(f"Parâmetro inválido: {key}.")
        if raw is not None and not raw.isdecimal():
            raise svc.RuleError(f"Parâmetro inválido: {key}.")
        return value

    @app.get("/api/v1/estoque")
    def api_stock():
        sql, values = stock_query()
        size = api_number("limit", 40, 100)
        page = api_number("page", 1, 1_000_000)
        rows = q(
            "SELECT p.sku,p.brand,p.unit,l.code AS location,COALESCE(b.quantity,0) AS quantity"
            + sql
            + " ORDER BY p.sku,l.code LIMIT ? OFFSET ?",
            [*values, size + 1, (page - 1) * size],
        )
        return {
            "items": [dict(row) for row in rows[:size]],
            "next_page": page + 1 if len(rows) > size and page < 1_000_000 else None,
        }

    @app.get("/api/v1/movimentacoes")
    def api_movements():
        limit = api_number("limit", 40, 100)
        before = api_number("before", 1, 2**63 - 1) if "before" in request.args else None
        kind = request.args.get("kind")
        if kind and kind not in svc.KINDS:
            raise svc.RuleError("Tipo de operação inválido.")
        sql, values = history_query()
        rows, next_cursor = ledger.window(app.config["DATABASE"], sql, values, before, limit)
        items = [
            {
                k: row[k]
                for k in (
                    "id",
                    "operation_id",
                    "sku",
                    "location",
                    "kind",
                    "created_at",
                    "before_qty",
                    "delta",
                    "after_qty",
                    "reversal_of",
                )
            }
            for row in rows
        ]
        return {"items": items, "next_before": next_cursor}

    @app.get("/api/openapi.yaml")
    def openapi():
        return send_file(ROOT / "docs" / "openapi.yaml", mimetype="application/yaml")

    @app.get("/operacoes/<int:operation_id>")
    def operation_detail(operation_id):
        operation = q(
            "SELECT o.*,u.name FROM operations o JOIN users u ON u.id=o.user_id WHERE o.id=?",
            (operation_id,),
            True,
        )
        if not operation:
            abort(404)
        entries = q(
            "SELECT e.*,b.quantity AS current_qty,p.unit FROM entries e JOIN balances b ON "
            "b.sku=e.sku AND b.location=e.location "
            "JOIN products p ON p.sku=e.sku WHERE e.operation_id=? ORDER BY e.id",
            (operation_id,),
        )
        reversal = q("SELECT id FROM operations WHERE reversal_of=?", (operation_id,), True)
        expected = {e["sku"] + "|" + e["location"]: e["current_qty"] for e in entries}
        return render_template(
            "operation.html",
            operation=operation,
            entries=entries,
            reversal=reversal,
            expected=expected,
        )

    @app.post("/operacoes/<int:operation_id>/estornar")
    def reverse(operation_id):
        require("supervisor")
        try:
            expected = json.loads(request.form.get("expected", "null"))
        except ValueError:
            abort(400)
        operation = svc.reverse(
            app.config["DATABASE"],
            g.user["id"],
            operation_id,
            request.form.get("key", ""),
            request.form.get("reason", ""),
            expected,
            request.form.get("confirmed") == "yes",
        )
        flash("Estorno registrado. A operação original continua no histórico.", "success")
        return redirect(url_for("operation_detail", operation_id=operation))

    @app.route("/cadastros", methods=["GET", "POST"])
    def masters():
        require("supervisor")
        if request.method == "POST":
            f = request.form
            if f.get("entity") == "product":
                svc.create_product(app.config["DATABASE"], g.user["id"], f)
            elif f.get("entity") == "location":
                svc.create_location(
                    app.config["DATABASE"],
                    g.user["id"],
                    f.get("area"),
                    f.get("brand"),
                    f.get("position"),
                )
            else:
                abort(400)
            flash("Cadastro criado. O saldo inicial é zero.", "success")
            return redirect(url_for("masters"))
        return render_template(
            "masters.html",
            areas=q("SELECT * FROM areas ORDER BY code"),
            brands=q("SELECT * FROM brands ORDER BY name"),
        )

    @app.route("/cadastros/produtos/importar", methods=["GET", "POST"])
    def import_products():
        require("supervisor")
        imported, errors = None, []
        if request.method == "POST":
            uploaded = request.files.get("products")
            if not uploaded or not (uploaded.filename or "").lower().endswith(".csv"):
                raise svc.RuleError("Selecione um arquivo .csv.")
            imported, errors = product_import.import_products(
                app.config["DATABASE"],
                g.user["id"],
                uploaded.stream.read(product_import.MAX_BYTES + 1),
            )
        return render_template("import_products.html", imported=imported, errors=errors)

    @app.get("/cadastros/produtos/modelo.csv")
    def product_csv_template():
        require("supervisor")
        sample = (
            ";".join(product_import.FIELDS)
            + "\nGPS-TESTE;Corsair;MODELO-TESTE;16 GB;modulo;1;A05\n"
        )
        return Response(
            sample,
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=produtos-modelo.csv"},
        )

    @app.post("/cadastros/status")
    def toggle_master():
        require("supervisor")
        svc.toggle_master(
            app.config["DATABASE"],
            g.user["id"],
            request.form.get("entity"),
            request.form.get("identifier"),
        )
        flash("Situação atualizada. O histórico foi preservado.", "success")
        return redirect(
            url_for("locations") if request.form.get("entity") == "locations" else url_for("stock")
        )

    @app.get("/locacoes")
    def locations():
        search = request.args.get("q", "")[:100]
        rows = q(
            "SELECT l.*,a.type,COALESCE(SUM(b.quantity),0) AS quantity,COUNT(CASE WHEN "
            "b.quantity>0 THEN 1 END) AS products "
            "FROM locations l JOIN areas a ON a.code=l.area LEFT JOIN balances b ON "
            "b.location=l.code "
            "WHERE l.code LIKE ? OR l.brand LIKE ? GROUP BY l.code ORDER BY l.code",
            ("%" + search + "%", "%" + search + "%"),
        )
        return render_template("locations.html", rows=rows)

    @app.route("/usuarios", methods=["GET", "POST"])
    def users():
        require("admin")
        if request.method == "POST":
            f = request.form
            svc.create_user(
                app.config["DATABASE"],
                g.user["id"],
                f.get("username"),
                f.get("name"),
                f.get("password", ""),
                f.get("role"),
                temporary=True,
            )
            flash("Usuário criado. No primeiro acesso, ele definirá a própria senha.", "success")
            return redirect(url_for("users"))
        return render_template(
            "users.html",
            users=q(
                "SELECT id,username,name,role,active,must_change_password FROM users ORDER BY id"
            ),
        )

    @app.post("/usuarios/<int:user_id>/status")
    def toggle_user(user_id):
        require("admin")
        svc.toggle_user(app.config["DATABASE"], g.user["id"], user_id)
        flash("Acesso atualizado.", "success")
        return redirect(url_for("users"))

    @app.route("/conta", methods=["GET", "POST"])
    def account():
        pending = bool(g.user["must_change_password"])
        error = None
        if request.method == "POST":
            new = request.form.get("new", "")
            try:
                if pending and new != request.form.get("confirm", ""):
                    raise svc.RuleError("A confirmação deve ser igual à nova senha.")
                svc.change_password(
                    app.config["DATABASE"], g.user["id"], request.form.get("old", ""), new
                )
            except svc.RuleError as exc:
                error = str(exc)
            else:
                session.clear()
                flash("Senha alterada. Entre novamente.", "success")
                return redirect(url_for("login"))
        return render_template("account.html", pending=pending, error=error), 400 if error else 200

    @app.get("/auditoria")
    def audit():
        require("admin")
        rows = q(
            "SELECT e.*,u.name FROM events e LEFT JOIN users u ON u.id=e.user_id ORDER BY e.id "
            "DESC LIMIT 200"
        )
        issues = db.reconcile(app.config["DATABASE"])
        return render_template("audit.html", rows=rows, issues=issues)

    @app.get("/exportar/<dataset>.csv")
    def export(dataset):
        if dataset == "estoque":
            sql, values = stock_query()
            rows = q(
                "SELECT p.sku,p.brand,p.manufacturer_code,p.unit,l.code AS location,"
                "COALESCE(b.quantity,0) AS quantity" + sql + " ORDER BY p.sku,l.code",
                values,
            )
            fields = ["sku", "brand", "manufacturer_code", "unit", "location", "quantity"]
        elif dataset == "historico":
            sql, values = history_query()
            rows = q(
                "SELECT e.operation_id,o.created_at,o.kind,e.sku,e.location,e.before_qty,"
                "e.delta,e.after_qty,u.name,o.reason" + sql + " ORDER BY e.id DESC",
                values,
            )
            fields = [
                "operation_id",
                "created_at",
                "kind",
                "sku",
                "location",
                "before_qty",
                "delta",
                "after_qty",
                "name",
                "reason",
            ]
        else:
            abort(404)
        stream = io.StringIO(newline="")
        stream.write("\ufeff")
        writer = csv.writer(stream, delimiter=";")
        writer.writerow(fields)
        for row in rows:
            cells = []
            for field in fields:
                value = row[field]
                if isinstance(value, str) and value.lstrip().startswith(
                    ("=", "+", "-", "@", "\t", "\r", "\n")
                ):
                    value = "'" + value
                cells.append(value)
            writer.writerow(cells)
        return Response(
            stream.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": f'attachment; filename="gpslogistic-{dataset}.csv"'},
        )

    return app
