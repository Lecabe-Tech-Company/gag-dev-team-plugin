---
name: record-agent-issue
description: Record sanitized agent problems, attempts, resolutions, and model provenance in immutable user-local history.
---

# Registro de problemas e tentativas

Use para registrar um problema concreto que o agente encontrou, sua tentativa e sua resolução. Não classifique uma pergunta normal de esclarecimento como erro. Separe falha de ambiente, ferramenta, requisito, processo e modelo; atribuição ao modelo exige evidência explícita.

Envie JSON UTF-8 por stdin para `gag-dev-team environment record --project .`. Nunca passe conteúdo privado nos argumentos. O CLI aceita `--event-id` estável para retries idempotentes; o mesmo ID com conteúdo diferente falha.

Campos do contrato: `event_type`, `session_id`, `agent_id`, `task_id`, `attempt_id`, `issue_id`, `causes`, `model`, `category`, `severity`, `attribution`, `summary`, `data`. Use identificadores estáveis para correlacionar eventos. Tipos operacionais: `session.started`, `session.ended`, `attempt.recorded`, `issue.opened`, `issue.resolved`, `issue.corrected`. Uma tentativa é uma operação relevante registrada, não uma estimativa de chamadas LLM.

`model` contém `provider`, `requested`, `observed`, `source`. `source` é `unknown`, `configured`, `declared` ou `observed`. Não transforme configuração ou declaração em observação. Ausência de dado permanece desconhecida. Não invente tokens, custos ou cobertura de chamadas. Os índices exibem apenas eventos registrados e tentativas distintas.

Faça resumo operacional mínimo e sanitizado. Não inclua prompts, conversas, stdout/stderr bruto, tokens, senhas, cookies, fragmentos de acesso do dashboard, conteúdo privado das regras/skills ou dados pessoais desnecessários. Referencie um código de falha e evidência curta revisada. O agente deve retirar segredos antes de enviar o evento. Se não for possível sanitizar com segurança, registre somente categoria e descrição genérica.

Resolução e correção usam novos eventos associados ao `issue_id`; nunca reescreva ou apague o registro original. Uma hipótese não confirmada usa atribuição desconhecida. `confirmed_model` exige causa demonstrada; falha de rede, runtime ou dependência usa atribuição de ambiente/ferramenta. Os hooks registram somente fatos observáveis suportados pelo host; complemente com CLI sem alegar captura universal.
