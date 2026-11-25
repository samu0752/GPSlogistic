# Segurança

| Controle | Comportamento |
|---|---|
| Perfis | A aplicação confere as permissões na interface e na camada de serviço |
| Primeiro acesso | A conta criada na interface precisa definir uma senha pessoal antes de acessar o estoque |
| Credenciais e sessões | Senhas são armazenadas como hashes. A troca de senha invalida sessões anteriores |
| Formulários | Token CSRF e limites de tamanho de requisição |
| Histórico de estoque | Gatilhos SQLite bloqueiam edição e exclusão de operações, lançamentos e eventos pela aplicação |
| Requisições repetidas | Chave de idempotência por operação e transações de escrita |
| Verificações do código | Ruff, Bandit e pip-audit nos fluxos do GitHub Actions |

O ambiente padrão é local. A proteção do arquivo do banco e da chave de sessão depende das permissões do sistema operacional. A auditoria registra eventos sem assinatura criptográfica.

## Senha inicial

`python manage.py init --generate-password` exibe a senha temporária uma única vez no terminal após gravar o hash. O primeiro login redireciona para **Minha conta** e bloqueia as funções de estoque e a API até a troca. Rode o comando em terminal privado. Uma nova execução preserva o banco e não exibe credenciais antigas. Instalações que ainda tiverem `ACESSO_LOCAL.txt` da versão anterior devem remover o arquivo com segurança e trocar aquela senha.

## Sessão e login

A sessão usa `HttpOnly`, `SameSite=Strict` e `Secure` quando `GPS_COOKIE_SECURE=1`. Em HTTPS a resposta inclui HSTS. CSP limita scripts, estilos e origens. `X-Frame-Options: DENY` e `X-Content-Type-Options: nosniff` também estão ativos.

O SQLite aplica 30 POSTs de login por endereço a cada minuto e bloqueia o login por 5 minutos após cinco falhas no mesmo identificador. Use `GPS_TRUST_PROXY=1` apenas atrás de um proxy confiável que controle os cabeçalhos encaminhados.

## Auditoria

A tela **Auditoria** lista sucessos, falhas, bloqueios e limitação do login, com o identificador normalizado quando válido. Senha, cookies e tokens ficam fora da trilha. O gatilho SQLite registra cada estorno com o autor, a data, o ID da correção e o ID da operação original, na mesma transação. Os gatilhos bloqueiam UPDATE, DELETE e a substituição de registros com REPLACE nas conexões da aplicação. A proteção contra edição por quem administra o arquivo do banco depende do controle do sistema operacional.
