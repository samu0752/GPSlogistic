# Regras de negócio

## Identificação e contagem

- **Produto/SKU:** identificador interno estável, por exemplo RAM-177. Não muda ao transferir o produto.
- **Código do fabricante:** identifica o modelo comercial. A combinação marca + código é única.
- **Locação:** endereço composto por área, marca e posição, por exemplo A05-COR-047.
- **Saldo:** quantidade inteira de unidades comerciais de um SKU em uma locação.
- **Operação:** ação do usuário, com motivo, horário UTC e identificador de repetição.
- **Lançamento:** alteração de um saldo dentro de uma operação, com anterior, variação e posterior.

Um kit fechado conta como uma unidade. Não há fracionamento de kits. RAM avulsa é contada por módulo; SSDs e HDs por unidade. O total do painel soma essas unidades comerciais, e não capacidade em GB nem módulos físicos.

Uma locação aceita vários SKUs do mesmo tipo e marca. Um SKU pode existir em várias locações compatíveis. A capacidade física não é modelada. SKU e número de série não são equivalentes; esta versão não controla números de série.

## Operações e efeitos

| Operação | Entrada informada | Efeito |
|---|---|---|
| Carga inicial | Catálogo e saldos simulados | Uma operação com 400 lançamentos; anterior igual a zero |
| Entrada | Quantidade positiva | Soma ao saldo da locação |
| Saída | Quantidade positiva | Subtrai, sem permitir saldo negativo |
| Transferência | Quantidade positiva, origem e destino | Subtrai da origem e soma ao destino na mesma transação |
| Contagem física | Quantidade encontrada, podendo ser zero | Registra a diferença entre quantidade contada e saldo consultado |
| Estorno | Operação original e motivo | Aplica o inverso dos lançamentos originais ao saldo atual |

Quantidades aceitas: inteiros entre 1 e 1.000.000.000; contagens permitem zero. O saldo resultante também precisa permanecer entre zero e esse limite. Motivos precisam ter de 8 a 500 caracteres.

Origem e destino de uma transferência devem ser diferentes. Tipo e marca precisam coincidir com o produto. Não há mudança de SKU, capacidade, unidade ou código do fabricante de produtos existentes pela interface; uma mudança de identidade deve receber um novo cadastro.

## Histórico e recuperação

O sistema não possui ação de apagar saldo. É possível chegar a zero por saída ou contagem física, com histórico. `saldo posterior = saldo anterior + variação`.

Estornos são permitidos para entradas, saídas e transferências. Cada operação pode ser estornada uma vez. Não se estornam carga inicial, contagem ou outro estorno. Uma contagem incorreta é corrigida com nova contagem física justificada.

Exemplo: 36 kits, saída equivocada de 2 e saída correta de 3. O saldo chega a 31. Estornar a primeira saída soma 2 e leva a 33. Recolocar 36 apagaria o efeito da saída correta e não é a regra usada.

Antes de estornar, o supervisor vê o saldo atual e o previsto, informa um motivo e confirma a conferência física. Se o saldo mudar desde a prévia, a operação é recusada e precisa ser revisada. Se aplicar o inverso levar a saldo negativo, o estorno também é recusado. A pessoa deve investigar a divergência; o sistema não força um saldo inválido.

Contagens também comparam o saldo consultado com o saldo atual ao salvar. Isso impede que uma contagem digitada antes de outra movimentação sobrescreva silenciosamente essa movimentação. O sistema permite registrar contagem sem divergência (variação zero), documentando que a conferência ocorreu.

## Transações e repetição

Todas as alterações de estoque são executadas dentro de `BEGIN IMMEDIATE` no SQLite. A reserva de escrita acontece antes da leitura do saldo. Se qualquer parte falhar, todas as mudanças daquela transação são desfeitas, incluindo a operação e seus lançamentos.

Cada formulário de movimento recebe uma chave aleatória. A combinação da chave com usuário e conteúdo reconhece reenvios. Reenviar a mesma chave e os mesmos dados retorna a operação existente; reutilizá-la com dados diferentes é recusado. Uma nova tela gera outra chave: o sistema não tenta adivinhar se duas operações distintas são semanticamente duplicadas.

## Matriz de acesso

| Ação | Operador | Supervisor | Administrador |
|---|:---:|:---:|:---:|
| Consultar painel, estoque, histórico e locações | ✓ | ✓ | ✓ |
| Exportar CSV | ✓ | ✓ | ✓ |
| Entrada, saída e transferência | ✓ | ✓ | ✓ |
| Contagem e estorno | | ✓ | ✓ |
| Criar/inativar produto e locação | | ✓ | ✓ |
| Criar/desativar usuário | | | ✓ |
| Ver eventos administrativos e conciliação web | | | ✓ |
| Alterar a própria senha | ✓ | ✓ | ✓ |

As permissões são verificadas no servidor e nos serviços. O usuário responsável vem da sessão, não de um campo editável. Não há exclusão de usuário. Desativar um usuário bloqueia as próximas requisições; não desfaz operações já realizadas. O administrador não pode desativar a si mesmo.

Produtos e locações com saldo positivo não podem ser inativados. Cadastros inativos não recebem movimentações. A reativação mantém a identidade e o histórico.

## Indicadores

- Unidades comerciais: soma de `balances.quantity`.
- Produtos ativos: quantidade de cadastros de produtos com `active=1`.
- Locações ativas: quantidade de endereços com `active=1`.
- Operações registradas: quantidade de operações, excluindo a carga inicial. Transferência conta uma vez; estorno conta como nova operação.
- Saldo baixo: produto ativo com soma de saldos inferior a `minimum`, inicialmente 5. Não é previsão de demanda nem ponto de reposição calculado.
- Área: soma dos saldos de seus endereços. Posições cadastradas incluem endereços sem saldo.

## Datas, CSV e procedência

Horários são armazenados em UTC e exibidos/filtrados em UTC−03:00. O filtro de data final inclui o dia inteiro. CSVs usam UTF-8 com BOM e ponto e vírgula. Campos textuais que poderiam iniciar fórmulas de planilha recebem apóstrofo de proteção.

O catálogo inicial traz fontes oficiais e data de conferência. Novos cadastros manuais ficam marcados como não conferidos. A aplicação não verifica automaticamente novas especificações na internet.

## Acuracidade de inventário

`/inventario/acuracidade` resume lançamentos de contagem para supervisores. **Contagens exatas** é a proporção de diferenças zero. **Acuracidade por unidade** é 1 menos a soma das diferenças absolutas dividida pela soma do maior valor entre saldo no sistema e contagem física de cada lançamento. Se todas as observações forem zero, a acuracidade por unidade é 100%. O ranking lista os 30 maiores desvios acumulados por SKU e inclui recontagens como novas observações. O indicador agrega unidades comerciais conforme registradas.

## Importação de produtos

Em **Cadastros**, baixe o modelo de CSV. Use UTF-8, vírgula ou ponto e vírgula, até 256 KiB e 500 registros. Cada linha passa pelas mesmas regras do formulário. As linhas válidas são gravadas juntas com saldo zero, e erros de campos, duplicidade ou referências aparecem com o número da linha. Um arquivo estruturalmente inválido não é importado.
