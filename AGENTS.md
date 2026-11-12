# Instruções do GAG Dev Team Plugin

## Fontes de consulta

- Para localizar código, símbolos, dependências e relações, use Graphify primeiro. Consulte o grafo e depois confirme os arquivos e linhas indicados. Se faltar grafo, gere-o localmente com `graphify extract . --code-only`.
- Para documentação, regras, decisões, especificações e guias do sistema Renew IT, pesquise no MCP do Scripta, projeto `renew-it`. Não use Graphify como substituto dessa documentação.
- Siga o fluxo do time em [skills/development-workflow/SKILL.md](skills/development-workflow/SKILL.md) nas demandas do Renew IT.
- Antes de abrir PRs por este agente, use `gh pr create` isolado, com destino stage/prod explícito e workdir no worktree da feature, permitindo executar o gate Graphify. Não contorne o hook por outras ferramentas ou wrappers.


- Para documentação técnica de bibliotecas e frameworks, use Context7 e confira a versão. A documentação interna do sistema continua no Scripta.
- Os cinco perfis do time estão em agents/ e suas cópias nativas em .codex/agents/. A skill setup-team instala os perfis em outros projetos. As responsabilidades detalhadas ainda serão definidas pelo usuário; não crie regras adicionais nem troque os modelos configurados silenciosamente.

- O planejamento do Orquestrador / Planejador é orientado a SDD. Use a skill [sdd-planning](skills/sdd-planning/SKILL.md) e preserve os sete subtítulos obrigatórios do modelo.

- O dev deve seguir a skill [sdd-development](skills/sdd-development/SKILL.md). O SDD fica no Scripta: o orquestrador entrega a referência e a versão ao time; o dev solicita quando faltar e todos os agentes confirmam o próprio acesso.
- Dev e orquestrador usam gag-investigador-advisor como braço direito orientador. Preserve as versões em contexto após conferir composer.json e as fontes complementares; a base declarada é Filament v5, Laravel 12 e PHP 8.4.27.
- Para cada página, componente ou ação Filament, consulte a documentação do tópico no Filament v5 e prefira recursos nativos. CSS personalizado embutido em páginas é proibido e exige reprovação do PR pelo QA; respeite o CSS global.
- Cada feature fica em seu próprio módulo, seguindo monólito modular MVC com serviços, SOLID e Object Calisthenics.

- O Revisor / QA implementa e mantém os testes da demanda, seguindo a skill [sdd-qa](skills/sdd-qa/SKILL.md). O dev não cria nem altera testes; ele implementa/corrige a aplicação e pode executar testes existentes.
- Testes devem cobrir cenários relevantes para segurança, qualidade e regressão, sem enfraquecer verificações para obter verde.
- Antes de enviar qualquer PR, execute os testes da feature e dos fluxos relacionados no estado final da branch e confira as evidências. Falhas ou validação obrigatória pendente impedem o envio.
