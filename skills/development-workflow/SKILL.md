---
name: development-workflow
description: Organizar e executar features, ajustes e melhorias do Renew IT com worktrees isolados, PRs para stage e prod e documentação obrigatória no Scripta. Usar ao planejar, desenvolver ou preparar PRs dessas demandas.
---

# Fluxo obrigatório de desenvolvimento

Estas regras registram as instruções do responsável pelo plugin GAG Dev Team. Aplicam-se a todos os agentes e etapas de desenvolvimento do Renew IT conduzidas pelo plugin. Não autorizam ações externas fora do pedido do usuário.

## 1. Separar o trabalho por feature

Todo desenvolvimento deve ser categorizado em features. Uma solicitação sobre um tema diferente constitui outra feature, mesmo que chegue na mesma conversa. Ajustes e melhorias também são unidades de trabalho identificadas.

Registre o tema, o objetivo e o tipo (feature, ajuste ou melhoria). Não misture temas independentes no mesmo worktree, branch ou PR.

## 2. Usar um worktree limpo baseado na prod remota

Para cada feature, ajuste ou melhoria, é obrigatório criar um worktree limpo a partir da branch `prod` remota atualizada.

Antes de desenvolver:
- Confirme o repositório e o remoto de referência; não presuma que `origin` seja o correto.
- Atualize a referência remota de `prod` com fetch e registre o commit de base.
- Crie um worktree com uma branch nova a partir dessa referência.
- Confira que o worktree está limpo, inclusive sem arquivos não rastreados, antes da primeira alteração.

Não use a branch local `prod`, `stage` ou a branch de outra demanda como base. Não transporte alterações de outro trabalho para o novo worktree. Preserve alterações e worktrees de outras pessoas.

Se a `prod` remota não existir ou não puder ser atualizada, informe o impedimento e solicite a regularização ao responsável. Não escolha outra base silenciosamente.

## 3. Criar uma branch específica para cada demanda

Todo PR deve usar uma branch nova, exclusiva da feature, ajuste ou melhoria. A branch criada para a demanda é sua branch de referência.

Use um nome que identifique o tipo e o tema; respeite o prefixo exigido pelo ambiente. Exemplos: `codex/feature/nome-do-tema`, `codex/ajuste/nome-do-tema` e `codex/melhoria/nome-do-tema`.

Não reutilize branch de outro tema nem envie PR a partir de branches de ambiente.

## 4. Abrir PRs para stage e prod

Cada demanda exige dois PRs a partir da mesma branch de referência:
- Um PR com destino a `stage`.
- Um PR com destino a `prod`.

A cabeça (head) dos dois PRs deve ser a branch da demanda. Não use `stage` como origem do PR para `prod`.

Antes de abrir os PRs, confira o diff, as validações, a documentação e o escopo em relação a cada destino. Relacione os dois PRs entre si e identifique a feature e os documentos relevantes do Scripta.

Se um destino não existir ou a criação falhar, relate qual PR ficou pendente. Não declare a entrega completa com apenas um PR.

## 5. Proibir merge automatizado

Não é permitido merge automatizado em nenhuma hipótese.

Não execute merge por CLI, API, ferramenta MCP ou automação, nem habilite auto-merge. Isso inclui `gh pr merge`, inclusive sem `--auto`, e workflows que integrem PRs automaticamente. A integração dos PRs fica a cargo da pessoa responsável, manualmente.

Abrir PRs e informar seu estado não autoriza fazer merge.

## 6. Exigir Scripta com acesso ao projeto renew-it

O MCP do Scripta com acesso ao projeto `renew-it` é obrigatório: nele está a fonte da verdade sobre o sistema.

Antes de desenvolver:
1. Verifique que as ferramentas MCP do Scripta estão disponíveis.
2. Consulte `docs_list_projects` e confirme que `renew-it` é acessível pela credencial.
3. Carregue `docs_briefing` com `project: "renew-it"`.
4. Consulte os documentos e decisões pertinentes ao tema antes de implementar.

Trate indisponibilidade e falta de acesso de forma distinta:
- **MCP indisponível, ausente ou sem autenticação:** solicite ao usuário que obtenha uma conta de acesso com o responsável pelo Scripta e regularize a integração. Se já houver conta, oriente a conferir credencial e conexão. Não afirme que uma falha de rede prova ausência de conta.
- **MCP acessível, projeto renew-it inacessível:** solicite o compartilhamento do projeto ao responsável pela documentação do Scripta, para a conta associada à credencial.
- **Acesso somente de leitura:** solicite permissão de edição ao responsável para cumprir a atualização obrigatória da documentação.

