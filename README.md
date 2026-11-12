# GAG Dev Team Plugin

Estrutura inicial do plugin Codex da Lecabe Tech Company.

## Estrutura

| Caminho | Finalidade |
| --- | --- |
| `plugin.json` | Identidade do plugin e configurações específicas da OpenAI. |
| `mcp.json` | Conexões MCP distribuídas com o plugin. |
| `mcp/` | Implementações e recursos dos servidores MCP. |
| `hooks/hooks.json` | Eventos e comandos dos hooks. |
| `hooks/scripts/` | Scripts executados pelos hooks. |
| `agents/` | Perfis e procedimentos dos agentes do time. |
| `skills/` | Skills em `skills/<nome>/SKILL.md`. |
| `assets/` | Ícones e outros recursos do plugin. |

## Estado inicial

O pacote usa o manifesto portátil na raiz. O formato portátil descobre skills em `skills/`, carrega conexões de `mcp.json` e usa a configuração de hooks referenciada no manifesto.

A skill development-workflow registra as regras obrigatórias do time. O endpoint MCP docs está pré-configurado com um placeholder de token e o hook SessionStart verifica o Scripta. Os cinco perfis iniciais estão definidos em agents/ e disponíveis neste projeto em .codex/agents/. Os arquivos `.gitkeep` preservam os diretórios vazios no Git.

A pasta `agents/` contém os perfis fonte. A skill setup-team instala esses perfis em `.codex/agents/` no projeto de destino, onde o Codex os descobre nativamente.

## Desenvolvimento

1. Definir os papéis dos agentes e os fluxos de trabalho.
2. Adicionar cada skill em `skills/<nome>/SKILL.md`.
3. Implementar ou conectar os servidores e declarar as conexões em `mcp.json`.
4. Definir eventos em `hooks/hooks.json` e seus scripts em `hooks/scripts/`.
5. Cadastrar o pacote em um marketplace local, instalar e testar em uma nova conversa.

Hooks de plugins exigem revisão de confiança pelo usuário. Segundo a documentação consultada, plugins com lifecycle hooks devem ser instalados manualmente no Codex desktop e não são elegíveis para o diretório público.

## Referências oficiais

