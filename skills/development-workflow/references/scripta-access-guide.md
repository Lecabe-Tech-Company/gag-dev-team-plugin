# Guia de Acesso e Configuração do Scripta

## 1. Objetivo

Este guia apresenta os procedimentos para começar a utilizar o **Scripta**, plataforma de documentação e gestão de conhecimento de projetos de software.

Ao final, você deverá saber como:

1. Criar sua conta no Scripta.
2. Solicitar acesso a um projeto existente.
3. Gerar uma API Key para integrações.
4. Autorizar o acesso da API Key a um projeto específico.
5. Validar as permissões e a conexão com o projeto.

> **Observação:** Os nomes exatos de alguns botões e menus devem ser conferidos na versão do Scripta utilizada. As etapas abaixo descrevem o fluxo de configuração; caminhos de interface não confirmados são indicados como orientações.

---

## 2. Criando uma conta no Scripta

### Passo 1 — Acessar a plataforma

1. Abra seu navegador.
2. Acesse o endereço do Scripta fornecido pela sua organização.
3. Na tela inicial, procure a opção de cadastro, como **Criar conta** ou **Registrar-se**.

### Passo 2 — Preencher os dados

Informe os dados solicitados pelo formulário de cadastro, normalmente:

- Nome completo.
- E-mail profissional.
- Senha de acesso.
- Confirmação da senha.

Clique na opção de cadastro para continuar.

### Passo 3 — Confirmar o cadastro

Caso a plataforma solicite confirmação de e-mail:

1. Abra a caixa de entrada do e-mail informado.
2. Localize a mensagem de confirmação do Scripta.
3. Clique no link de ativação.
4. Retorne à plataforma.

### Passo 4 — Realizar o primeiro login

1. Acesse novamente o Scripta.
2. Informe seu e-mail e senha.
3. Entre na plataforma.
4. Verifique os projetos disponíveis em sua conta.

**Resultado esperado:** sua conta está criada e você consegue acessar o ambiente do Scripta.

> Criar uma conta não significa receber automaticamente acesso aos projetos de outros usuários.

---

## 3. Solicitando acesso a um projeto no Scripta

Projetos no Scripta possuem permissões individuais. Para acessar um projeto criado por outra pessoa, é necessário que o responsável conceda acesso à sua conta.

### Passo 1 — Identificar o projeto

Solicite ao responsável as seguintes informações:

- Nome do projeto.
- Identificador (slug) do projeto.
- Nome ou contato do proprietário.
- Nível de permissão necessário.

**Exemplo:**

```text
Nome do projeto: Sistema Financeiro
Slug: sistema-financeiro
Permissão desejada: Editor
```

### Passo 2 — Solicitar autorização

Entre em contato com o proprietário ou administrador do projeto e informe o e-mail utilizado no cadastro do Scripta.

**Modelo de solicitação:**

> Olá!
>
> Já criei minha conta no Scripta e preciso de acesso ao projeto **Sistema Financeiro**.
>
> Meu e-mail cadastrado é: usuario@empresa.com
>
> Gostaria de solicitar permissão de Editor para consultar e manter a documentação técnica do projeto.
>
> Obrigado!

### Passo 3 — Aguardar a liberação

O responsável pelo projeto deverá acessar as opções de gerenciamento de membros ou compartilhamento e conceder a permissão adequada à sua conta.

As permissões identificadas na integração do Scripta são:

| Permissão | Descrição |
|---|---|
| Owner | Proprietário do projeto. |
| Editor | Pode consultar e editar a documentação. |
| Viewer | Pode consultar documentos, sem permissão de escrita. |

### Passo 4 — Validar o acesso

Após a liberação:

1. Entre novamente no Scripta.
2. Acesse a lista de projetos.
3. Localize o projeto compartilhado.
4. Abra sua documentação.
5. Verifique se as operações necessárias estão disponíveis.

**Resultado esperado:** o projeto aparece entre os projetos acessíveis pela sua conta.

---

## 4. Gerando uma API Key no Scripta

Uma **API Key** é uma credencial utilizada para permitir que aplicações externas e agentes de IA se autentiquem nas ferramentas de integração do Scripta.

Ela pode ser utilizada em integrações com ferramentas de desenvolvimento, automações e clientes MCP compatíveis.

### Passo 1 — Acessar as configurações da conta

1. Faça login no Scripta.
2. Abra as configurações de sua conta.
3. Localize a seção de integrações, API Keys ou tokens de acesso.

> O nome e a localização exatos dessa seção devem ser conferidos na interface atual da plataforma.

### Passo 2 — Criar uma chave

Na seção de credenciais:

1. Selecione a opção para criar uma nova chave.
2. Informe um nome que identifique a finalidade da integração, caso solicitado.
3. Configure as permissões disponíveis e necessárias.
4. Confirme a geração.

**Exemplos de nomes:**

```text
vscode-desenvolvimento
agente-documentacao
integracao-ci-cd
```

### Passo 3 — Armazenar a chave

Depois de gerar a chave, copie o valor apresentado e armazene-o em um local seguro.

Exemplo ilustrativo de configuração:

```env
SCRIPTA_API_KEY=sua_chave_aqui
```

**Boas práticas de segurança:**

- Nunca compartilhe sua API Key publicamente.
- Não inclua a chave diretamente no código-fonte.
- Não salve credenciais em repositórios Git.
- Utilize variáveis de ambiente ou um gerenciador de segredos.
- Crie chaves diferentes para integrações diferentes, quando possível.
- Revogue e substitua chaves comprometidas.

> **Importante:** A API Key do Scripta não deve ser confundida com uma chave da OpenRouter. A OpenRouter é configurada separadamente em **Configurações → Assistente**, quando necessária para recursos de IA.