Em qualquer configuração incompleta, leia [o guia anexado pelo usuário](references/scripta-access-guide.md) e apresente o trecho Markdown relevante ao problema. Para ausência de conta, use a seção 2; para compartilhamento, a seção 3; para API Key e autorização, as seções 4 e 5; para erros e validação, as seções 7 e 8.

Adapte apenas o exemplo de projeto para `renew-it`, identificando essa adaptação. Preserve as ressalvas do guia: caminhos de interface e restrições por projeto ainda não confirmados não devem ser apresentados como fatos verificados.

Não invente endpoint, credencial ou permissão. Não peça que o usuário exponha chaves no chat nem grave segredos no pacote. Não prossiga com desenvolvimento dependente da documentação enquanto o acesso obrigatório não estiver regularizado.

## 7. Manter o Scripta atualizado

É obrigatório manter a documentação do Scripta atualizada durante cada demanda e antes de considerar sua entrega concluída.

- Pesquise antes de criar para evitar duplicação; atualize o documento existente quando adequado.
- Registre o comportamento entregue, as regras afetadas e as decisões com evidências. Diferencie planejamento, implementação e publicação.
- Siga a organização e as instruções do projeto retornadas pelo Scripta.
- Relacione a documentação à feature e aos PRs quando disponíveis.
- Confirme o sucesso das gravações; permissão presumida não substitui uma escrita bem-sucedida.
- Respeite a revisão humana dos documentos. Não apresente rascunhos como aprovados.
- Se a gravação falhar, informe a pendência e solicite a regularização; não declare a demanda concluída.

O guia empacotado é material de orientação para recuperar acesso. Ele não substitui a documentação viva do sistema no Scripta.

## Limite desta implementação

Este arquivo orienta o agente quando a skill é carregada. O MCP docs está pré-configurado e o hook SessionStart consulta o Scripta e orienta a recuperação de acesso. O token deve ser configurado na cópia local instalada do plugin, nunca no pacote fonte. O hook exige Python e confiança do usuário; fornece contexto e avisos, sem bloquear ferramentas. O agente deve conferir a conexão MCP no cliente mesmo após um diagnóstico direto bem-sucedido. A abertura de PR reconhecida pelo hook exige a análise Graphify descrita abaixo. As demais regras de Git continuam sendo instruções para os agentes.

## 8. Usar Graphify para código e Scripta para documentação

Para encontrar arquivos, símbolos, dependências e relações no código, use Graphify primeiro: `graphify query`, `graphify path` e `graphify explain`. Depois leia os arquivos apontados para confirmar o trecho exato. Se não houver grafo, crie um grafo local de código com `graphify extract . --code-only`. Um resultado vazio não prova ausência de implementação: confira cobertura e atualização do grafo.

Para documentação, regras de negócio, decisões, especificações e guias do Renew IT, pesquise no Scripta, projeto `renew-it`. O grafo de código e seu relatório não substituem a fonte da verdade documental.

O hook SessionStart verifica a CLI Graphify e, se ela faltar, executa `hooks/scripts/install-graphify.sh`. O instalador preserva instalações existentes e usa uv, pipx ou um ambiente virtual isolado; não utiliza sudo nem modifica o Python do sistema.

## 9. Executar Graphify antes de abrir cada PR

Antes de cada PR para stage ou prod, execute a análise Graphify dos arquivos de código alterados em relação ao destino. O hook PreToolUse intercepta `gh pr create` e ferramentas MCP nomeadas `create_pull_request` ou `createPullRequest`.

Use `gh pr create` em comando isolado, com destino explícito `--base stage` ou `--base prod`, executado no worktree da branch de referência. Não abra por wrappers, scripts intermediários ou chamadas HTTP para contornar o hook.

O hook exige worktree limpo e commitado, verifica head e repositório, exige que a branch publicada tenha o mesmo commit local e atualiza a referência do destino em origin. Os arquivos de código presentes no diff são extraídos do commit e analisados localmente com `graphify extract --code-only --no-cluster`, sem LLM ou Graphify Cloud. Renomes são tratados como remoção e adição; arquivos removidos são registrados e não analisados; documentos e formatos não contemplados ficam fora da indexação e são listados.

