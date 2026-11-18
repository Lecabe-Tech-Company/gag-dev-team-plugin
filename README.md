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
