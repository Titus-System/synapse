# Exemplos válidos

Um exemplo por schema de `contracts/`, com a mesma estrutura de diretórios. É o que os testes de cada componente desserializam nos DTOs da sua stack (ADR-002): o exemplo prova que o schema e o DTO descrevem a mesma coisa.

Como todo `contracts/`, isto é insumo de build e nunca dependência de runtime.

| Exemplo | Schema | O que cobre |
| --- | --- | --- |
| [domain/representacao-regra.json](domain/representacao-regra.json) | `domain/representacao-regra.schema.json` | Regra só com o núcleo, que é o alcance da Sprint 1 |
| [domain/representacao-regra-elementos.json](domain/representacao-regra-elementos.json) | `domain/representacao-regra.schema.json` | Faixa de valor, janela de datas e exclusão, sem alteração do schema |
| [domain/representacao-regra-generico.json](domain/representacao-regra-generico.json) | `domain/representacao-regra.schema.json` | Elemento que não corresponde a nenhum construto reconhecido |
| [domain/conflitos-rodada.json](domain/conflitos-rodada.json) | `domain/conflitos-rodada.schema.json` | Conflitos de uma rodada de correção: um campo ausente e um conflito entre núcleo e exclusão |
| [domain/conflitos-rodada-parametros.json](domain/conflitos-rodada-parametros.json) | `domain/conflitos-rodada.schema.json` | Conflitos sobre os parâmetros da simulação: orçamento negativo, meta zero e competência sem dados publicados, sem o valor dito no motivo |
| [domain/parametros-simulacao.json](domain/parametros-simulacao.json) | `domain/parametros-simulacao.schema.json` | Orçamento, meta de venda e período ditos no texto |
| [domain/parametros-simulacao-vazio.json](domain/parametros-simulacao-vazio.json) | `domain/parametros-simulacao.schema.json` | Texto que não diz nenhum parâmetro |
| [domain/resultado-simulacao.json](domain/resultado-simulacao.json) | `domain/resultado-simulacao.schema.json` | Totais, asserções e as cinco quebras da decomposição |
| [domain/resultado-linhas.json](domain/resultado-linhas.json) | `domain/resultado-linhas.schema.json` | Apuração por competência e matrícula, na lotação do RH: linha sem alteração, aumento percentual e bônus individual |
| [domain/resultado-diagnostico-resultado-incoerente.json](domain/resultado-diagnostico-resultado-incoerente.json) | `domain/resultado-diagnostico.schema.json` | Detalhamento que não fecha com totais ou quebras, recusado fora do container, sem exceção capturada |
| [domain/resultado-diagnostico-excecao.json](domain/resultado-diagnostico-excecao.json) | `domain/resultado-diagnostico.schema.json` | Exceção da regra, com a falha estruturada que o sandbox capturou |
| [domain/resultado-diagnostico-timeout.json](domain/resultado-diagnostico-timeout.json) | `domain/resultado-diagnostico.schema.json` | Execução encerrada por prazo: só a causa, sem falha nem traceback |
| [domain/resultado-diagnostico-fora-do-schema.json](domain/resultado-diagnostico-fora-do-schema.json) | `domain/resultado-diagnostico.schema.json` | Resultado que não valida contra o schema: caminhos e palavras-chave, sem os valores rejeitados |
| [domain/resultado-diagnostico-cobertura-incompleta.json](domain/resultado-diagnostico-cobertura-incompleta.json) | `domain/resultado-diagnostico.schema.json` | Cobertura incompleta: a causa e o elemento exigido que o código não declarou, sem falha nem problemas |
| [events/executar-codigo-cobertura.json](events/executar-codigo-cobertura.json) | `events/executar-codigo.schema.json` | Comando com os elementos que a regra exige, para o worker conferir a cobertura; `executar-codigo.json` é o mesmo comando sem o campo, que segue executado sem a conferência |
| [events/parametros-confirmados.json](events/parametros-confirmados.json) | `events/parametros-confirmados.schema.json` | Versão pronta para abrir o ciclo do codegen, com as competências e o orçamento do job |
| [events/parametros-confirmados-meta-venda.json](events/parametros-confirmados-meta-venda.json) | `events/parametros-confirmados.schema.json` | Versão gravada a partir de uma correção, com a meta de venda do job |
| [events/regra-submetida-texto.json](events/regra-submetida-texto.json) | `events/regra-submetida.schema.json` | Primeira publicação da origem texto, antes da extração: sem orçamento, sem meta e com todas as competências publicadas |
| [events/regra-submetida-voz.json](events/regra-submetida-voz.json) | `events/regra-submetida.schema.json` | Primeira publicação da origem voz, sem orçamento/meta e com todas as competências publicadas |
| [events/regra-submetida-parametros.json](events/regra-submetida-parametros.json) | `events/regra-submetida.schema.json` | Origem texto republicada com a versão extraída e com o orçamento, a meta e o período que o texto disse |
| [events/etapa-alterada.json](events/etapa-alterada.json) | `events/etapa-alterada.schema.json` | Progresso sem conflitos: o campo `conflitos` ausente |
| [events/etapa-alterada-conflitos.json](events/etapa-alterada-conflitos.json) | `events/etapa-alterada.schema.json` | Pausa para correção: a versão analisada e os conflitos que o chatbot mostra ao usuário, com os elementos envolvidos e o motivo |
| [events/etapa-alterada-falha-reextracao.json](events/etapa-alterada-falha-reextracao.json) | `events/etapa-alterada.schema.json` | Falha da reextração de uma correção, que reabre a rodada em vez de encerrar o job |
| [events/correcao-submetida.json](events/correcao-submetida.json) | `events/correcao-submetida.schema.json` | Correção enviada pelo chatbot, por referência à submissão, com as competências do job |
| [events/correcao-submetida-parametros.json](events/correcao-submetida-parametros.json) | `events/correcao-submetida.schema.json` | Correção com os parâmetros atuais do job, entre eles uma competência fora das publicadas |
| [events/etapa-alterada-conflitos-parametros.json](events/etapa-alterada-conflitos-parametros.json) | `events/etapa-alterada.schema.json` | Pausa para correção de orçamento, meta e período, validada pela referência ao schema de conflitos |
| [events/correcao-proposta.json](events/correcao-proposta.json) | `events/correcao-proposta.schema.json` | Regra reextraída da correção, no corpo, ainda sem linha em `regras`; sem `parametros`, os do job não mudam |
| [events/correcao-proposta-parametros.json](events/correcao-proposta-parametros.json) | `events/correcao-proposta.schema.json` | Correção do período, com o conjunto completo de parâmetros depois dela |
| [events/job-encerrado.json](events/job-encerrado.json) | `events/job-encerrado.schema.json` | Encerramento por decisão do usuário (`liberado`) |
| [events/job-encerrado-erro.json](events/job-encerrado-erro.json) | `events/job-encerrado.schema.json` | Encerramento por falha (`erro`) |
| [events/regra-extraida.json](events/regra-extraida.json) | `events/regra-extraida.schema.json` | Referências ao job, à submissão e ao artefato em `extracoes_regras`, sem representação no corpo |
| [domain/rebaixamentos-extracao.json](domain/rebaixamentos-extracao.json) | `domain/rebaixamentos-extracao.schema.json` | Motivos de conversão de elementos para genérico, armazenados fora da representação |
| [domain/rebaixamentos-extracao-parametros.json](domain/rebaixamentos-extracao-parametros.json) | `domain/rebaixamentos-extracao.schema.json` | Códigos fora do vocabulário ou ambíguos, e parâmetros da simulação sem lastro ou com período não resolvido |

