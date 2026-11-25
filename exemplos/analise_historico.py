"""Análise do histórico exportado pelo GPSlogistic (Histórico > Exportar CSV).

Uso:
    python exemplos/analise_historico.py gpslogistic-historico.csv
    python exemplos/analise_historico.py gpslogistic-historico.csv --exportar-json resumo.json
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

REQUIRED_COLUMNS = {"kind", "sku", "delta", "name"}


def analyze_csv(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Arquivo não encontrado: {path}")

    saidas_por_sku: Counter[str] = Counter()
    entradas_por_sku: Counter[str] = Counter()
    operacoes_por_usuario: Counter[str] = Counter()
    operacoes_por_tipo: Counter[str] = Counter()
    total_linhas = 0

    with path.open(encoding="utf-8-sig", newline="") as arquivo:
        reader = csv.DictReader(arquivo, delimiter=";")
        fields = set(reader.fieldnames or ())
        missing = REQUIRED_COLUMNS - fields
        if missing:
            cols = ", ".join(sorted(missing))
            raise ValueError(f"CSV inválido; colunas obrigatórias ausentes: {cols}")

        for linha in reader:
            total_linhas += 1
            kind = (linha.get("kind") or "").strip()
            sku = (linha.get("sku") or "").strip()
            name = (linha.get("name") or "Sem usuário").strip()
            delta = int(linha.get("delta") or 0)

            operacoes_por_usuario[name] += 1
            operacoes_por_tipo[kind] += 1
            if kind == "out":
                saidas_por_sku[sku] += abs(delta)
            elif kind == "in":
                entradas_por_sku[sku] += max(0, delta)

    return {
        "total_lancamentos": total_linhas,
        "por_tipo": dict(operacoes_por_tipo.most_common()),
        "top_saidas_sku": dict(saidas_por_sku.most_common(10)),
        "top_entradas_sku": dict(entradas_por_sku.most_common(10)),
        "por_usuario": dict(operacoes_por_usuario.most_common()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("arquivo", type=Path, help="Caminho para o CSV exportado do histórico.")
    parser.add_argument(
        "--exportar-json",
        type=Path,
        default=None,
        help="Caminho opcional para salvar o resumo em JSON.",
    )
    args = parser.parse_args()
    try:
        summary = analyze_csv(args.arquivo)
    except (FileNotFoundError, ValueError, OSError) as exc:
        parser.exit(1, f"Erro ao processar CSV: {exc}\n")

    print(f"Lançamentos analisados: {summary['total_lancamentos']}")
    print("\nMovimentações por tipo:")
    for tipo, total in summary["por_tipo"].items():
        print(f"  {tipo}: {total}")
    print("\nTop 10 SKUs com mais saídas (unidades):")
    for sku, total in summary["top_saidas_sku"].items():
        print(f"  {sku}: {total}")
    print("\nLançamentos por usuário:")
    for nome, total in summary["por_usuario"].items():
        print(f"  {nome}: {total}")

    if args.exportar_json is not None:
        args.exportar_json.parent.mkdir(parents=True, exist_ok=True)
        args.exportar_json.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"\nResumo JSON salvo em: {args.exportar_json}")


if __name__ == "__main__":
    main()
