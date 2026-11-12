---
name: sdd-development
description: Desenvolver features, ajustes e melhorias do Renew IT a partir do SDD no Scripta, conferindo versões, documentação Filament v5, arquitetura modular MVC com serviços e CSS global.
---

# Desenvolvimento orientado ao SDD

## Receber e conferir o SDD

Ao receber uma solicitação de desenvolvimento, solicite ao orquestrador ou solicitante o SDD criado no Scripta/renew-it. Se o repasse já informar sua referência, confirme a versão e leia o documento sem repetir a pergunta. Não inicie implementação sem identificar e consultar o SDD correspondente.

Confira os sete subtítulos obrigatórios da skill sdd-planning e os requisitos, critérios e evidências da demanda. Registre no contexto de trabalho o código/slug, a versão consultada e as pendências relevantes. Se faltar SDD ou acesso, solicite a regularização; não crie requisitos por suposição.

## Entender a etapa antes de codar

Antes de alterar código, identifique no SDD a etapa atual, os requisitos que ela atende, suas dependências, o resultado esperado e as evidências necessárias. Mantenha esse estado no contexto de trabalho e atualize-o ao concluir a etapa ou encontrar um impedimento. Não comece por uma solução desconectada do plano.

Defina primeiro uma sequência curta de implementação ou pseudocódigo proporcional à tarefa. Para uma mudança simples, poucas instruções claras bastam. Se o Dev Thinking já contiver pseudocódigo suficiente e atualizado, confira-o e reaproveite-o.

Quando houver ambiguidade, alternativas difíceis de comparar ou risco de complexidade desnecessária, chame gag-investigador-advisor para elaborar ou revisar o pseudocódigo antes de implementar. Compartilhe a etapa, os requisitos, as fontes e a dúvida concreta. A orientação deve ficar coerente com o SDD no Scripta; mudanças de escopo ou regra de negócio precisam ser reconciliadas com o orquestrador.

## Escolher a solução mais simples e eficiente

Prefira a solução mais simples que cumpra integralmente o SDD: reaproveite a biblioteca e o código existente antes de criar camadas, componentes ou abstrações novas. Não antecipe extensibilidade sem necessidade concreta.

Avalie a complexidade de tempo e memória dos caminhos relevantes usando Big O. Defina o que n representa, considere o volume esperado e compare alternativas quando isso mudar a escolha. Verifique loops aninhados, buscas repetidas em coleções, quantidade de consultas, N+1, hidratação excessiva, processamento em lote e paginação conforme a demanda.

Considere também os custos reais de I/O, banco e memória: uma classificação assintótica melhor, isoladamente, não prova que a solução é mais rápida no volume utilizado. Escolha a melhor performance compatível com correção, legibilidade e padrões do projeto. Evite micro-otimizações sem benefício demonstrável; se houver hipótese de gargalo ou alegação de ganho, colete medidas representativas e registre limites da comparação. Não declare melhora de performance sem evidência.

## Escrever código legível e funcional

Aplique Object Calisthenics e SOLID para reduzir responsabilidades misturadas e aninhamento. Prefira guard clauses e early returns quando simplificarem o fluxo sem alterar validações, autorização, transações ou efeitos necessários. O objetivo é clareza; não encurte o código por meio de expressões obscuras.

Use nomes de métodos e variáveis que expressem sua intenção e comportamento. Se um método não explica o que faz, primeiro considere melhorar o nome ou separar responsabilidades. Quando houver uma restrição legítima ou comportamento não óbvio que não possa ser explicado adequadamente pelo nome, adicione comentários explicativos sobre a intenção, a regra ou o motivo da decisão. Não use comentários para esconder um nome enganoso ou repetir literalmente o código; mantenha-os atualizados.

Confira a implementação contra os critérios da etapa antes de avançar. Entregue código funcional, legível e de complexidade justificada, acompanhado das evidências exigidas pelo SDD.

## Trabalhar com o investigador / advisor

Use o agente gag-investigador-advisor como braço direito para orientar a execução. Compartilhe a referência e a versão do SDD, os pontos técnicos a esclarecer e as evidências disponíveis. Consulte-o para escolher caminhos adequados, reaproveitar recursos e resolver dúvidas de implementação; ele deve conferir as fontes e devolver orientação fundamentada.

O apoio do advisor não muda o escopo nem substitui decisões do usuário ou a documentação vigente. Parecer não equivale a aprovação de produto, autorização de backend ou permissão de merge.

