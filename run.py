"""Servidor de demonstração local. Não disponibilizar diretamente na internet."""

import argparse
import logging
import threading
import webbrowser
from logging.handlers import RotatingFileHandler
from pathlib import Path

from gps.app import ROOT, create_app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5050)
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Use 0.0.0.0 somente dentro de contêiner, publicando a porta apenas em 127.0.0.1.",
    )
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()
    app = create_app()
    handler = RotatingFileHandler(
        Path(app.config["DATABASE"]).parent / "app.log",
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)
    if args.open:
        threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{args.port}")).start()
    app.run(host=args.host, port=args.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