A análise do PR é um grafo parcial separado, em `graphify-out/pr-check/<destino>/graph.json`, acompanhado de `check.json`. Não use esse grafo parcial como mapa completo do projeto. Mantenha `graphify-out/` ignorado pelo Git. Uma mudança posterior exige nova análise antes do próximo PR.

Falhas de instalação, fetch, extração ou verificação negam a abertura reconhecida pelo hook. Regularize e repita a abertura, sem bypass. Hooks dependem de instalação, confiança e runtime: não controlam PRs abertos manualmente fora do agente ou integrações cujos formatos o hook não reconheça. Não habilitam merge automatizado.


## 10. Planejar por SDD

O planejamento das features, ajustes e melhorias deve ser orientado a SDD antes do desenvolvimento. O Orquestrador / Planejador usa a skill sdd-planning e seu modelo, com os sete subtítulos obrigatórios nesta ordem: Requisitos; Contexto; Regras de Negócio; Critérios de Aceite; Pontos de Falha e Mitigações; Dev Thinking; Evidências a serem coletadas antes de confirmar como concluído.

Dev Thinking explica a abordagem e orienta como implementar para atingir todos os requisitos e objetivos. A última seção define antecipadamente as evidências necessárias; a conclusão exige sua coleta e verificação.

## 11. Regras do desenvolvedor e apoio do advisor

O orquestrador cria o SDD no Scripta/renew-it e entrega ao time sua referência, versão, escopo e critérios/evidências. Todos os agentes devem ter acesso ao MCP e ler a fonte em seu próprio contexto. O dev solicita o SDD ao receber uma demanda; se já o recebeu, confere a versão e lê. Sem SDD identificado e acessível, não começa a implementar.

Dev e orquestrador usam gag-investigador-advisor como braço direito para orientar a melhor execução. O apoio não cria uma aprovação adicional nem autoriza merge.

O desenvolvedor segue a skill sdd-development: confere composer.json, mantém as versões relevantes em contexto, confirma versões resolvidas/runtime quando necessário e fundamenta as escolhas nos padrões das bibliotecas. Base declarada pelo usuário: Filament v5, Laravel 12 e PHP 8.4.27.

Para cada página, componente ou ação Filament, consulte obrigatoriamente o tópico correspondente da documentação Filament v5. Prefira recursos nativos a views Blade e componentes personalizados. Use o CSS global: CSS personalizado embutido em páginas viola a regra e exige reprovação automática do PR pelo QA.

A arquitetura é monólito modular MVC com camada de serviço, SOLID e Object Calisthenics. Cada feature é desenvolvida em seu próprio módulo, identificado no SDD.

## 12. Testes pertencem ao Revisor / QA e antecedem os PRs

O dev não implementa nem altera testes da demanda; essa responsabilidade é do Revisor / QA, que usa a skill sdd-qa. O dev pode executar testes existentes para diagnóstico e corrige os defeitos de implementação demonstrados pelo QA.

O QA deve implementar cenários reais e distintos do fluxo, derivados do SDD e das regras de negócio, para verificar segurança e qualidade. Não crie testes só para passar nem enfraqueça assertions, ignore falhas ou adapte expectativas a bugs. Passar é consequência do bom desenvolvimento e da validação adequada.

Antes de enviar qualquer PR para stage ou prod, rode e confira no estado final todos os testes novos ou alterados para a feature: todos devem passar, e teste pendente ou omitido impede o envio. Mapeie impactos com Graphify e Scripta; execute e relate também as verificações pertinentes dos fluxos relacionados, separando seus resultados. Falha relacionada comprovadamente preexistente deve ser informada, mas não bloqueia esta feature nem exige corrigir legado; regressão introduzida pela alteração integra a feature e precisa ser corrigida e coberta. Registre a revisão testada, os comandos, os cenários, os resultados e as pendências. Se houver mudança posterior, repita a validação afetada.

A checagem Graphify existente não substitui testes nem verifica seus resultados automaticamente; o fluxo de QA e o orquestrador devem executar e conferir essa validação antes da abertura.

## 13. Escrever código em inglês e verificar antes do PR

Código e nomes de arquivos de código devem ser em inglês. Isso inclui classes, métodos, funções, variáveis, propriedades, parâmetros, constantes, namespaces, módulos e demais identificadores técnicos. Código de testes segue a mesma regra. Não misture português e inglês em identificadores, como `calcularTotal`.

