# Fluxogramas e UML

Os diagramas descrevem a versão 1 implementada. GitHub renderiza os blocos Mermaid ao abrir este Markdown. O diagrama de classes é um **modelo conceitual de domínio** correspondente às tabelas SQL; o código Python usa funções e registros SQLite, não classes ORM com esses nomes.

## Fluxograma de movimentação

```mermaid
flowchart TD
    A[Usuário autenticado abre formulário] --> B[Seleciona produto, locação, tipo e quantidade]
    B --> C[Informa motivo e confere a prévia]
    C --> D[Envia formulário com CSRF e chave única]
    D --> E{Sessão, CSRF e perfil válidos?}
    E -- Não --> X[Recusar sem alterar estoque]
    E -- Sim --> F[Iniciar transação BEGIN IMMEDIATE]
    F --> G{Chave já utilizada?}
    G -- Mesmo usuário e conteúdo --> H[Retornar operação existente]
    G -- Outro conteúdo ou usuário --> R[Desfazer transação e recusar]
    G -- Não --> I[Validar produto, endereço, quantidade e saldo]
    I --> J{Contagem física?}
    J -- Sim --> K[Exigir conferência e saldo da prévia ainda atual]
    J -- Não --> L{Transferência?}
    K --> M[Calcular variação e saldo resultante]
    L -- Sim --> N[Validar destino diferente e compatível]
    L -- Não --> M
    N --> M
    M --> O{Todas as regras atendidas?}
    O -- Não --> R
    O -- Sim --> P[Inserir operação e lançamentos]
    P --> Q[Gatilhos conferem anterior e atualizam saldos]
    Q --> S{Gravação completa?}
    S -- Não --> R
    S -- Sim --> T[Confirmar transação]
    T --> U[Exibir operação e histórico]
    H --> U
```

## Fluxograma de investigação e correção

```mermaid
flowchart TD
    A[Divergência percebida] --> B[Consultar SKU e locação no histórico]
    B --> C[Identificar operação e movimentos posteriores]
    C --> D{Erro em entrada, saída ou transferência?}
    D -- Sim --> E[Supervisor abre prévia do estorno]
    E --> F[Confere fisicamente e informa motivo]
    F --> G{Saldo não mudou e inversão é válida?}
    G -- Sim --> H[Registrar estorno vinculado]
    G -- Não --> I[Recusar e investigar novamente]
    D -- Não --> J[Realizar nova contagem física]
    J --> K[Registrar diferença com motivo e saldo esperado]
    H --> L[Original e correção permanecem no histórico]
    K --> L
```

## UML — classes do domínio

```mermaid
classDiagram
    class User {
      int id
      string username
      string password_hash
      string role
      bool active
    }
    class Brand {
      string code
      string name
    }
    class Area {
      string code
      string category
      string type
    }
    class Product {
      string sku
      string manufacturer_code
      string capacity
      string unit
      int modules
      string source
      bool active
      int minimum
    }
    class Location {
      string code
      bool active
    }
    class Balance {
      string sku
      string location
      int quantity
    }
    class Operation {
      int id
      string kind
      datetime created_at
      string reason
      string request_key
      string payload_hash
      int reversal_of
    }
    class Entry {
      int id
      int before_qty
      int delta
      int after_qty
    }
    class AuditEvent {
      int id
      datetime created_at
      string action
      string details
    }
    Brand "1" --> "0..*" Product : identifica
    Brand "1" --> "0..*" Location : organiza
    Area "1" --> "0..*" Location : contém
    Product "1" --> "0..*" Balance : possui
    Location "1" --> "0..*" Balance : armazena
    User "1" --> "0..*" Operation : registra
    Operation "1" *-- "1..*" Entry : agrupa
    Product "1" --> "0..*" Entry : movimentado
    Location "1" --> "0..*" Entry : recebe alteração
    Operation "0..1 original" <-- "0..1 estorno" Operation : reversal_of
    User "0..1" --> "0..*" AuditEvent : associado
```

A multiplicidade operação/lançamento representa uma transação concluída; uma inserção parcial é revertida. O banco permite registros técnicos transitórios dentro da transação, invisíveis como operação concluída para os demais clientes. Evento de login recusado pode não ter usuário associado.

## UML — sequência de uma transferência

```mermaid
sequenceDiagram
    actor U as Operador
    participant N as Navegador
    participant W as Flask app.py
    participant S as services.py
    participant D as SQLite e gatilhos
    U->>N: Informar origem, destino, SKU, quantidade e motivo
    N->>W: POST /movimentar com CSRF e chave
    W->>W: Verificar sessão e CSRF
    W->>S: operate(usuario, chave, transfer, dados)
    S->>D: BEGIN IMMEDIATE
    S->>D: Consultar usuário, chave, cadastros e saldos
    alt Reenvio idêntico
        D-->>S: Operação existente
        S-->>W: ID já registrado
    else Nova transferência válida
        S->>D: Inserir operação
        S->>D: Inserir lançamento negativo na origem
        D->>D: Validar anterior e atualizar saldo da origem
        S->>D: Inserir lançamento positivo no destino
        D->>D: Validar anterior e atualizar saldo do destino
        S->>D: COMMIT
        S-->>W: ID da operação
    else Falha em qualquer etapa
        S->>D: ROLLBACK
        S-->>W: Erro de regra ou integridade
    end
    W-->>N: Redirecionar ao detalhe ou apresentar erro
    N-->>U: Resultado da solicitação
```

## Componentes

```mermaid
flowchart LR
    U[Navegador local] --> H[Flask: rotas e sessão]
    H --> T[Templates Jinja e arquivos estáticos]
    H --> S[Serviços de negócio]
    S --> D[(SQLite: saldo e histórico)]
    H --> Q[Consultas e exportação]
    Q --> D
    H --> W[Análises somente leitura]
    W --> D
    C[manage.py] --> S
    C --> D
    C --> B[(Backup SQLite separado)]
    J[Catálogo JSON] --> C
    X[Testes unittest] --> H
    X --> S
```

## Mapa de casos de uso por perfil

Representação em fluxograma dos casos de uso; Mermaid não oferece a notação UML nativa de casos de uso neste documento.

```mermaid
flowchart LR
    O[Operador] --> C[Consultar e exportar estoque e histórico]
    O --> M[Registrar entrada, saída e transferência]
    O --> N[Consultar análises: ABC, movimentação e cobertura]
    S[Supervisor] --> O
    S --> R[Contar e estornar]
    S --> P[Cadastrar e inativar produtos e locações]
    A[Administrador] --> S
    A --> U[Gerenciar usuários]
    A --> V[Consultar auditoria e conciliação]
```

As setas entre perfis indicam acúmulo de permissões, não herança entre classes Python. Pedidos, reservas e expedição não aparecem como componentes existentes porque ainda são evolução planejada.