- [Empacotamento e hooks](https://developers.openai.com/plugins/build/plugins)
- [Criação de skills](https://developers.openai.com/plugins/build/skills)
- [Instalação e testes](https://developers.openai.com/plugins/deploy/connect-chatgpt)
- [Compatibilidade de agents e comandos](https://developers.openai.com/plugins/guides/submit-claude-plugin)

## Regras do time

A [skill de fluxo de desenvolvimento](skills/development-workflow/SKILL.md) registra as doze regras definidas pelo responsável: separação por feature; worktree limpo baseado na prod remota; branch exclusiva; dois PRs da mesma branch para stage e prod; proibição de merge automatizado; acesso obrigatório ao Scripta/renew-it; documentação sempre atualizada; Graphify para código e Scripta para documentação; análise Graphify antes de cada PR.

O [guia de acesso ao Scripta](skills/development-workflow/references/scripta-access-guide.md) reproduz o anexo fornecido pelo usuário e deve orientar a recuperação de acesso com o trecho pertinente.

O hook de Scripta fornece diagnóstico e orientações, sem bloquear ferramentas de desenvolvimento. O hook Graphify nega a abertura de PR reconhecida quando a análise não conclui; as demais regras de Git continuam sendo instruções para os agentes.

## Configuração do Scripta

O servidor `docs` em `mcp.json` aponta para `https://scripta-mcp.lecabe.com.br/mcp`. O transporte usa `streamable-http`, nome exigido pelo formato portátil para a conexão HTTP enviada pelo responsável.

O valor `Bearer ds_gere_um_token_acima` é apenas um placeholder. Após instalar o plugin localmente:

1. Obtenha uma conta e uma API Key do Scripta; solicite acesso Editor ao projeto `renew-it`.
2. Na cópia instalada do plugin (não no repositório fonte), configure `mcp.json` com `Authorization: Bearer SEU_TOKEN`, preservando a sintaxe JSON.
3. Reinicie o cliente para recarregar a conexão MCP.
4. Revise e confie no hook do plugin quando solicitado pelo Codex.
5. Confirme que as ferramentas do servidor docs estão disponíveis.

Não versione tokens nem os envie no chat. Headers do formato portátil são literais: escrever uma variável como `${SCRIPTA_API_KEY}` no header não configura expansão de ambiente. Uma atualização ou reinstalação pode substituir a cópia instalada; confira a configuração depois dela.

## Verificação no início da sessão

O hook `SessionStart` usa Python 3.9+ (biblioteca padrão), disponível como `python3` no Linux/macOS ou pelo launcher `py -3` no Windows. O handler tem limite de 35 segundos e as consultas usam timeout de até 6 segundos cada.

O script verifica a configuração e, quando há token, inicializa uma sessão MCP, consulta `docs_list_projects` e lê `docs_briefing` para `renew-it`. Diferencia token ausente/inválido, acesso recusado, projeto não compartilhado, papel sem edição confirmada, falha de rede e resposta incompatível.

Em caso de problema, mostra um aviso em português e fornece ao agente o trecho correspondente do guia anexado para ajudar o usuário. A consulta é somente de leitura; não altera documentos e não prova permissão efetiva de escrita. O diagnóstico direto também não comprova que a conexão MCP do cliente carregou: o agente ainda deve conferir suas ferramentas.

O hook orienta o agente a aguardar a regularização antes de desenvolver. Ele não implementa um bloqueio PreToolUse. Sua execução depende da instalação, da confiança no hook e do Python disponível no ambiente.

## Verificação local

Execute na raiz do projeto:

```sh
python3 -m unittest discover -s tests -v
python3 hooks/scripts/check_scripta.py
```

Os testes usam respostas simuladas, sem rede ou tokens reais. Com a configuração inicial, a execução manual do hook retorna a orientação de token ausente.

## Graphify: instalação e consultas

O [instalador Bash](hooks/scripts/install-graphify.sh) verifica o executável existente e instala o pacote `graphifyy` somente se faltar. Usa `uv tool install graphifyy`, `pipx install graphifyy` ou um venv privado em PLUGIN_DATA. Precisa de Python 3.10+ e, para uma instalação nova, acesso ao índice de pacotes. Não faz upgrade automático, não usa sudo e não executa `graphify codex install`, que alteraria as instruções do projeto.

O hook SessionStart chama esse fluxo automaticamente. Para executar manualmente:

```sh
bash hooks/scripts/install-graphify.sh
```

Para localizar código, consulte primeiro o grafo geral:

```sh
graphify extract . --code-only
graphify query "Onde está a implementação que procuro?"
graphify path "Origem" "Destino"
graphify explain "Conceito"
```

Use o Scripta/renew-it para documentação, regras e decisões. O Graphify não substitui essa fonte.

## Graphify antes de abrir PRs

O hook PreToolUse em [graphify_hook.py](hooks/scripts/graphify_hook.py) reconhece a abertura direta por `gh pr create` e ferramentas MCP com nome `create_pull_request` ou `createPullRequest`. Comandos de consulta de PR passam sem análise.

Abra cada PR em comando isolado, no worktree da feature, com destino explícito. Exemplo após commitar e publicar a branch:

```sh
gh pr create --base stage --head codex/feature/meu-tema --title "Meu tema" --body-file /caminho/descricao-pr.txt
gh pr create --base prod --head codex/feature/meu-tema --title "Meu tema" --body-file /caminho/descricao-pr.txt
```

O gate confere worktree limpo, branch atual, remoto origin, repositório do PR e coincidência do commit local com a branch publicada. Atualiza a referência remota do destino e calcula o diff a partir do ancestral comum. Extrai somente o conteúdo commitado dos arquivos alterados contemplados pela lista de extensões do script e roda `graphify extract --code-only --no-cluster` num corpus temporário. A passagem AST não usa LLM nem publica em Graphify Cloud.

O grafo parcial fica em `graphify-out/pr-check/<destino>/graph.json`; `check.json` registra os commits e as listas de arquivos enviados à análise, removidos ou deixados fora. Remoções não têm conteúdo para analisar. Documentos, arquivos sensíveis, symlinks, binários e extensões fora da lista não entram no corpus. O suporte efetivo de cada linguagem depende da versão do Graphify instalada. O grafo geral permanece separado.

Mantenha `graphify-out/` ignorado no repositório atendido. O plugin já o ignora neste repositório; não altera automaticamente o .gitignore de outros projetos. Se instalação, fetch ou análise falhar, o hook retorna uma decisão de negar a abertura reconhecida.

Os hooks precisam estar instalados, habilitados e confiados no Codex. O instalador .sh exige Bash; no Windows, use um ambiente Bash compatível, preferencialmente WSL. A validação foi feita no WSL, não no runtime nativo Windows. Não é um controle do servidor GitHub: PRs manuais fora do agente e formatos de ferramentas não reconhecidos ficam fora da cobertura. A regra do time continua exigindo a análise antes de qualquer abertura; não contorne o hook por wrappers ou APIs alternativas.

Fontes consultadas: [README oficial](https://github.com/Graphify-Labs/graphify/blob/v8/README.md), [CLI oficial](https://github.com/Graphify-Labs/graphify/blob/v8/graphify/cli.py) e [contrato de hooks do Codex](https://learn.chatgpt.com/docs/hooks). A CLI foi exercitada localmente com Graphify 0.9.11; o instalador usa a versão resolvida pelo gerenciador quando a ferramenta está ausente.

## Context7

O servidor remoto `context7` está declarado em `mcp.json` com transporte `streamable-http` e endpoint OAuth `https://mcp.context7.com/mcp/oauth`, seguindo o [pacote portátil oficial do Context7](https://github.com/upstash/context7/blob/master/plugins/agent-plugins/context7/mcp.json). Não há chave embutida. Após instalar/recarregar o plugin, conclua a autenticação OAuth se o cliente solicitar e confirme as ferramentas disponíveis.

Use Context7 para documentação técnica de bibliotecas e frameworks, conferindo a versão do projeto. Graphify continua destinado à localização de código; a documentação interna do Renew IT continua no Scripta.

## Identidades iniciais dos agentes

| Perfil | Responsabilidade inicial | Modelo | Raciocínio |
| --- | --- | --- | --- |
| Orquestrador / planejador (`gag-orquestrador-planejador`) | Planeja e gerencia a entrega de features do Renew IT. | `gpt-6.1-terra` | `low` |
| Desenvolvedor (`gag-desenvolvedor`) | Desenvolve as alterações autorizadas para a feature do Renew IT. | `gpt-6-luna` | `high` |
| Investigador / advisor (`gag-investigador-advisor`) | Recebe solicitações e investiga o contexto para apoiar o planejamento e a execução. | `gpt-6.1-sol` | `medium` |
| Revisor / QA (`gag-revisor-qa`) | Revisa alterações e verifica a qualidade e o atendimento ao pedido. | `gpt-6.1-sol` | `low` |
| Documentador (`gag-documentador`) | Consolida as alterações, consulta o Scripta e atualiza a documentação do Renew IT. | `gpt-6-luna` | `medium` |

Os perfis fonte ficam em `agents/gag-*.toml`. Cada um define nome, descrição, modelo, raciocínio e instruções de identidade. As regras detalhadas de cada papel serão fornecidas posteriormente pelo usuário. Não foram definidos novos poderes de aprovação nem um fluxo obrigatório de delegação.

Como o plugin portátil não registra automaticamente o diretório `agents/` como agentes nativos do Codex, a configuração inicial usa a [skill setup-team](skills/setup-team/SKILL.md), referenciada em `extensions.com.openai.onboardingSkill`. Ela instala os perfis no projeto desejado:

```sh
python3 /caminho/do/plugin/scripts/install-agents.py --project /caminho/absoluto/do/projeto
```

O instalador usa Python 3.10+, grava os TOMLs em `.codex/agents/` e recusa substituir perfis existentes com conteúdo diferente. Repetir com arquivos iguais é seguro. Os perfis já foram instalados neste repositório do plugin.

Reinicie a sessão do Codex para recarregar a configuração. Isso não inicia agentes, não altera o modelo desta conversa e não seleciona automaticamente o orquestrador como modelo principal. Peça o perfil desejado numa sessão compatível, por exemplo: "Use o agente gag-investigador-advisor para investigar esta solicitação." Os modelos e permissões efetivamente disponíveis dependem do cliente e da conta; os perfis não elevam permissões.

Referência: [agentes personalizados do Codex](https://learn.chatgpt.com/docs/agent-configuration/subagents).


## Planejamento orientado a SDD

O Orquestrador / Planejador usa a [skill sdd-planning](skills/sdd-planning/SKILL.md) e o [modelo de SDD](skills/sdd-planning/assets/sdd-template.md) antes do desenvolvimento. Todo SDD inclui estes sete subtítulos, na ordem:

1. Requisitos
2. Contexto
3. Regras de Negócio
4. Critérios de Aceite
5. Pontos de Falha e Mitigações
6. Dev Thinking
7. Evidências a serem coletadas antes de confirmar como concluído.

Dev Thinking orienta a abordagem de implementação para cumprir os requisitos e objetivos. As evidências são definidas no planejamento e precisam ser coletadas e verificadas antes de confirmar a conclusão. SDDs do sistema ficam no Scripta; o arquivo empacotado é somente o modelo reutilizável.

O perfil mantém GPT-6.1 Terra com raciocínio low. A cópia nativa neste projeto foi atualizada; outros projetos com perfis instalados anteriormente precisam receber a atualização explicitamente, pois o instalador preserva arquivos com conteúdo diferente.

## Regras do desenvolvedor e colaboração do time

O orquestrador cria e mantém o SDD no Scripta/renew-it e entrega ao time sua referência, versão, escopo e critérios/evidências. O dev solicita o SDD ao iniciar cada demanda; quando já informado, confere a versão e consulta a fonte. Todos os agentes verificam o próprio acesso ao MCP do Scripta. Os perfis herdam a conexão e as permissões do agente principal; não incluem credenciais individuais.

Dev e orquestrador usam o Investigador / Advisor como braço direito para orientar a execução com evidências. Esse apoio não atribui ao advisor poderes de aprovação ou merge.

A [skill sdd-development](skills/sdd-development/SKILL.md) define:
- Conferir composer.json e manter as versões relevantes no contexto, complementando com composer.lock e o runtime quando necessário.
- Usar Filament v5, Laravel 12 e PHP 8.4.27 como base declarada pelo usuário, sem apresentar essa declaração como detecção feita no repositório.
- Fundamentar a implementação nos padrões das bibliotecas utilizadas.
- Consultar o tópico da documentação Filament v5 antes de desenvolver qualquer página, componente ou ação, priorizando recursos nativos.
- Respeitar o CSS global do sistema. CSS personalizado embutido em páginas implica reprovação automática pelo QA.
- Adotar monólito modular MVC com serviços, SOLID e Object Calisthenics, com cada feature em seu próprio módulo.

A reprovação por CSS está configurada como obrigação do Revisor / QA, com evidências de arquivo/trecho; não foi criado um novo bloqueio no servidor GitHub ou detector estático de estilos. As outras regras de PR e merge continuam vigentes.


## Simplicidade e preparo antes da implementação

O dev identifica primeiro a etapa do SDD, requisitos, dependências e evidências e define uma abordagem simples ou pseudocódigo. Reaproveita o Dev Thinking quando suficiente e chama o advisor quando necessário para orientar a execução antes de codar.

A skill sdd-development exige considerar Big O de tempo e memória nos caminhos relevantes, juntamente com volume, consultas/N+1, I/O e carregamento de dados. Ganhos alegados precisam de evidência; otimização não deve comprometer correção e clareza.

Código deve ser funcional e legível: responsabilidades e nomes claros, guard clauses/early returns quando simplificarem o fluxo, e comentários explicativos para decisões e comportamentos não óbvios. Reduzir caracteres não é um objetivo isolado.

## Autoria e qualidade dos testes

O **Revisor / QA implementa e mantém os testes** da demanda; o desenvolvedor implementa e corrige o código da aplicação. O dev pode executar testes existentes para diagnóstico. A [skill sdd-qa](skills/sdd-qa/SKILL.md) orienta a cobertura de cenários reais a partir do SDD.

Os testes devem detectar defeitos e verificar segurança e qualidade: sucesso, falhas, limites, permissões, estados, efeitos e regressões aplicáveis ao fluxo. Não há quantidade fixa de cenários. Assertions enfraquecidas, expectativas adaptadas ao bug, mocks que eliminam o comportamento sob teste e testes escritos só para ficar verdes não atendem à regra.

Antes de enviar PRs para stage/prod, é obrigatório executar e conferir os testes da feature e dos fluxos relacionados sobre o estado final da branch. O QA justifica a seleção com base nos impactos, registra comandos, revisão e resultados e amplia a suíte quando não puder delimitar o impacto. Mudança posterior exige nova validação afetada.

Falhas e testes obrigatórios pendentes impedem o envio. O orquestrador confere essa evidência; o documentador consolida no Scripta. O hook Graphify continua realizando a análise de código: ele não executa nem atesta os testes automaticamente.
