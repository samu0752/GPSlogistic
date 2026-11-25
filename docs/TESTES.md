# Testes e validação

A suíte unittest usa bancos SQLite separados e inclui **37 testes automatizados**.

| Área | Cobertura |
|---|---|
| Estoque | Carga inicial, entradas, saídas, transferências, saldo insuficiente e contagem |
| Transações | Concorrência, idempotência e consistência dos saldos |
| Rastreabilidade | Estorno, integridade do histórico e conciliação |
| Acesso | Login, perfis, primeiro acesso e invalidação de sessão após troca de senha |
| Interface | Rotas, filtros e exportação CSV |
| Indicadores | Curva ABC, cobertura e contagem de operações com o mesmo horário |
| Recuperação | Backup e restauração em banco separado |

O GitHub Actions inclui uma matriz de testes em Python 3.11, 3.12 e 3.13.
