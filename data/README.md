# Catálogo e dados de demonstração

`catalogo.json` contém 400 modelos de RAM, SSD e HD, separados por SKU interno e código do fabricante. Cada produto inclui fonte oficial e informação de conferência. A data registrada na preparação do catálogo é **23 de novembro de 2026**.

| Marca | Código interno | Modelos |
|---|---|---:|
| Corsair | COR | 176 |
| Kingston | KIN | 90 |
| Samsung | SAM | 54 |
| Seagate | SEA | 40 |
| Western Digital | WDC | 40 |

O arquivo registra 295 URLs oficiais distintas. Código e capacidade foram conferidos durante a preparação do catálogo; características adicionais só foram incluídas quando extraídas das fontes. A aplicação não consulta a internet ao importar nem confirma a validade comercial atual desses modelos.

Há 98 modelos de kits de RAM. O campo `modulos_por_unidade` documenta o conteúdo de cada kit, enquanto o saldo conta kits fechados. Produtos avulsos contam uma unidade comercial por item.

## Dados simulados

MemoUniverse, locações e quantidades são fictícios. O total inicial é 8.000 unidades comerciais em 400 posições. A distribuição atende ao cenário de demonstração; não provém de uma empresa ou levantamento real. Capacidade física de prateleiras, demanda, custo, preço, fornecedores e números de série não foram dimensionados.

## Importação

`manage.py init` importa produtos, áreas, marcas e locações, e cria uma operação de carga inicial com 400 lançamentos. Todos partem de saldo anterior zero. O arquivo JSON permanece como dado inicial, independente do banco mutável da aplicação.

Novos produtos cadastrados pela interface não ganham automaticamente a indicação de fonte conferida. São identificados como cadastros manuais não conferidos. Os registros fictícios usados nos testes ficam separados do catálogo.

## Uso das marcas

Os nomes identificam os produtos usados como exemplo. Não há patrocínio, vínculo com fabricantes nem uso de seus logotipos ou fotografias. As fontes ficam vinculadas aos registros. A preparação deste catálogo não constitui autorização de marca, certificação comercial nem verificação de disponibilidade para compra.
