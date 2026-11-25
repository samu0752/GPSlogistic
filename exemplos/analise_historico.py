"""Exemplo de análise do histórico exportado pelo sistema (Histórico > Exportar CSV).

Uso:  python exemplos/analise_historico.py gpslogistic-historico.csv
Usa só a biblioteca padrão. Mostra saídas por produto e por usuário.
"""

import csv
import sys
from collections import Counter


def main(caminho):
    saidas_por_sku, operacoes_por_usuario = Counter(), Counter()
    with open(caminho, encoding="utf-8-sig", newline="") as arquivo:
        for linha in csv.DictReader(arquivo, delimiter=";"):
            operacoes_por_usuario[linha["name"]] += 1
            if linha["kind"] == "out":
                saidas_por_sku[linha["sku"]] += -int(linha["delta"])
    print("Top 10 produtos com mais saídas (unidades):")
    for sku, total in saidas_por_sku.most_common(10):
        print(f"  {sku}: {total}")
    print("\nLançamentos por usuário:")
    for nome, total in operacoes_por_usuario.most_common():
        print(f"  {nome}: {total}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
