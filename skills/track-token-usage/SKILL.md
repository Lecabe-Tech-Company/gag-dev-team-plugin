---
name: track-token-usage
description: Track Codex token usage against an explicitly named work goal and verified agent threads.
---

# Token usage por objetivo

Use esta skill para vincular trabalho explícito a um objetivo de consumo e para consultar ou corrigir atribuições. A coleta abrange somente sessões que foram registradas pelo usuário ou pelo orquestrador para o objetivo ativo.

## Iniciar um objetivo

Antes de iniciar, confirme que a tarefa é um objetivo de trabalho identificável e que o host fornece o identificador estável da thread Codex atual. Use o nome conciso do objetivo sem copiar prompts, mensagens ou conteúdo de arquivos. Não invente thread ID, parent ID ou caminho de fonte. Se o host não fornecer esses dados, informe que a atribuição não está disponível para essa sessão.

No projeto ativo, envie um objeto JSON ao comando `goal-start`:

```sh
printf '%s' '{"goal_id":"goal-opaque-id","name":"Implementar relatório de consumo","thread_id":"<thread-id-verificada>","source_root":"<CODEX_HOME>/sessions"}' | python .gag-dev-team/plugin/scripts/gag_dev_team.py environment goal-start --project .
```

O comando cria um objetivo privado, registra a fonte raiz e vincula o orquestrador. O identificador pode ser omitido para que o comando gere um. O caminho de fonte deve resolver para a pasta `sessions` do `CODEX_HOME` configurado.

## Vincular subagentes e fontes

Vincule cada subagente observável ao objetivo antes de sincronizar seu uso. Informe `thread_id`, `parent_thread_id`, `agent_name` e `source_root` usando identificadores fornecidos pelo host. O coletor confere a ancestralidade no registro `session_meta`; uma alegação de pai incompatível não recebe uso. Uma mesma thread pode mudar de objetivo, mas somente respostas dentro do intervalo de vínculo serão atribuídas àquele objetivo.

```sh
printf '%s' '{"goal_id":"goal-opaque-id","thread_id":"<child-thread-id>","parent_thread_id":"<root-thread-id>","agent_name":"environment_frontend","source_root":"<CODEX_HOME>/sessions"}' | python .gag-dev-team/plugin/scripts/gag_dev_team.py environment agent-link --project .
```

`source-register` registra uma thread sem objetivo; ela não pode reclamar respostas não atribuídas de outro projeto. `usage-sync` sincroniza apenas fontes registradas. O serviço local inicia um coletor privado a cada minuto enquanto o dashboard autenticado estiver saudável. Ele para quando o dashboard encerra ou deixa de corresponder à conta e ao projeto. Leituras HTTP não sincronizam dados.

## Encerrar, consultar e corrigir

Ao concluir o objetivo, encerre-o com `goal-end`. O histórico continua privado e imutável. Para corrigir uma atribuição, use `usage-correct` com a thread, a resposta, o objetivo desejado (ou `null` para não atribuído) e um motivo breve. A correção gera um novo evento auditável.

O snapshot pode filtrar por `period`, `goal_id`, `agent_id` e `model`. Ele separa o consumo próprio do consolidado dos descendentes, usa somente `token_usage_record.usage` por resposta e mantém campos ausentes como desconhecidos. `turn_context.model` é modelo declarado pelo host; não prova qual modelo o provedor serviu.

Não registre ou reproduza prompts, respostas, conteúdo de ferramentas, logs completos, credenciais ou transcrições. Não some `turn_token_usage` nem `thread_token_usage`; são acumulados. Não estime custo nem transforme limites ou quotas em consumo. Fonte parcial, incompatível, interrompida ou indisponível deve permanecer claramente identificada.
