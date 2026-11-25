# Arquitetura e decisões

## Estrutura implementada

```text
GPSlogistic/
├── gps/
│   ├── app.py              # HTTP, sessão, CSRF, telas, consultas e CSV
│   ├── services.py         # regras, permissões e operações transacionais
│   ├── db.py               # esquema SQL, conexões, gatilhos e conciliação
│   ├── templates/          # páginas HTML renderizadas com Jinja
│   └── static/             # CSS, JavaScript e símbolo SVG próprio
├── data/catalogo.json      # catálogo e saldos iniciais simulados
├── tests/test_system.py    # testes automatizados isolados
├── docs/                   # documentação e diagramas
├── manage.py               # inicialização, verificação, backup, restauração
├── run.py                  # servidor local e log rotativo
├── iniciar.ps1             # preparação e execução no Windows
├── Iniciar GPSlogistic.cmd
├── requirements.txt        # dependências fixadas
└── .github/workflows/      # configuração de CI
```

`instance/` é criado localmente e ignorado pelo Git: contém banco, chave de sessão, logs e eventualmente o arquivo de acesso inicial. `.venv/` também é local e não acompanha a distribuição para GitHub.

## ADR-001 — Monólito em Flask

Uma aplicação contém HTTP, regras e acesso ao banco em módulos separados. Jinja gera o HTML no servidor; JavaScript melhora a prévia de movimentos. O servidor mantém a validação definitiva, independentemente de alterações no navegador. Não há API pública REST nesta versão; as rotas recebem formulários HTML.

A arquitetura combina interface web, regras e persistência em um único serviço.

## ADR-002 — SQLite local e SQL explícito

SQLite mantém os dados em arquivo e dispensa instalar um servidor de banco para a demonstração. O projeto usa `sqlite3` da biblioteca padrão, consultas parametrizadas e restrições SQL. Não usa ORM nem apresenta uma migração para PostgreSQL como pronta.

`BEGIN IMMEDIATE` serializa escritas antes de ler o saldo. O modo WAL permite leitores enquanto uma escrita é preparada. Há limite de espera de 15 segundos; indisponibilidade é apresentada como falha temporária. Esta estratégia favorece correção numa demonstração pequena, não alta capacidade de escrita concorrente.

O esquema tem versão 1 registrada em `metadata`. A inicialização acrescenta os campos de credenciais usados pelo primeiro acesso.

## ADR-003 — Livro de lançamentos e saldo materializado

`operations` representa uma ação do usuário. `entries` representa cada produto/locação alterado por essa ação. `balances` oferece consulta rápida do saldo atual.

Ao inserir um lançamento, um gatilho verifica se o saldo anterior coincide com o saldo existente. Outro gatilho atualiza `balances` com o saldo posterior. Tudo ocorre dentro da mesma transação. Restrições impedem quantidades negativas e inconsistência aritmética.

Gatilhos rejeitam atualização/exclusão em `entries`, `operations` e `events`. Não há uma rota de edição direta do saldo. A conciliação recompõe os saldos pela sequência de lançamentos e compara com a tabela atual.

Isso não é um sistema completo de event sourcing: os cadastros continuam em tabelas convencionais e nem todo estado pode ser reconstruído somente pelo livro de estoque. A auditoria também não é criptograficamente inviolável.

## ADR-004 — Estorno compensatório

Um estorno é outra operação, com `reversal_of` apontando para a original e protegido por unicidade. Seus lançamentos invertem as variações originais. Ele não reatribui um saldo antigo e não apaga entradas posteriores.

A prévia inclui os saldos correntes; o serviço compara esse retrato com o banco dentro da transação. Divergência exige nova conferência. Uma transferência estornada continua sendo indivisível: ambos os lados mudam ou nenhum muda.

## ADR-005 — Idempotência por formulário

`request_key` é único. `payload_hash` identifica o conteúdo normalizado da operação. Reenvios idênticos pelo mesmo usuário retornam o ID já criado. Reutilização com outro usuário ou conteúdo é recusada. O bloqueio de escrita e a restrição SQL também cobrem duas requisições simultâneas.

## ADR-006 — Segurança local

