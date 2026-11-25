# API REST

A API é somente leitura. Operadores, supervisores e administradores autenticados usam a sessão criada pelo formulário de login. Uma conta temporária precisa concluir a troca antes de consumir a API.

| Rota | Uso |
|---|---|
| `GET /api/v1/estoque` | Saldos por SKU e locação, com filtros da tela de estoque e paginação |
| `GET /api/v1/movimentacoes` | Lançamentos por SKU, locação, operação e período, com cursor exclusivo |
| `GET /api/openapi.yaml` | Especificação OpenAPI 3.1 |

Abra [openapi.yaml](openapi.yaml) no Swagger Editor ou importe em um cliente OpenAPI. Para testar com o navegador autenticado, abra outra aba na mesma origem. Exemplo em `http://127.0.0.1:5050/api/v1/movimentacoes?sku=RAM-177&limit=10`. Quando `next_before` vier preenchido, repita a consulta com o mesmo filtro e passe esse número em `before`.

A API omite o usuário e o motivo das movimentações.
