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

O conteúdo fica em `<git-common-dir>/gag-dev-team/user-rules/`, nos metadados locais do repositório e fora da árvore versionável. Não depende apenas de `.gitignore`: não é um arquivo da árvore que possa entrar normalmente em um commit. Worktrees compartilham esse armazenamento; outro clone não recebe suas regras por `clone` ou `pull`.

A skill aplica o conjunto aceito na conversa atual; novas sessões o recuperam pelos hooks. Atualizações preservam os dados. Edições manuais ou mudanças nas políticas exigem nova revisão. A análise de compatibilidade de texto é contextual, feita pelo agente; hashes e estados locais detectam revisões inválidas, sem fingir que resolvem a semântica sozinhos.

## Skills particulares e personalização

Use `manage-user-skills` para criar uma skill particular do projeto. Ela fica em `<git-common-dir>/gag-dev-team/user-skills/`, com SKILL.md e referências textuais. Os hooks mostram um catálogo privado; o agente lê o conteúdo quando ele é pertinente. Esse catálogo tem namespace próprio e não substitui as skills do plugin nem promete aparecer em seletores nativos dos editores.

O agente também pode sugerir e criar rascunhos a partir de padrões da tarefa: seu modo de acompanhar o trabalho, dúvidas recorrentes, erros evitáveis e perguntas que ajudam a completar o SDD. Preferências explícitas podem ser consolidadas após revisão; hipóteses inferidas continuam inativas até esclarecimento. Uma ocorrência isolada não vira regra permanente.

As skills preservam as obrigações do plugin, os sete subtítulos e o aceite do SDD e as permissões da tarefa. O recurso não executa scripts automaticamente nem percorre seus chats anteriores. Dados particulares não são enviados ao Git ou incluídos nos pacotes e permanecem locais após atualizações.

## Instalação

Tenha **Git**, **Node.js 18+ com npm** e **Python 3.11+** instalados. Abra o terminal na pasta do seu projeto Git.

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