Senhas são armazenadas como hashes por Werkzeug (scrypt padrão da versão fixada). As contas criadas no painel usam uma senha temporária e definem uma credencial pessoal no primeiro acesso. A chave de sessão é aleatória e persiste em arquivo privado.

Há cookies HttpOnly/SameSite Strict, CSRF em todos os POSTs, validação de perfil nos serviços, templates com escape HTML, política CSP sem scripts externos e parâmetros SQL. O login bloqueia a conta informada por cinco minutos após cinco falhas. Os logs não recebem senhas. A limitação de login é local por nome de usuário; não substitui controles de borda ou proteção distribuída.

O cookie não usa `Secure` porque a execução local é HTTP. Sessões têm duração de até oito horas. Trocar a senha incrementa a versão de autenticação da conta e encerra as sessões anteriores. Desativar a conta impede acesso nas requisições seguintes.

## Dicionário de dados

| Tabela | Chave | Papel |
|---|---|---|
| users | id | Login, nome, hash de senha, perfil e situação |
| areas | code | Uma das oito áreas por categoria/tipo |
| brands | code | Código interno e nome da marca |
| products | sku | Modelo, fabricante, tipo, capacidade, unidade, fonte e situação |
| locations | code | Área e marca da posição |
| balances | sku + location | Quantidade atual por produto/endereço |
| operations | id | Tipo, usuário, data, motivo, idempotência e eventual estorno |
| entries | id | Operação, produto, endereço e evolução do saldo |
| events | id | Eventos administrativos e de acesso |
| login_limits | username | Falhas e prazo de bloqueio do login |
| metadata | key | Versão do esquema |

## Próximas decisões

A migração para PostgreSQL exigirá estratégia explícita de bloqueio por linha e testes concorrentes equivalentes. Publicação pública exigirá servidor WSGI apropriado, HTTPS, cookies Secure, segredos externos, revisão de sessão e política de backup. Nenhuma dessas configurações é considerada entregue nesta versão.

## Paginação e índices do histórico

A página carrega até 40 linhas em ordem decrescente de `entries.id` e busca uma linha adicional para descobrir se existe próxima página. O parâmetro `before` é exclusivo. Lançamentos novos entram no topo e não deslocam a página mais antiga. URLs antigas com `page` continuam aceitas.

```sql
EXPLAIN QUERY PLAN
SELECT e.id, o.kind
FROM entries e JOIN operations o ON o.id = e.operation_id
WHERE e.sku = 'RAM-177' AND e.id < 2000
ORDER BY e.id DESC LIMIT 41;
```

O plano local usou `SEARCH e USING INDEX entry_sku_id (sku=? AND id<?)` e `SEARCH o USING INTEGER PRIMARY KEY (rowid=?)`. Para filtro por locação, `entry_location_id` é coberto quando apenas o ID é selecionado. Para SKU e locação juntos já existe `entry_lookup`. A busca por texto com `LIKE '%termo%'` pode fazer varredura. Ordenação por ID após filtros de data pode usar árvore temporária conforme o plano escolhido.

## Benchmark local

Execute `python -m scripts.benchmark` para criar um banco temporário com 400 SKUs e 8.000 unidades. O script acumula entradas e saídas alternadas, mede 30 consultas por cenário com uma nova conexão SQLite por consulta e concilia o resultado. O volume abaixo exclui a carga inicial. Os tempos dependem da máquina.

| Movimentações adicionais | Estoque por SKU p50 / p95 | Histórico por SKU p50 / p95 | Histórico geral p50 / p95 |
|---:|---:|---:|---:|
| 0 | 1,856 / 1,978 ms | 1,882 / 2,011 ms | 1,901 / 2,024 ms |
| 1.000 | 1,848 / 2,643 ms | 1,910 / 2,010 ms | 1,915 / 2,072 ms |
| 10.000 | 1,819 / 1,921 ms | 1,917 / 1,972 ms | 1,903 / 1,947 ms |

O histórico retorna até 40 lançamentos por consulta. Os resultados medem as consultas locais, sem tempo de rede ou renderização.

Consulte o [diagrama entidade-relacionamento](ER.md) para localizar chaves e cardinalidades.
