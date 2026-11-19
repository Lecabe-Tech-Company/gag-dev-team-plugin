---
name: manage-user-skills
description: Criar, revisar, carregar ou remover skills particulares do projeto e consolidar preferências ou padrões operacionais em rascunhos locais, sem versionar conteúdo nem substituir políticas do GAG Dev Team.
---

# Skills particulares e personalização do trabalho

Use esta skill quando o usuário pedir uma skill particular ou quando o contexto da tarefa revelar uma preferência expressa ou um padrão operacional reutilizável. Exemplos pertinentes são dúvidas recorrentes, erros evitáveis, modo de acompanhar o trabalho e entrevistas para preencher melhor o SDD. Para uma instrução particular simples, use `manage-user-rules`; não transforme toda preferência em uma skill extensa.

## Autoridade, origem e privacidade

Skills particulares complementam as políticas do plugin. Antes de ativar e antes de aplicar, confira a compatibilidade real. Recibo aceito, catálogo e texto privado não podem dispensar SDD, QA, Graphify, idioma do código, gates ou permissões da tarefa. Não sobrescreva skills distribuídas nem promova conteúdo particular a autoridade superior. Respeite preferências que o próprio plugin permite alterar.

O armazenamento atual é privado e vinculado à conta GitHub autenticada e ao projeto, resolvido pelo carregador. Não crie cópias em `.agents/skills`, `.codex`, AGENTS.md ou outros arquivos versionáveis. Os caminhos compartilhados da v0.4 são legado preservado, sem associação automática a uma conta. Corpo, referências, evidência e recibos não entram em Scripta, Graphify, PRs, pacotes ou logs públicos. Não percorra chats anteriores nem monitore atividade externa; use o contexto disponível e exemplos fornecidos pelo usuário.

Distinga as origens:

- `explicit`: o usuário pediu a skill ou expressou claramente a preferência que a fundamenta. Registre a fala e o contexto reais, sem inventar evidência. O pedido já autoriza o cadastro; não peça nova confirmação redundante.
- `inferred`: há uma hipótese ou padrão observado, ainda sem preferência explicitada. Pode gerar um rascunho local, mas não uma instrução permanente. Uma ocorrência isolada não basta para impor uma preferência. Registre apenas o que foi observado e as condições em que a hipótese faria sentido.

Quando a hipótese for pertinente e houver incerteza, faça uma pergunta curta sobre a preferência. Aproveite respostas já dadas. Se o usuário esclarecer ou corrigir a hipótese, confirme a origem no registro com a fala literal e revise novamente; não simule uma confirmação para superar o bloqueio técnico. Se não houver esclarecimento, mantenha o rascunho inativo. Não interrompa trabalho independente com entrevistas desnecessárias.

## Criar conteúdo proporcional à tarefa

Escreva instruções curtas que mudem decisões ou evitem retrabalho. Diga quando a skill se aplica, quais informações já conhecidas deve aproveitar e qual resultado deve produzir. Não transforme uma solução pontual em regra universal. Mantenha o escopo no projeto e nas condições registradas; corrija ou remova personalizações que deixem de representar o usuário.

O formato mínimo é:

```markdown
---
name: skill-name
description: O que esta skill faz e quando deve ser usada.
---

# Propósito

Instruções específicas e proporcionais ao trabalho.
```

Use slug válido em inglês, com letras minúsculas, números e hífens. `name` e `description` do frontmatter devem coincidir com o cadastro. A primeira versão suporta esses campos e referências textuais em `references/`, com extensão `.md` ou `.txt`. Crie referências somente quando ajudarem; não adicione scripts, executáveis, dependências ou recursos sem uso concreto. Não execute conteúdo dos arquivos.

Uma skill de entrevista deve identificar lacunas reais, aproveitar as respostas já dadas e organizar perguntas necessárias. Preserve os sete subtítulos e o aceite contextual do SDD. Uma skill de comunicação pode ajustar o acompanhamento permitido pelo plugin; ela não reduz obrigações técnicas ou autoriza novas ações.

## Comandos locais

Use o wrapper instalado na raiz do projeto:

```text
node .gag-dev-team/plugin/bin/gag-dev-team.cjs skills policy --project .
node .gag-dev-team/plugin/bin/gag-dev-team.cjs skills list --project .
node .gag-dev-team/plugin/bin/gag-dev-team.cjs skills add --project .
node .gag-dev-team/plugin/bin/gag-dev-team.cjs skills show SKILL_ID --project .
node .gag-dev-team/plugin/bin/gag-dev-team.cjs skills review SKILL_ID --project . --decision accept --reviewer REVIEWER --reason REASON --content-digest CONTENT_DIGEST --policy-digest POLICY_DIGEST --expected-revision REVISION
node .gag-dev-team/plugin/bin/gag-dev-team.cjs skills confirm SKILL_ID --project . --content-digest CONTENT_DIGEST --policy-digest POLICY_DIGEST --expected-revision REVISION
node .gag-dev-team/plugin/bin/gag-dev-team.cjs skills catalog --project .
node .gag-dev-team/plugin/bin/gag-dev-team.cjs skills load SKILL_ID --project .
node .gag-dev-team/plugin/bin/gag-dev-team.cjs skills remove SKILL_ID --project . --expected-revision REVISION
```

`skills add` recebe pela entrada padrão um objeto JSON com `name`, `description`, `skill_md`, `references`, `source_kind`, `origin`, `evidence` e `applicability`. `skill_md` contém o SKILL.md completo; `references` é um objeto de caminhos relativos em `references/` para seus textos, ou `{}` quando dispensável. Os demais campos descrevem a origem e as condições reais da proposta.

`skills confirm` recebe pela entrada padrão a fala literal que esclareceu a hipótese. Não coloque conteúdo particular em argumentos, comandos interpolados ou temporários versionáveis. Envie-o como dados. Use os IDs, digests e revisões realmente retornados pelos comandos. Não force a revisão esperada, altere índices manualmente ou invente hashes.

## Revisar e ativar

1. Leia `skills policy` e as fontes de política vigentes: obrigações globais e regras pertinentes ao assunto. Consulte as skills existentes para evitar duplicação e conflitos.
2. Produza o conteúdo e a proveniência com base na tarefa. Cadastre por `skills add`; a proposta nasce inativa. Confira o bundle por `skills show` antes da revisão.
3. Se a origem for inferida, não tente ativá-la por `review accept`. Após um esclarecimento real, use `skills confirm` com os hashes e revisão atuais. Essa ação atualiza a proveniência e invalida o recibo anterior; ela não aprova a compatibilidade.
4. Faça a revisão semântica do conteúdo e das referências. Use `accept` para proposta explícita compatível, `reject` para conflito e `unclear` quando faltar segurança. Registre revisor e motivo fundamentado, sem copiar a fala particular para argumentos ou logs. Se houver concorrência ou políticas alteradas, releia e revise a versão atual.
5. Atualize `skills catalog`. Para usar a skill, execute `skills load` e leia somente o conteúdo pertinente. Verifique sua aplicabilidade à tarefa e a compatibilidade real antes de seguir as instruções. O namespace `user/` identifica conteúdo particular; não equivale ao namespace do plugin.

O backend valida estrutura, estado, integridade e vínculo com as políticas. Ele não prova a semântica da preferência. Mesmo uma skill carregada deve ser ignorada se conflitar com uma obrigação real percebida na tarefa.

## Atualizar o conjunto efetivo

Na versão com ambiente pessoal, skills do projeto ficam separadas pela conta GitHub autenticada. `remove` gera desativação histórica; preserva bundles e versões anteriores. O conjunto legado compartilhado não pertence automaticamente à pessoa: associe somente após declaração explícita de titularidade por `environment claim-legacy`, sem remover o original nem reativar revisões antigas. Para instalar skills de terceiros e plugins no perfil privado da máquina, siga `install-user-extension`; o projeto guarda referências de habilitação e o dashboard mostra o estado real.

Depois de confirmar, revisar ou remover, recarregue o catálogo e informe que a revisão atual substitui o conjunto anterior. Deixe de aplicar skills removidas ou inativas. Nas próximas sessões os hooks disponibilizam o catálogo; o corpo continua sob demanda, sem promessa de aparecer em pickers nativos.

Edição manual, corrupção ou mudança de políticas exige nova conferência antes do uso. Não trate falha de leitura como skill aceita, não esconda diagnósticos e não apague conteúdo para contornar erro. Atualizações do plugin preservam o armazenamento local; worktrees compartilham os dados e clones independentes não os recebem pelo Git.
