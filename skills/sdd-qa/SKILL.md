---
name: sdd-qa
description: Revisar e implementar testes de features do Renew IT com base no SDD, cobrindo cenários reais, segurança, qualidade e regressões dos fluxos relacionados antes de PRs.
---

# Revisão e testes orientados ao SDD

## Responsabilidade dos testes

O agente gag-revisor-qa é responsável por criar e manter os testes da demanda, incluindo dados e auxiliares específicos desses testes. O desenvolvedor implementa a feature e corrige os defeitos relatados; ele não cria nem altera testes. Ele pode executar testes existentes para diagnóstico.

Planeje e implemente os testes no mesmo worktree/branch da feature, coordenando a posse dos arquivos com o desenvolvedor para evitar edições concorrentes. Preserve as autorizações do projeto; o papel de QA não concede acesso adicional ao backend nem autoriza merge.

## Definir o que os testes precisam demonstrar

Leia o SDD vigente no Scripta/renew-it e os documentos de negócio relacionados. Confira as versões e as ferramentas de teste já instaladas e os padrões dos testes próximos. Use a documentação correspondente à versão para a sintaxe necessária, sem presumir a versão de Pest ou PHPUnit.

Relacione requisitos e critérios de aceite aos cenários, resultados esperados e evidências. O resultado esperado vem do contrato e da regra de negócio, não da implementação atual. Identifique divergências e pendências no SDD em vez de inventar uma resposta.

O objetivo é exercitar comportamentos e detectar defeitos reais para proteger segurança e qualidade. Passar é consequência de implementação correta e verificação adequada; não é a finalidade isolada do teste.

## Cobrir cenários relevantes do fluxo

Não limite a cobertura ao caminho feliz nem imponha um número arbitrário de testes. Cubra os cenários distintos e os riscos concretos do fluxo, conforme se apliquem:

- Resultados válidos com dados representativos e variações das regras de negócio.
- Entradas vazias, ausentes ou inválidas; limites mínimo e máximo; valores imediatamente fora do limite.
- Autenticação, autorização, isolamento de dados e efeitos proibidos.
- Estados em que a ação é permitida ou recusada.
- Reenvio, idempotência, concorrência e duplicação quando o fluxo puder sofrer essas condições.
- Falhas de dependências, transações, rollback e consistência de dados.
- Efeitos em banco, eventos, filas e integrações nos limites necessários ao cenário.
- Regressões nas funcionalidades que compartilham os contratos ou caminhos alterados.

Cada cenário deve ter uma condição relevante e um resultado esperado verificável. Use datasets quando as variações tiverem a mesma estrutura e contratos distintos merecerem cobertura; não multiplique casos equivalentes apenas para aumentar contagem.

## Evitar testes feitos apenas para passar

Exercite comportamento observável, resultados persistidos e ausência de efeitos indevidos quando isso fizer parte da regra. Use assertions capazes de detectar o defeito que o cenário pretende revelar; apenas executar sem exceção ou verificar uma resposta genérica pode ser insuficiente.

Não copie a lógica da implementação para calcular o resultado esperado. Não substitua a unidade sob teste por um mock que já devolve o resultado desejado. Isole dependências externas quando necessário sem eliminar o comportamento que precisa ser exercitado.

Não remova assertions, afrouxe condições, ignore falhas, marque testes como skipped/incomplete ou altere expectativas só para obter verde. Uma expectativa incorreta pode ser corrigida quando a regra e a evidência demonstrarem o erro, registrando a justificativa.

Se um teste revelar defeito de implementação, entregue ao dev o cenário, o esperado, o observado e as evidências. O QA mantém o teste que detecta o problema; o dev corrige o código da aplicação. Não adapte o teste ao bug. Quando viável, demonstre que um teste de regressão distingue o comportamento defeituoso do corrigido.

## Mapear os fluxos relacionados

Use Graphify para identificar dependências, consumidores e caminhos de código afetados. Consulte o Scripta para confirmar os contratos e fluxos de negócio relacionados, e confira os testes existentes desses caminhos.

Defina explicitamente os conjuntos de testes da feature e dos fluxos relacionados, com justificativa de cobertura. Uma seleção por nome ou filtro não comprova que todas as dependências relevantes foram incluídas. Se o impacto não puder ser delimitado, amplie a execução para os módulos/suítes pertinentes; alterações transversais podem exigir a suíte completa.

Se não houver testes necessários para um fluxo relacionado, implemente a cobertura pertinente como QA; não trate ausência de teste como evidência de ausência de risco.

## Executar antes de enviar PR

Antes do PR, execute no estado final todos os testes novos ou alterados para a feature. Todos devem passar; teste da feature não descoberto, pendente, omitido, skipped/incomplete ou falhando significa que o critério não foi atendido. Confira descoberta, comandos e ambiente, inclusive isolamento do banco e integrações.

Execute também as verificações dos fluxos relacionados conforme o impacto e relate seus resultados em separado; elas não são declaradas aprovadas por estarem verdes as da feature. Falha relacionada bloqueia a feature somente quando há evidência de que foi introduzida pela alteração ou quando sua causa não pode ser distinguida de uma regressão da feature. Falha comprovadamente preexistente deve ser registrada com evidência, sem exigir correção do legado nesta demanda. Se a alteração causar regressão, QA a cobre como teste da feature e o dev corrige antes do envio.

A execução obrigatória deve ocorrer depois da última alteração relevante. Registre a revisão/estado testado; se código ou testes mudarem depois, repita conjuntos afetados e a cobertura relacionada. Resultados de outra revisão não aprovam os testes da feature. Não recomende nem envie PR enquanto qualquer teste da feature estiver pendente ou falhando.

## Entregar o resultado da revisão

Registre os comandos executados, o ambiente/versões relevantes, a revisão testada, a seleção de cenários da feature e relacionados, os resultados e as pendências. Consolide as evidências no Scripta e na descrição dos PRs conforme o fluxo do time; não versione relatórios gerados.

Revise também os critérios arquiteturais, de versões, Filament e CSS global já definidos. Testes verdes não substituem esses critérios nem provam ausência absoluta de defeitos. Informe o que foi efetivamente verificado e os limites da cobertura; nenhuma revisão autoriza merge automatizado.

## Idioma do código

Código, nomes de arquivos de código e identificadores técnicos devem ser em inglês. Planejamento, SDD, documentação e acompanhamento podem ser em português; labels e textos do frontend podem ser em pt-BR. A verificação de idioma do diff commitado é obrigatória antes de abrir PR: violação ou análise incompleta bloqueia a abertura. Consulte a seção 13 da skill development-workflow. Não exija tradução de documentos por esta regra.
