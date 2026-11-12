# GAG Dev Team

Seu time de desenvolvimento com IA, organizado para entregar mais, gastar menos e manter a qualidade.

Transforme solicitações em entregas com planejamento claro, desenvolvimento focado, revisão e documentação atualizada. Cada função recebe o modelo adequado ao trabalho, buscando reduzir o custo sem abrir mão do raciocínio necessário.

Você conversa com o orquestrador e aprova o plano antes do desenvolvimento. A prioridade é fazer bem feito, mesmo quando isso leva mais tempo.

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