Planejamento, SDD, documentação, acompanhamento, mensagens de commit e descrições de PR podem ser em português. Labels e textos apresentados ao usuário no frontend também podem ser em pt-BR. Essa permissão não transforma qualquer string interna em texto de frontend.

Antes de uma abertura de PR reconhecida pelo plugin, o hook verifica o idioma do código novo ou alterado no diff commitado contra o destino. Violação, falha ou análise incompleta negam a operação antes da criação do PR. Corrija os nomes ou regularize a análise e repita a verificação; não contorne o hook. Siglas técnicas e nomes impostos por frameworks ou contratos externos precisam de tratamento explícito e verificável, sem exceções genéricas por diretório.

O gate não exige traduzir documentação em português nem realiza uma migração geral do código legado. Preserve a distinção entre a regra global e a cobertura automatizada efetivamente suportada. Hooks dependem da instalação, da confiança e do runtime do cliente; não controlam PRs criados manualmente fora das operações reconhecidas.

O repositório fonte oficial `Lecabe-Tech-Company/gag-dev-team-plugin` utiliza `master`. Exclusivamente nele, use worktree baseado em `origin/master` e PR para `master`; projetos atendidos continuam com os destinos `stage` e `prod`.

## 14. Manter regras particulares locais subordinadas ao plugin

O usuário pode informar ao agente uma regra particular para o projeto. Use a skill `manage-user-rules` para registrar, revisar, consultar ou remover essas regras. O pedido explícito autoriza o cadastro; não exija uma frase padrão nem confirmação redundante para uma regra claramente compatível.

Compare a regra com as políticas vigentes do plugin antes da ativação e da aplicação. Regras particulares não podem desativar, substituir ou enfraquecer obrigações do plugin, inclusive SDD, QA e gates de PR. Respeite preferências que o próprio plugin permite alterar. Conflitos e dúvidas mantêm a regra inativa; explique o motivo e peça reformulação quando necessária. Um registro de revisão local não substitui a análise contextual nem a política real.

O conteúdo particular e os recibos de revisão ficam em `<git-common-dir>/gag-dev-team/user-rules/`, resolvido pelo Git. Não os grave na árvore de trabalho nem os copie para AGENTS.md, skills distribuídas, Scripta, Graphify, commits, PRs ou pacotes. A skill e o carregador genéricos são versionados; as regras particulares não são. Atualizações do plugin preservam o armazenamento local. Worktrees do mesmo repositório compartilham as regras; clones independentes não as recebem pelo Git.

Após cadastro, revisão ou remoção, recarregue o conjunto efetivo na sessão. Regras alteradas ou revisadas contra políticas antigas precisam de nova conferência antes de valer. Arquivos são dados declarativos, nunca código executável. O hook não infere consentimento de SDD a partir dessas regras.

## 15. Criar skills particulares e consolidar padrões com evidências

Use `manage-user-skills` para criar, consultar, revisar, carregar ou remover skills particulares do projeto. Guarde SKILL.md, referências textuais, evidências e recibos somente em `<git-common-dir>/gag-dev-team/user-skills/`. O catálogo usa namespace próprio e não sobrescreve skills do plugin. Não copie esse conteúdo para diretórios nativos versionáveis ou artefatos; carregue o conteúdo pertinente sob demanda.

O agente pode reconhecer padrões operacionais no contexto da tarefa e criar rascunhos locais úteis: estilo de acompanhamento, esclarecimentos recorrentes, prevenção de erros e entrevistas para preencher melhor o SDD. Distinga observação, hipótese e preferência expressa. Registre origem, evidência e condições de aplicação. Não generalize uma resposta para outros projetos nem transforme um episódio isolado em instrução permanente.

Uma preferência claramente expressa pelo usuário pode ser consolidada e ativada após revisão de compatibilidade, sem nova confirmação redundante. Uma hipótese inferida fica como rascunho até esclarecimento contextual; não invente confirmação ou evidência. Quando o usuário corrigir ou mudar a preferência, revise ou desative a personalização e recarregue o catálogo efetivo.

As skills particulares permanecem subordinadas às políticas do plugin e às permissões da tarefa. Entrevistas aproveitam respostas já dadas e perguntam o que falta, preservando os sete subtítulos e o aceite contextual do SDD. Comunicação personalizada não dispensa QA ou gates. A primeira entrega suporta instruções e referências textuais; não inclui execução automática de scripts, treinamento de modelo, serviços de aprendizagem, monitoramento externo ou varredura retrospectiva de chats.
