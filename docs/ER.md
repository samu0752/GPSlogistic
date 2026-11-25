# Modelo entidade-relacionamento

```mermaid
erDiagram
    AREAS ||--o{ LOCATIONS : organiza
    BRANDS ||--o{ LOCATIONS : identifica
    BRANDS ||--o{ PRODUCTS : fabrica
    PRODUCTS ||--o{ BALANCES : agrega
    LOCATIONS ||--o{ BALANCES : abriga
    PRODUCTS ||--o{ ENTRIES : movimenta
    LOCATIONS ||--o{ ENTRIES : recebe
    OPERATIONS ||--|{ ENTRIES : contém
    USERS ||--o{ OPERATIONS : executa
    USERS o|--o{ EVENTS : registra
    OPERATIONS o|--o| OPERATIONS : estorna
    USERS {
        int id PK
        text username UK
        text role
        int auth_version
    }
    PRODUCTS {
        text sku PK
        text brand FK
        text manufacturer_code
    }
    LOCATIONS {
        text code PK
        text area FK
        text brand FK
    }
    BALANCES {
        text sku PK,FK
        text location PK,FK
        int quantity
    }
    OPERATIONS {
        int id PK
        int user_id FK
        text request_key UK
        int reversal_of FK,UK
    }
    ENTRIES {
        int id PK
        int operation_id FK
        text sku FK
        text location FK
        int before_qty
        int delta
        int after_qty
    }
    EVENTS {
        int id PK
        int user_id FK
        text action
        text created_at
    }
```

O saldo é materializado por par SKU/locação. A mesma transação grava a operação e seus lançamentos. `schema_version`, `metadata` e os limitadores de login são tabelas de controle, sem chaves estrangeiras.