## Conferir e manter as versões em contexto

Antes de desenvolver, leia o composer.json na revisão/worktree da demanda e mantenha em contexto os nomes e as restrições de versão das bibliotecas relevantes. Consulte composer.lock para versões resolvidas e confira a versão real do PHP, quando necessário: uma restrição como ^8.4 não comprova a versão exata do runtime.

Base informada pelo usuário: **Filament v5, Laravel 12 e PHP 8.4.27**. Identifique essa base como declarada até verificá-la no projeto. Se as evidências divergirem, registre a divergência e regularize a orientação antes de escolher APIs incompatíveis; não troque dependências por conta própria.

Reconfira quando mudar de projeto, worktree, revisão ou quando composer.json/composer.lock mudar. Ao resumir o contexto para continuidade, preserve as versões verificadas e suas fontes. Não grave segredos em arquivos de memória.

## Fundamentar a implementação nas bibliotecas

Todo desenvolvimento deve se apoiar nos padrões das bibliotecas efetivamente utilizadas e na documentação correspondente às versões conferidas. Use Context7 para documentação técnica e fontes oficiais quando precisar confirmar o comportamento. Não use exemplos de outra versão como se fossem compatíveis.

Para **toda página, componente ou ação Filament**, é obrigatória a consulta ao tópico correspondente da documentação do **Filament v5** antes de implementar. Registre a fonte/tópico consultado e sua aplicação à demanda. Não basta conhecer genericamente o Filament ou consultar apenas Laravel.

Prefira os recursos nativos existentes no Filament v5. Antes de propor uma view Blade ou componente personalizado, confira se um recurso nativo já atende ao requisito. Uma personalização necessária deve ter justificativa no SDD; a preferência é reaproveitar o que a biblioteca fornece.

## Respeitar o CSS global

O CSS define o design do sistema, não o de uma página isolada. Use o tema, as classes e os padrões globais existentes.

É proibido injetar CSS personalizado nas páginas: isso inclui blocos style, atributos style, injeção de regras por JavaScript, extraAttributes com style ou estilos locais inseridos por mecanismos como push de styles. Não contorne a regra movendo um estilo exclusivo da página para um ponto de injeção indireto.

Se a demanda realmente exigir mudança de design, trate-a no design global do sistema, dentro do escopo autorizado e com os efeitos sobre outras telas considerados. Não invente um tema específico para a página.

**CSS personalizado embutido em página é violação do projeto e implica reprovação automática do PR pelo Revisor / QA.** Não apresente essa alteração como pronta para aprovação. A regra de revisão não instala por si só uma proteção no servidor GitHub.

## Seguir a arquitetura do projeto

Adote o **monólito modular MVC com camada de serviço**, com forte aplicação de **SOLID** e **Object Calisthenics**. Reaproveite os padrões existentes coerentes com essa arquitetura e com as bibliotecas; mantenha responsabilidades claras e regras de negócio na camada apropriada.

Cada feature deve ser desenvolvida em seu próprio módulo, identificado no SDD. Ajustes e melhorias de uma feature permanecem no módulo dela. Não espalhe a implementação nova por áreas externas ao módulo; explicite no SDD as integrações e dependências compartilhadas necessárias.

Não transforme os princípios em motivo para criar camadas ou abstrações sem uso concreto. Respeite as autorizações de backend do projeto, inclusive a chave de desenvolvimento quando exigida.

## Entregar evidências

Siga o fluxo compartilhado de worktree, branch e PRs. Valide os critérios do SDD, verifique a ausência de CSS embutido e entregue as evidências previstas, as versões consideradas e as referências técnicas consultadas. A documentação do sistema é mantida no Scripta, com apoio do documentador. Não confirme como concluído o que ainda tiver evidência obrigatória pendente.

## Encaminhar a implementação ao QA

O dev não cria nem altera testes, fixtures ou auxiliares específicos dos testes da demanda. A autoria e manutenção pertence ao Revisor / QA, conforme a skill sdd-qa. O dev pode executar testes existentes para diagnóstico, informar cenários e dependências impactados e corrigir os defeitos no código da aplicação demonstrados pelo QA, preservando a separação das responsabilidades.

Coordene o repasse no mesmo worktree/branch para evitar alterações concorrentes. Antes de enviar PRs, confira com o QA que os testes da feature e dos fluxos relacionados foram executados no estado final da branch, com resultados e evidências. Não envie com essa validação pendente ou falhando.