Schema alterado mantém pelo menos um exemplo válido atualizado na mesma mudança.

## Validação

O `manifesto.json` associa cada exemplo ao schema correspondente. Para validar
todos os exemplos localmente:

```bash
python -m pip install --requirement contracts/requirements.txt
python contracts/validar-exemplos.py
```

O script retorna código diferente de zero e identifica o arquivo e o campo
quando um exemplo não atende ao schema correspondente.

O mesmo comando valida a estrutura de `contracts/http/openapi.yaml` e seus exemplos
de schemas, parâmetros, requisições e respostas. Os exemplos HTTP são conferidos
por `$ref` ao schema no documento original, incluindo referências aos schemas de
domínio; não há cópias dos schemas para testes. Exemplos reutilizados por `$ref`
também são resolvidos antes da validação.
No exemplo SSE, o JSON de cada campo `data:` é validado contra o schema do evento;
os comentários de heartbeat não são dados do evento.

Na T-251, os exemplos de `GET /jobs` e `GET /jobs/{id}` cobrem nome definido pelo
usuário, nome padrão e ausência de nome. `PUT /jobs/{id}/nome` inclui requisições,
resposta com o nome gravado e recusas. As regras de normalização e persistência
serão exercitadas na implementação da API (T-253).

Para conferir que o validador rejeita exemplos inválidos e referências quebradas:

```bash
python contracts/testar-validador.py
```
