---
name: setup-team
description: Instalar e configurar o GAG Dev Team em Codex, Claude Code, Cursor ou Antigravity.
---

# Configurar o time

1. Identifique a raiz Git do projeto de destino. Preserve configurações existentes e resolva colisões com o usuário.
2. Execute na raiz: npx --yes github:Lecabe-Tech-Company/gag-dev-team-plugin install. A primeira instalação oferece seleção múltipla dos quatro ambientes; para execução não interativa use --harness codex,claude,cursor,antigravity com os ambientes desejados.
3. A CLI baixa exclusivamente a última release estável oficial com checksum. Se não houver release ou a rede falhar, informe a falha; nunca substitua por uma branch.
4. Execute configure pelo mesmo comando npx. A janela local recebe a chave do Scripta; nunca solicite credenciais no chat. Salvar prepara o acesso e dispara a instalação do Graphify.
5. Reabra os ambientes selecionados e conclua as permissões e autenticações nativas. Context7 usa OAuth. Cada agente confirma seu acesso ao Scripta e consulta docs_briefing de renew-it.
6. O orquestrador conversa com o usuário e avalia o aceite no contexto real: só autorização clara do escopo e da versão vigente permite desenvolver; silêncio, negativa, ambiguidade ou outro escopo não autorizam. O aceite pode ocorrer antes de declare-sdd. Mudança material exige novo aceite. O orquestrador pode registrar a fala literal com approve-sdd --evidence e --recorded-by; esse registro é auxiliar, e falha/ausência não exige repetir aceite já dado. Não invente evidência; confirmação terminal só vale quando uma pessoa responde sim/não diretamente.
7. Cada harness recebe seus formatos nativos e modelos relativos por função. Não prometa equivalência de raciocínio nem disponibilidade de modelos. Preserve escolhas explícitas já configuradas. No Cursor, o modelo da conversa principal depende do seletor do cliente; as regras mantêm a identidade do orquestrador.
8. SessionStart e Stop verificam releases com os hooks habilitados. update permite atualização manual. Preserve alterações locais e a chave em caso de falha.

Caveman é o padrão de comunicação; respeite normal mode/stop caveman e preserve documentos e código completos. As políticas de desenvolvimento e os sete subtítulos do SDD ficam nas skills development-workflow, sdd-planning, sdd-development e sdd-qa.
