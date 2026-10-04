# Fluxo e decisões da Sprint 2

Este documento registra o comportamento aprovado para a Sprint 2, de 05/10 a 25/10/2026. As funcionalidades descritas como planejadas ainda precisam ser implementadas; a existência de um campo no contrato ou no banco não comprova que seu fluxo já esteja funcionando.

Os épicos e as tarefas publicados no [projeto da Sprint 2](https://github.com/orgs/Titus-System/projects/13/views/6) são a referência de execução. A arquitetura geral está em [ARCHITECTURE.md](ARCHITECTURE.md), o esquema existente em [modelo-dados.dbml](database/modelo-dados.dbml) e as limitações dos dados em [ESCOPO-SIMULACAO.md](ESCOPO-SIMULACAO.md).

## 1. Ponto de partida implementado

- O formulário de núcleo fecha o fluxo de geração, execução em sandbox, comparação com o baseline e apresentação do resultado.
- O núcleo contém `vigencia`, `loja`, `marca`, `cargo` e `percentual`. Matrícula pode ser alvo de uma especificação; não é campo do núcleo.
- A representação já admite `faixa_valor`, `condicao_limiar`, `janela_datas`, `exclusao`, `bonus_fixo` e `generico`. O fluxo atual de entrada não produz essas especificações.
- O grafo ativo começa lendo uma regra já estruturada: `load_rule → code_generation → persist_response → extract_code → dispatch_execution → await_execution → decision`, com desvio condicional para `suggest_adaptation`.
- O codegen consome `regra-submetida` e `simulacao-concluida.codegen`. A API publica `parametros-confirmados`, mas o codegen ainda não o consome.
- A validação de domínio existe no caminho de adaptação; sua aplicação no fluxo principal ainda é trabalho da Sprint 2.
- O worker grava o resultado. A API consulta o artefato e atualiza o estado do job; não substitui o worker como produtor dos valores.
- O dataset publicado e os baselines abrangem agosto a dezembro de 2025. Julho existe na fonte bruta e está excluído da simulação.

## 2. Regra completa e fluxo de entrada

A Sprint 2 cobre a regra inteira descrita pelo usuário, com núcleo e todas as particularidades suportadas pelos dados. Todos os construtos estão no escopo. A integração inicial usa núcleo mais `generico`; essa sequência não exclui os outros construtos da entrega.

1. O usuário envia texto ou áudio.
2. A API registra a submissão original e acompanha o job. Quando houver áudio, chama o provedor de transcrição e persiste o texto.
3. O codegen lê o texto persistido e extrai uma representação completa.
4. A regra extraída passa por validação de domínio e de consistência.
5. Sem problemas apontados, o fluxo segue automaticamente para geração de código e simulação.
6. Havendo elementos incompletos, incoerentes ou não processáveis, o usuário é encaminhado ao chatbot para corrigir a regra.

O chatbot é uma interface de correção orientada pelos problemas encontrados. Não é uma conversa aberta nem uma tela obrigatória de confirmação de toda regra.

O código gerado continua não confiável e é executado exclusivamente pelo worker em sandbox. Cobertura declarada e asserções são verificações necessárias; a correção semântica dos construtos também precisa ser demonstrada por resultados esperados. Um elemento sem implementação válida impede a simulação integral.

## 3. Loop de correção e histórico

A cada rodada, o chatbot mostra os problemas e aceita uma correção por texto ou voz. O codegen reextrai a regra usando o contexto existente, produz uma versão nova e a revalida. O ciclo termina quando a regra fica processável, sem limite de tentativas.

### Persistência aprovada, ainda a implementar

- Uma tabela própria de rodadas, relacionada ao job e à versão da regra analisada.
- Conflitos armazenados como lista estruturada em `jsonb`, com o elemento e o motivo.
- Referência à submissão de correção e à versão resultante, quando existirem.
- Encadeamento entre rodadas por `rodada_anterior_id`.
- Cada correção registrada em uma submissão separada e imutável. Nenhuma submissão incorpora ou sobrescreve as anteriores.
- Preservação das versões anteriores da regra.
- Histórico completo apresentado no chatbot, incluindo problemas, correções e versões.
- Sair da tela preserva o estado corrente do job e a rodada pendente; o usuário pode retomá-la posteriormente. A saída da tela não equivale a cancelamento ou abandono persistido.

O contexto enviado à LLM combina a representação estruturada atual, o texto da correção corrente e o histórico textual anterior necessário para interpretar essa correção. O vínculo histórico fica nas rodadas; não exige copiar todo o histórico para cada submissão.

O SSE comunica o estado corrente e as atualizações. O histórico precisa ser consultável no banco, inclusive após uma reconexão; não pode depender das mensagens que permaneceram na memória do navegador.

### Coordenação entre serviços

A API recebe a correção e anuncia sua referência. O codegen propõe uma representação corrigida; a API persiste a versão e emite a confirmação que permite retomar o grafo. Os contratos estão definidos pela [T-200 A](https://github.com/Titus-System/synapse/issues/185): `correcao-submetida` leva a referência da submissão de correção ao codegen, `correcao-proposta` devolve à API a representação reextraída e `etapa-alterada` ganhou o campo opcional `conflitos`, mostrado pelo chatbot a cada rodada. Produtores e consumidores desses contratos ainda precisam ser implementados.

O consumo de `parametros-confirmados` precisa funcionar em qualquer rodada e ser idempotente, evitando duplicação de versões ou de efeitos em reentregas.

## 4. Áudio e transcrição

A API é responsável por chamar o provedor de ASR. O codegen consome somente o texto; não seleciona o binário nem chama o provedor.

A tabela `submissoes` já contém `binario`, `formato`, `transcricao` e `transcrito_em`. A permissão de leitura do codegen já existe. Essa estrutura atende ao armazenamento de áudio e transcrição, sem uma migration nova para esses campos.

A entrada inicial e as correções por voz usam a mesma infraestrutura de captura, armazenamento e transcrição. Cada áudio de correção pertence à sua própria submissão, vinculada à rodada correspondente. A submissão inicial permanece identificável.

O estado `aguardando_transcricao` já existe no contrato HTTP e precisa ser incluído no enum e nas transições da API como parte de E4. O áudio é persistido antes da chamada ao provedor; a disponibilidade da transcrição é anunciada somente depois da gravação do texto. Uma chamada externa não deve manter aberta a transação que grava o job e seu evento.

E4 pode ser desenvolvido em paralelo com E1–E3. O fechamento do caminho de correção por voz exige a integração com E3; a captura e a transcrição não dependem da implementação do chatbot para serem construídas.

## 5. Vendas e alternativas

O resultado deve ajudar o usuário a analisar a relação entre vendas e comissão. Os dados atuais não permitem estimar quanto as vendas aumentariam por causa de uma alteração na taxa de comissão.

### Funcionamento existente

Há uma tentativa automática de regra alternativa para o recorte suportado: regra somente de núcleo, sem especificações, quando os valores permitem ajustar seu percentual. A alternativa é uma versão nova e passa pela execução normal antes de poder ser aceita. Não existe uma sequência ilimitada de sugestões automáticas.

Esse mecanismo não garante uma alternativa para toda regra inviável e não deve ser apresentado como suporte já comprovado para adaptações de todos os construtos.

### Cenário de vendas planejado

E5 acrescenta uma leitura mantendo a regra e variando o volume de vendas. A premissa aprovada é uma taxa global uniforme aplicada proporcionalmente às vendas existentes: R$ 100 e R$ 200 tornam-se R$ 110 e R$ 220 sob crescimento de 10%. As proporções entre lojas, pessoas, marcas e competências são preservadas.

Esse resultado é um cenário hipotético, não uma previsão nem uma correlação causal. A taxa, as vendas e as comissões de cada candidato precisam ser apuradas por código determinístico no worker; o codegen coordena o processamento e apresenta referências ao resultado.

Não se pode prometer que aumentar vendas faça uma comissão caber em um orçamento absoluto fixo. Algumas regras aumentam o custo junto com as vendas; outras têm faixas, bônus ou descontinuidades. A busca precisa explicitar seu critério, intervalo e tratamento de ausência de solução. Bisseção só é adequada onde a condição pesquisada tiver a monotonicidade necessária.

A saída complementar está prevista na [T-200 B](https://github.com/Titus-System/synapse/issues/186). Ela é distinta da proposta de regra alternativa.

## 6. Rastreabilidade dos valores

O objetivo é permitir identificar quem receberia quanto, onde e quando. “Quando” é a competência mensal; a janela diária de Black Friday é uma particularidade suportada pelos dados de novembro e pelos elementos da regra.

### Resultado existente

`resultados_simulacao` armazena `totais`, `assercoes` e `decomposicao`. As cinco quebras atuais — elemento, loja, marca, cargo e competência — são mapas independentes de diferenças contra o baseline. Elas não contêm o valor absoluto por colaborador nem as linhas resultantes da apuração.

Guardar agregados por dimensão não permite reconstruir quanto uma pessoa receberia em uma determinada loja e competência. Uma declaração de cobertura por elemento também não prova sozinha que a aritmética da regra está correta.

### Evolução prevista

- E9 e a [T-200 C](https://github.com/Titus-System/synapse/issues/187) incluem matrícula e valores absolutos, preservando as quebras de diferença existentes.
- A necessidade de preservar os dataframes resultantes da simulação faz parte do planejamento.
- Ainda deve ser confirmado se a consulta exige apenas totais independentes ou linhas que relacionem matrícula, loja e competência. A escolha determina a granularidade e o contrato de persistência; os agregados da T-200 C não resolvem automaticamente esse cruzamento.
- O worker produz, verifica e persiste os resultados. O codegen ajusta a geração para produzi-los; a API consulta e expõe; o frontend apresenta sem calcular os valores.
- Dados detalhados ficam no armazenamento, referenciados pelos eventos. Não devem ser enviados integralmente pelo RabbitMQ nem registrados nos logs.

O formato de armazenamento dos dataframes e a consulta dos detalhes serão definidos tecnicamente a partir da granularidade confirmada.

## 7. Campanhas, nomes e navegação

“Campanha” é a apresentação de um job com resultado final válido e veredito viável. Neste escopo, não é uma entidade nova que agrupa vários jobs. O job técnico continua existindo mesmo quando não há campanha válida.

- A campanha reúne as versões da regra, suas simulações e seus resultados.
- A versão nova proveniente de sugestão substitui a anterior como regra vigente, preservando as anteriores no histórico.
- Uma simulação viável oferece a opção de salvar na finalização; essa tela encaminha para salvos.
- Se a regra for inviável e o usuário não seguir com a sugestão, ela não é salva como campanha e permanece acessível na lista de conversas do menu lateral.
- A tela de salvos leva ao relatório e não exibe status.
- Os filtros de loja, marca, cargo e vigência devem admitir múltiplas seleções.
- A tela de progresso da simulação deve perder o scroll sem necessidade.

### Nome e fallback

E8 prevê uma coluna nullable `jobs.nome`, editável a partir da lista, e o mesmo campo opcional nos dois formatos HTTP: `JobResumo` e `JobDetalhado`. São duas projeções do mesmo nome, não duas colunas de banco.

O nome definido pelo usuário tem prioridade. Sem ele, o fallback são os primeiros 50 caracteres do texto inicial ou da transcrição do áudio inicial; entradas mais curtas aparecem integralmente. Correções e novas versões não mudam a fonte do fallback. Entradas com prefixos iguais podem ter o mesmo nome padrão.

A mudança de contrato está na [T-200 D](https://github.com/Titus-System/synapse/issues/188). A coluna e o fluxo de renomear ainda precisam ser implementados. A disponibilidade do fallback de voz depende da transcrição.

## 8. Autocadastro e recuperação de senha

E11 utiliza os fluxos nativos do Keycloak para cadastro, verificação de e-mail e redefinição de senha. O autocadastro atribui somente o papel de negócio `profissional-rh`; não oferece escolha de auditor ou administrador.

A API mantém o provisionamento local por `usuarios.keycloak_sub`. Recuperar a senha preserva essa identidade e a posse das regras e campanhas. Senhas e tokens de recuperação não passam a ser armazenados pela API.

O envio de e-mails, o remetente, as URLs de retorno e a aplicação das configurações em realms existentes são parte da entrega. Esses recursos ainda não estão habilitados na configuração atual do realm.

## 9. Pendências do ciclo de vida

As tarefas [T-201](https://github.com/Titus-System/synapse/issues/200), [T-202](https://github.com/Titus-System/synapse/issues/201), [T-203](https://github.com/Titus-System/synapse/issues/202) e [T-204](https://github.com/Titus-System/synapse/issues/203) tratam de motivos e campos do HTTP, contrato de diagnóstico, armazenamento do diagnóstico e persistência das falhas pelo worker. Os problemas documentados não devem ser tratados como já corrigidos apenas porque as tarefas foram publicadas.

A limpeza de checkpoints após o encerramento definitivo usa o evento `job-encerrado` da API e o registro `jobs_grafo_encerrados` do codegen, que permanece depois da remoção e mantém a deduplicação dos ciclos. Um ciclo que ainda espera um resultado só é removido depois de processá-lo (DEC-095).

`aguardando_transcricao` pertence a E4 e o consumo de `parametros-confirmados` pertence a E3. Não são decisões de escopo pendentes.

## 10. Questões ainda abertas

- **Cliente/PO:** basta consultar totais por dimensão ou é necessário relacionar matrícula, loja e competência na mesma linha?
- **Dom Rock:** existe evidência adicional que permita relacionar mudanças de comissão com mudanças de vendas por funcionário?
- **Técnicas:** seleção do provedor de ASR, ordem de implementação dos construtos, desenho da busca de vendas e persistência dos detalhes.

As decisões de armazenamento de áudio, modalidade das correções, histórico do chatbot, ausência de limite de tentativas, fallback de nome e inclusão dos construtos já estão tomadas.

## Referências de execução

- [E1: extração](https://github.com/Titus-System/synapse/issues/190), [E2: validação](https://github.com/Titus-System/synapse/issues/191), [E3: chatbot](https://github.com/Titus-System/synapse/issues/192) e [E4: voz](https://github.com/Titus-System/synapse/issues/193).
- [E5: adaptação e vendas](https://github.com/Titus-System/synapse/issues/194), [E7: prova de geração e execução](https://github.com/Titus-System/synapse/issues/196) e [T-299: integração ponta a ponta](https://github.com/Titus-System/synapse/issues/195).
- [E8: nomes](https://github.com/Titus-System/synapse/issues/197), [E9: resultados](https://github.com/Titus-System/synapse/issues/198), [E10: campanhas](https://github.com/Titus-System/synapse/issues/199) e [E11: acesso](https://github.com/Titus-System/synapse/issues/189).
