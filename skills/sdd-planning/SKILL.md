---
name: sdd-planning
description: Planejar features, ajustes e melhorias do Renew IT por SDD, com requisitos, contexto, regras de negócio, critérios de aceite, falhas e mitigações, orientação ao desenvolvedor e evidências de conclusão.
---

# Planejamento orientado a SDD

O Orquestrador / Planejador deve estruturar o planejamento de cada demanda como um SDD antes do desenvolvimento. Use o [modelo de SDD](assets/sdd-template.md), mantendo os sete subtítulos obrigatórios na ordem abaixo.

Consulte o Scripta/renew-it para documentação e regras do sistema, Graphify para localizar a implementação e Context7 para documentação técnica de bibliotecas e frameworks. Separe fatos verificados, propostas, hipóteses e pendências; cite as fontes efetivamente consultadas.

## Estrutura obrigatória

1. **Requisitos:** resultado esperado, comportamentos necessários e limites do escopo. Identifique os requisitos para relacioná-los aos critérios e às evidências.
2. **Contexto:** situação atual, motivo da demanda, fluxo existente, dependências e pontos de integração confirmados.
3. **Regras de Negócio:** condições, restrições, permissões, validações e exceções aplicáveis, com suas fontes. Não transforme suposições em regras.
4. **Critérios de Aceite:** condições observáveis e verificáveis que demonstram o atendimento dos requisitos; descreva cenário, ação e resultado esperado.
5. **Pontos de Falha e Mitigações:** falhas concretas relacionadas à demanda, seus efeitos, a prevenção ou tratamento e como verificar a mitigação.
6. **Dev Thinking:** orientação técnica prática para o desenvolvedor atingir todos os requisitos e objetivos. Explique a abordagem, os caminhos existentes a reaproveitar, a sequência de implementação, as dependências, as decisões e suas justificativas objetivas. Inclua pseudocódigo quando ajudar. Não trate esta seção como transcrição de raciocínio interno.
7. **Evidências a serem coletadas antes de confirmar como concluído.:** defina antecipadamente o que comprovará cada critério de aceite, como coletar a evidência e qual resultado será considerado suficiente. Diferencie evidência planejada de evidência já coletada.

Não omita subtítulos. Quando uma seção não se aplicar, registre a justificativa. Lacunas ou decisões pendentes devem ficar explícitas; não invente dados para completar o SDD.

Documentação viva e SDDs do sistema devem ser mantidos no Scripta conforme as regras do projeto. O arquivo em assets é um modelo distribuído pelo plugin, não uma especificação paralela do Renew IT.

Antes de apresentar o planejamento como pronto, confira a coerência entre requisitos, regras, critérios, mitigações, orientação de implementação e evidências. Ao acompanhar a entrega, só confirme como concluído aquilo que tiver as evidências exigidas coletadas e verificadas; registre o que permanecer pendente.

## Criar no Scripta e entregar ao time

Crie e mantenha o SDD no Scripta, projeto renew-it. Antes de delegar uma demanda, entregue ao time o código/slug, o link quando disponível, a versão vigente, o escopo e os critérios/evidências esperados. O resumo do repasse ajuda a orientar, mas todos os agentes devem consultar o documento no Scripta em seu próprio contexto.

Confirme que cada agente possui as ferramentas MCP do Scripta e acesso ao projeto. Os perfis herdam servidores e permissões do agente principal; instalar um TOML não cria credenciais nem comprova acesso. Se houver impedimento, use o guia de configuração e regularize antes de trabalho dependente do SDD.

Use gag-investigador-advisor como braço direito do planejamento e da orientação técnica, compartilhando o SDD, as evidências e as dúvidas específicas. O desenvolvedor também usa esse apoio. O advisor orienta com fontes; ele não substitui decisões do usuário nem recebe autoridade de merge.

No Contexto, registre as versões declaradas e verificadas das bibliotecas e o módulo próprio da feature. No Dev Thinking, respeite a arquitetura modular MVC com serviços, SOLID, Object Calisthenics, a documentação Filament v5, a preferência por recursos nativos e o CSS global. Consulte as regras da skill sdd-development para detalhar a abordagem.


## Simplicidade, pseudocódigo e performance no Dev Thinking

Oriente o dev a identificar a etapa atual do SDD antes de codar. Dê uma sequência de implementação ou pseudocódigo proporcional à tarefa, usando o advisor quando necessário para resolver dúvidas ou comparar alternativas. Priorize reaproveitamento e a solução mais simples que cumpra todos os requisitos.

Quando relevante ao volume e ao risco, explicite a complexidade de tempo e memória em Big O, o significado de n e os custos de consultas, I/O e carregamento de dados. Diferencie hipótese de performance e resultado medido. Oriente código legível, responsabilidades claras, early returns adequados e comentários explicativos para comportamentos não óbvios.

## Responsabilidade e evidências dos testes

Planeje a implementação dos testes como responsabilidade do Revisor / QA, separada da implementação da aplicação pelo dev. Nos Critérios de Aceite e nas Evidências, relacione cenários do fluxo e riscos concretos de segurança/qualidade; o objetivo dos testes é detectar defeitos e verificar contratos, não apenas passar.

A execução dos testes da feature e dos fluxos relacionados é obrigatória antes de enviar qualquer PR para stage/prod. Inclua sua identificação, revisão testada, comandos/resultados e pendências nas evidências. Mudanças posteriores exigem repetir a validação afetada. O orquestrador não considera a entrega apta para PR se essa verificação estiver faltando ou falhando.
