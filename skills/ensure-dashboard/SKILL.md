---
name: ensure-dashboard
description: Verify or start the account-scoped local environment dashboard and communicate its actual URL.
---

# Dashboard local do usuário

Use ao iniciar o acompanhamento do ambiente ou quando o usuário pedir o dashboard. Execute no projeto ativo:

```sh
python .gag-dev-team/plugin/scripts/gag_dev_team.py environment dashboard --project .
```

O comando autentica a conta pela API `gh api user`, seleciona Node.js compatível, prepara dependências com lockfile, compila e verifica o serviço por bearer, projeto, conta, versão e hash das fontes. Reutiliza apenas uma instância correspondente. O app escuta exclusivamente em `127.0.0.1`. Nunca interrompa um processo alheio para liberar porta.

Enquanto o dashboard autenticado estiver saudável, inicia ou reutiliza um coletor privado que sincroniza, a cada minuto, somente fontes Codex explicitamente registradas. O coletor encerra quando o serviço deixa de responder com a mesma conta e projeto. O resultado inclui `collector.status`; `running` ou `starting` confirma o worker. Se o valor for `unavailable`, comunique que a atualização automática está indisponível. A sincronização também pode ser solicitada explicitamente por `track-token-usage`; leituras do dashboard nunca iniciam sincronização.

Comunique ao usuário a URL exata retornada, incluindo o fragmento de acesso. Esse fragmento é uma credencial local: não o copie para Git, Scripta, comentários de PR, logs ou histórico de erros. O dashboard é somente leitura. Se autenticação, runtime, build ou health falhar, informe a pendência real; não invente uma URL ou declare o serviço pronto. Não solicite nem registre tokens GitHub.

Os arquivos históricos são privados, separados por host e ID numérico GitHub. Não associe dados legados compartilhados a uma conta sem declaração explícita de titularidade. Não apague eventos, regras, skills ou registros de problemas; correções e desativações geram novos eventos.
