# GAG Dev Team

Seu time de desenvolvimento com IA, organizado para entregar mais, gastar menos e manter a qualidade.

Transforme solicitações em entregas com planejamento claro, desenvolvimento focado, revisão e documentação atualizada. Cada função recebe o modelo adequado ao trabalho, buscando reduzir o custo sem abrir mão do raciocínio necessário.

Você conversa com o orquestrador e autoriza o escopo do SDD no contexto da conversa antes do desenvolvimento. Não há frase ou formato obrigatório; um aceite claro pode ocorrer antes do registro local.

A prioridade é fazer bem feito, mesmo quando isso leva mais tempo.

## Idioma do código e bloqueio de PR

Código, nomes de arquivos de código, classes, métodos, variáveis e demais identificadores técnicos devem ser em inglês. Planejamento, documentação e acompanhamento podem ser em português. Labels e textos apresentados ao usuário no frontend podem ser em pt-BR.

Antes de uma abertura de PR reconhecida pelo plugin, o hook verifica o código commitado. Violações e verificações incompletas bloqueiam a criação do PR. A regra complementa as verificações Graphify e o QA obrigatório; não exige traduzir documentação em português.

A análise verifica os identificadores nas linhas novas ou alteradas e os caminhos de arquivos de código novos ou renomeados. Usa um vocabulário inglês empacotado, com licença e checksum, além de termos técnicos explícitos. Termos desconhecidos precisam ser resolvidos antes do PR; não são aceitos automaticamente por estarem sem acentos ou em maiúsculas. Código legado sem alteração permanece fora desta migração.

Os parsers cobrem Python, JavaScript/JSX, TypeScript/TSX, PHP, JSON e TOML. Python usa AST da biblioteca padrão; JavaScript, TypeScript e PHP usam os parsers Tree-sitter instalados com Graphify. Falta de parser, erro de sintaxe ou formato de código sem cobertura bloqueia a abertura. Templates mistos, como Blade, Vue e Svelte, exigem cobertura específica e não recebem aprovação por serem parcialmente interpretados como texto.

O vocabulário é uma verificação lexical de identificadores, não uma prova de intenção semântica de palavras compartilhadas entre idiomas, como `total` e `menu`. QA continua obrigatório para revisar os contratos e o uso das strings. Hooks precisam estar instalados e confiados; operações manuais externas ao agente não são interceptadas.

Compatível com **Codex, Claude Code, Cursor e Antigravity**. Escolha um ou vários durante a instalação.

## Regras particulares do projeto

Peça ao agente para guardar uma regra particular usando a skill `manage-user-rules`. Ela compara sua regra com as políticas do plugin e ativa somente regras compatíveis. Regras conflitantes ficam inativas, com explicação; elas não podem dispensar SDD, QA ou os gates do PR.

Na implementação do ambiente pessoal, o armazenamento atual é separado pela conta GitHub autenticada (host e ID numérico) e pelo projeto, dentro dos metadados locais do Git, fora da árvore versionável. Worktrees do mesmo repositório compartilham o armazenamento; clones independentes não o recebem por `clone` ou `pull`. Os caminhos compartilhados da v0.4 continuam como legado preservado, sem associação automática a uma conta. Só importe legado após confirmação explícita de titularidade; regras importadas passam por nova revisão contra as políticas vigentes.

A skill aplica o conjunto aceito na conversa atual; novas sessões o recuperam pelos hooks. Atualizações preservam os dados. Edições manuais ou mudanças nas políticas exigem nova revisão. A análise de compatibilidade de texto é contextual, feita pelo agente; hashes e estados locais detectam revisões inválidas, sem fingir que resolvem a semântica sozinhos.

## Skills particulares e personalização

Use `manage-user-skills` para criar uma skill particular do projeto. O catálogo atual usa armazenamento separado pela conta GitHub autenticada e pelo projeto, com versões imutáveis e cache de runtime privado. Os hooks mostram um catálogo privado; o agente lê o conteúdo quando pertinente. Skills pessoais nunca substituem as skills ou políticas do plugin. Caminhos compartilhados da v0.4 são legado preservado, não um catálogo atual nem automaticamente associado a uma conta.

O agente também pode sugerir e criar rascunhos a partir de padrões da tarefa: seu modo de acompanhar o trabalho, dúvidas recorrentes, erros evitáveis e perguntas que ajudam a completar o SDD. Preferências explícitas podem ser consolidadas após revisão; hipóteses inferidas continuam inativas até esclarecimento. Uma ocorrência isolada não vira regra permanente.

As skills preservam as obrigações do plugin, os sete subtítulos e o aceite do SDD e as permissões da tarefa. O recurso não executa scripts automaticamente nem percorre seus chats anteriores. Dados particulares não são enviados ao Git ou incluídos nos pacotes e permanecem locais após atualizações.

## Instalação

O plugin inclui um dashboard Next.js local para regras, skills, sessões, problemas, modelos e extensões pessoais. Peça ao agente para abrir o acompanhamento; a skill `ensure-dashboard` verifica ou inicia o serviço e informa sua URL protegida. O dashboard requer Node.js 20.9+ com npm e usa somente loopback. A autenticação da conta usa GitHub CLI (`gh auth login`); tokens nunca são enviados ao navegador.

O histórico JSON é imutável e separado por host e ID numérico GitHub nos metadados locais do Git. Correções e desativações adicionam eventos; nenhum registro histórico é apagado. Dados legados compartilhados exigem declaração explícita de titularidade antes da associação. Métricas cobrem somente tentativas e problemas registrados, com origem configurada/declarada/observada/desconhecida do modelo; não representam todas as chamadas LLM.

Pedidos claros de instalação de plugins ou skills pessoais usam `install-user-extension`: versões e proveniência ficam no perfil privado da máquina, fora de Git, e cada projeto mantém suas referências. Toda ativação depende de compatibilidade com as regras obrigatórias do plugin. Instalação nativa pode depender de trust, autenticação ou reinício; o agente informa o estado real.

Tenha **Git**, **Node.js 18+ com npm** e **Python 3.11+** instalados. O dashboard local requer **Node.js 20.9+**. Abra o terminal na pasta do seu projeto Git.

No Windows (CMD ou PowerShell), Linux ou macOS:

```sh
npx --yes github:Lecabe-Tech-Company/gag-dev-team-plugin install
```

Selecione os ambientes em que deseja usar seu time. Para selecionar diretamente:

```sh
npx --yes github:Lecabe-Tech-Company/gag-dev-team-plugin install --harness codex,claude,cursor,antigravity
```

A instalação utiliza a última release estável publicada. Se ainda não houver uma release, aguarde a primeira publicação em [Releases](https://github.com/Lecabe-Tech-Company/gag-dev-team-plugin/releases).

## Conecte seu Scripta

```sh
npx --yes github:Lecabe-Tech-Company/gag-dev-team-plugin configure
```

Uma janela abre no navegador para inserir e salvar sua chave do Scripta. O guia para obter a chave está na própria tela. Sua chave fica somente no projeto local e fora do Git.

Após salvar, aguarde a confirmação e reabra seu ambiente de desenvolvimento. Conclua as permissões e autenticações que ele solicitar.

## Atualizações

O time verifica novas versões no início e no término das sessões, nos ambientes com hooks habilitados. Para atualizar manualmente:

```sh
npx --yes github:Lecabe-Tech-Company/gag-dev-team-plugin update
```

Modelos e recursos disponíveis dependem do seu ambiente e da sua conta.
