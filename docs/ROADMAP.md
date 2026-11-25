# Roadmap

Tópicos do repositório propostos para publicação: `flask`, `inventory`, `sqlite`, `wms` e `unittest`.

O quadro **GPSlogistic Roadmap** pode acompanhar as Issues abaixo nas colunas **A fazer**, **Em andamento**, **Em revisão** e **Concluído**. Os registros desta página estão prontos para importar quando houver um repositório conectado.

| Issue | Critério de aceite |
|---|---|
| Pedidos e reservas | Exibir saldo físico, reservado e disponível. Cancelar pedido libera reserva na mesma transação. |
| Conferência da expedição | Confirmar SKU e quantidade e gravar baixa vinculada ao pedido. |
| Campanhas de inventário | Abrir contagem por área, pedir segunda conferência e manter histórico por campanha. |
| PostgreSQL como alternativa | Preservar atomicidade, idempotência, auditoria e invariantes em testes de ambos os bancos. |
| Hospedagem do servidor Flask | Configurar HTTPS, volume persistente, backups e recuperação da conta. |

A prévia estática tem um [workflow próprio](../.github/workflows/demo.yml). Depois do primeiro deploy, adicione o endereço verificado ao topo do README. A tag Git `v1.0.0` pode ser usada como base da release no GitHub.
