---
name: setup-team
description: Configurar os cinco perfis de agentes do GAG Dev Team no projeto após instalar o plugin ou quando o usuário pedir a configuração do time.
---

# Configurar o time

Use esta skill na configuração inicial do plugin ou quando o usuário solicitar a instalação dos perfis em um projeto.

1. Identifique a raiz do projeto que o usuário está configurando. Se não houver um destino inequívoco, pergunte qual projeto deve receber os perfis.
2. Localize a raiz instalada deste plugin a partir deste arquivo.
3. Execute o script empacotado `scripts/install-agents.py --project CAMINHO_ABSOLUTO_DO_PROJETO` com Python 3.10+. O caminho do script parte da raiz do plugin; não execute um arquivo homônimo no projeto de destino.
4. O script instala os cinco TOMLs em `.codex/agents/`. Se houver perfil com conteúdo diferente, ele recusa sobrescrever. Informe o conflito e preserve a configuração existente.
5. Oriente a reiniciar a sessão do Codex para recarregar os perfis. Os arquivos não mudam automaticamente o modelo da conversa principal nem iniciam agentes.
6. O Context7 está declarado em `mcp.json` como servidor remoto OAuth, no endpoint `https://mcp.context7.com/mcp/oauth`. Se o cliente solicitar autenticação, oriente a concluir o login do Context7 pelo cliente. Não solicite credenciais no chat.
7. Confira a presença das ferramentas Context7 e Scripta na nova sessão. Todos os agentes devem herdar o MCP do Scripta e consultar docs_briefing para renew-it em seu próprio contexto antes de trabalho dependente do SDD. Perfis não carregam credenciais próprias nem alteram permissões. A conexão principal precisa estar configurada, habilitada e acessível. Para configurar o acesso ao Scripta/renew-it, use o guia da skill development-workflow.

Os perfis incluem identidade, função, modelo, raciocínio e as regras já definidas pelo usuário: SDD no Scripta, repasse ao time, apoio do advisor e padrões de desenvolvimento/revisão. Novas regras serão acrescentadas conforme orientação do usuário. Não introduza novos fluxos de aprovação ou inicie o time apenas para testar a instalação.