---

## 5. Liberando um projeto específico no Scripta

Depois de criar uma API Key, é necessário verificar se ela possui autorização para operar no projeto desejado.

O acesso do usuário e o acesso da integração devem ser tratados separadamente.

### Passo 1 — Confirmar o acesso do usuário

Antes de configurar a integração, confirme que a conta associada à chave possui acesso ao projeto.

O responsável pelo projeto deverá conceder o papel adequado ao usuário.

### Passo 2 — Verificar as permissões da API Key

Acesse a área de gerenciamento de credenciais do Scripta e verifique quais ferramentas ou permissões estão disponíveis para a chave.

Se houver controles de autorização por projeto, selecione somente o projeto que a integração precisa acessar.

**Exemplo de escopo desejado:**

```text
API Key: agente-documentacao

Projeto:
  sistema-financeiro

Permissões necessárias:
  - Consultar documentação
  - Pesquisar documentos
  - Criar documentos
  - Atualizar documentos
```

> **Atenção:** A existência de uma configuração de restrição por projeto na interface ainda precisa ser confirmada. As ferramentas MCP conhecidas recebem o identificador do projeto, mas isso não significa necessariamente que a chave tenha um mecanismo separado de autorização por projeto.

### Passo 3 — Validar a autorização

Utilize a integração do Scripta para listar os projetos acessíveis pela chave.

A ferramenta MCP disponível para essa consulta é:

```text
docs_list_projects
```

Ela retorna informações como:

```json
{
  "projects": [
    {
      "slug": "sistema-financeiro",
      "name": "Sistema Financeiro",
      "role": "editor"
    }
  ]
}
```

*O JSON acima é apenas um exemplo ilustrativo.*

Se o projeto aparecer na resposta, a chave possui acesso de acordo com o papel informado.

### Passo 4 — Testar a consulta ao projeto

Com o slug identificado, utilize a ferramenta:

```text
docs_briefing
```

Informando o projeto:

```json
{
  "project": "sistema-financeiro"
}
```

Essa operação permite carregar informações gerais sobre o projeto, seus documentos, categorias e instruções de documentação.

**Resultado esperado:** a integração consegue consultar as informações do projeto autorizado.

---

## 6. Entendendo os níveis de acesso

É importante diferenciar três elementos:

| Elemento | Finalidade |
|---|---|
| Conta do usuário | Identifica a pessoa que utiliza o Scripta. |
| Permissão no projeto | Define quais projetos o usuário pode consultar ou editar. |
| API Key | Autentica a integração e permite utilizar as ferramentas autorizadas. |

Uma API Key válida não garante permissão de escrita em todos os projetos.

Por exemplo, se a credencial possuir acesso como `viewer`, tentativas de edição podem retornar o erro HTTP `403 Forbidden`.

---

## 7. Problemas comuns

### O projeto não aparece na listagem

**Possíveis causas:**
- O proprietário ainda não compartilhou o projeto.
- A conta utilizada não é a correta.
- O projeto está identificado por outro slug.
- A credencial não tem acesso ao projeto solicitado.

**Solução:** confirme o compartilhamento com o proprietário e consulte novamente a lista de projetos.

### Erro 401 — Unauthorized

Indica um problema de autenticação.

**Verifique:**
- Se a API Key foi informada corretamente.
- Se a credencial continua válida.
- Se o cliente está configurado com a chave adequada.

### Erro 403 — Forbidden

Indica que a operação não foi autorizada.

**Verifique:**
- As permissões da conta no projeto.
- Se a operação exige permissão de edição.
- Se o projeto está acessível pela credencial.

### A integração consulta, mas não consegue editar

Uma causa possível é que a conta possui permissão `viewer`.

**Solução:** solicitar ao proprietário a permissão `editor`, caso ela seja necessária.

---

## 8. Checklist de configuração

Antes de começar a trabalhar com o Scripta, confirme:

- [ ] Conta criada no Scripta.
- [ ] Login realizado com sucesso.
- [ ] Projeto identificado pelo nome e slug.
- [ ] Acesso solicitado ao proprietário.
- [ ] Permissão concedida à conta.
- [ ] API Key gerada.
- [ ] API Key armazenada com segurança.
- [ ] Permissões da integração verificadas.
- [ ] Projeto encontrado pela integração.
- [ ] Consulta à documentação realizada com sucesso.
- [ ] Permissão de escrita validada, se necessária.

---

## 9. Resumo do processo

```text
1. Criar conta no Scripta
          |
          v
2. Solicitar acesso ao projeto
          |
          v
3. Proprietário concede permissão
          |
          v
4. Gerar uma API Key
          |
          v
5. Verificar acesso da credencial
          |
          v
6. Configurar a integração
          |
          v
7. Listar projetos disponíveis
          |
          v
8. Validar o projeto desejado
          |
          v
9. Começar a utilizar o Scripta
```

---

## 10. Considerações finais

O processo de configuração do Scripta envolve duas responsabilidades principais:

**Usuário:**
- Criar sua conta.
- Solicitar participação em projetos.
- Gerar e proteger suas credenciais de integração.
- Validar o acesso necessário.

**Proprietário do projeto:**
- Gerenciar os membros do projeto.
- Conceder permissões adequadas.
- Garantir que somente pessoas autorizadas tenham acesso às informações.

Ao seguir essas orientações, a equipe poderá organizar o acesso à documentação e utilizar integrações com maior controle e segurança.

**Nota de validação:** Este guia considera os recursos identificados nas ferramentas de integração do Scripta. Antes de adotá-lo como procedimento oficial, devem ser confirmados no aplicativo os caminhos exatos para cadastro, emissão de chaves e eventual restrição de credenciais por projeto.
