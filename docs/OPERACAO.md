# Ambiente e persistência

O GPSlogistic utiliza Python 3.11 ou superior e SQLite. O ambiente padrão é local, com o servidor limitado a 127.0.0.1.

A pasta local instance reúne o banco, a chave de sessão e os registros técnicos. O catálogo JSON representa a carga inicial, enquanto usuários, saldos e movimentações são persistidos no banco. A inicialização preserva um banco já preenchido.

O diagnóstico verifica a integridade do SQLite e concilia os saldos com o livro de lançamentos. A API de backup do SQLite produz uma cópia consistente. A restauração gera um banco separado para conferência. A migração do primeiro acesso acrescenta campos às contas existentes e mantém suas credenciais.

## Coletor com câmera

O modo coletor pode ler produto, origem e destino com a câmera em navegadores que oferecem `BarcodeDetector` em contexto seguro. Use HTTPS ou a origem local em loopback. O navegador pede permissão quando você escolhe ler um campo. A imagem é processada no aparelho e o formulário só é enviado pelo operador. Digitação e leitores que simulam teclado continuam disponíveis.

## Docker Compose

```sh
docker compose build
docker compose run --rm gps python manage.py init --generate-password
docker compose up --wait
```

Anote a credencial temporária exibida no segundo comando. O serviço usa Gunicorn como usuário não-root, publica apenas em `127.0.0.1:5050` e guarda o SQLite e a chave de sessão no volume `gps_data`. A verificação `GET /health` fica disponível após a inicialização. Para instalação atrás de proxy HTTPS, ajuste os cookies e a configuração de proxy para o ambiente efetivo.

No Linux e no macOS, use `sh iniciar.sh` ou `make run`. No Windows, execute `Iniciar GPSlogistic.cmd` ou `iniciar.ps1`. O launcher mostra a credencial somente se tiver criado o banco.
