"""Comandos de operação: inicialização, diagnóstico, backup e restauração segura."""

import argparse
import getpass
import json
import os
import secrets
import sqlite3
import sys
from pathlib import Path

from gps import db, services

ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / "instance" / "gpslogistic.db"


def backup(source, target):
    source, target = Path(source).resolve(), Path(target).resolve()
    if not source.is_file():
        raise services.RuleError("Banco de origem não encontrado.")
    target.parent.mkdir(parents=True, exist_ok=True)
    # Criação exclusiva: não sobrescreve banco nem backup anterior.
    with target.open("xb"):
        pass
    origin = sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True)
    destination = sqlite3.connect(target)
    try:
        origin.backup(destination)
    finally:
        origin.close()
        destination.close()
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description="Administração local do GPSlogistic")
    parser.add_argument("--database", type=Path, default=os.getenv("GPS_DATABASE") or DEFAULT_DB)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Importar catálogo e definir acesso inicial")
    init.add_argument(
        "--generate-password",
        action="store_true",
        help="Gerar e mostrar uma senha temporária uma única vez no terminal",
    )
    commands.add_parser("check", help="Conferir integridade e correspondência saldo/histórico")
    save = commands.add_parser(
        "backup", help="Criar backup consistente, inclusive com servidor ativo"
    )
    save.add_argument("target", type=Path)
    restore = commands.add_parser("restore", help="Restaurar backup para um NOVO arquivo de banco")
    restore.add_argument("source", type=Path)
    restore.add_argument("--to", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            db.initialize(args.database)
            if db.query(args.database, "SELECT 1 FROM users LIMIT 1", one=True):
                print("Banco já inicializado. Catálogo, senha e movimentações preservados.")
                return 0
            password = (
                secrets.token_urlsafe(18)
                if args.generate_password
                else getpass.getpass("Crie a senha de samuel (mínimo 12 caracteres): ")
            )
            if not args.generate_password and password != getpass.getpass("Repita a senha: "):
                raise services.RuleError("As senhas não coincidem.")
            catalog = json.loads((ROOT / "data" / "catalogo.json").read_text(encoding="utf-8-sig"))
            services.seed(args.database, catalog, password, temporary=args.generate_password)
            if args.generate_password:
                print("Acesso temporário. Troque a senha no primeiro login.")
                print("Usuário: samuel")
                print(f"Senha temporária: {password}", flush=True)
            print("Pronto: 400 produtos, 400 locações, 8.000 unidades simuladas e usuário samuel.")
        elif args.command == "check":
            if not args.database.exists():
                raise services.RuleError("Banco não inicializado.")
            issues = db.reconcile(args.database)
            if issues:
                print("\n".join(issues))
                return 1
            print("OK: banco íntegro, referências válidas e saldos conciliados com o histórico.")
        elif args.command == "backup":
            print("Backup criado:", backup(args.database, args.target))
        elif args.command == "restore":
            if not args.source.exists():
                raise services.RuleError("Backup não encontrado.")
            if db.reconcile(args.source):
                raise services.RuleError("Backup reprovado na conciliação. Restauração cancelada.")
            restored = backup(args.source, args.to)
            if db.reconcile(restored):
                raise services.RuleError("Falha na validação do banco restaurado.")
            print("Backup restaurado e validado em:", restored)
            print("O banco atual não foi substituído. Consulte docs/OPERACAO.md.")
        return 0
    except (services.RuleError, sqlite3.Error, OSError) as error:
        print("Não foi possível concluir:", error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
