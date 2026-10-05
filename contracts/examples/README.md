# Exemplos válidos

Um exemplo por schema de `contracts/`, com a mesma estrutura de diretórios. É o que os testes de cada componente desserializam nos DTOs da sua stack (ADR-002): o exemplo prova que o schema e o DTO descrevem a mesma coisa.

Como todo `contracts/`, isto é insumo de build e nunca dependência de runtime.

| Exemplo | Schema | O que cobre |
| --- | --- | --- |
| [domain/representacao-regra.json](domain/representacao-regra.json) | `domain/representacao-regra.schema.json` | Regra só com o núcleo, que é o alcance da Sprint 1 |
| [domain/representacao-regra-elementos.json](domain/representacao-regra-elementos.json) | `domain/representacao-regra.schema.json` | Faixa de valor, janela de datas e exclusão, sem alteração do schema |
| [domain/representacao-regra-generico.json](domain/representacao-regra-generico.json) | `domain/representacao-regra.schema.json` | Elemento que não corresponde a nenhum construto reconhecido |
| [domain/conflitos-rodada.json](domain/conflitos-rodada.json) | `domain/conflitos-rodada.schema.json` | Conflitos de uma rodada de correção: um campo ausente e um conflito entre núcleo e exclusão |
| [domain/resultado-simulacao.json](domain/resultado-simulacao.json) | `domain/resultado-simulacao.schema.json` | Totais, asserções e as cinco quebras da decomposição |
| [domain/resultado-diagnostico-excecao.json](domain/resultado-diagnostico-excecao.json) | `domain/resultado-diagnostico.schema.json` | Exceção da regra, com a falha estruturada que o sandbox capturou |
| [domain/resultado-diagnostico-timeout.json](domain/resultado-diagnostico-timeout.json) | `domain/resultado-diagnostico.schema.json` | Execução encerrada por prazo: só a causa, sem falha nem traceback |
| [domain/resultado-diagnostico-fora-do-schema.json](domain/resultado-diagnostico-fora-do-schema.json) | `domain/resultado-diagnostico.schema.json` | Resultado que não valida contra o schema: caminhos e palavras-chave, sem os valores rejeitados |
| [domain/resultado-diagnostico-cobertura-incompleta.json](domain/resultado-diagnostico-cobertura-incompleta.json) | `domain/resultado-diagnostico.schema.json` | Cobertura incompleta: a causa e o elemento exigido que o código não declarou, sem falha nem problemas |
| [events/executar-codigo-cobertura.json](events/executar-codigo-cobertura.json) | `events/executar-codigo.schema.json` | Comando com os elementos que a regra exige, para o worker conferir a cobertura; `executar-codigo.json` é o mesmo comando sem o campo, que segue executado sem a conferência |
| [events/parametros-confirmados.json](events/parametros-confirmados.json) | `events/parametros-confirmados.schema.json` | Versão pronta para abrir o ciclo do codegen, com as competências e o orçamento do job |
| [events/etapa-alterada.json](events/etapa-alterada.json) | `events/etapa-alterada.schema.json` | Progresso sem conflitos: o campo `conflitos` ausente |
| [events/etapa-alterada-conflitos.json](events/etapa-alterada-conflitos.json) | `events/etapa-alterada.schema.json` | Pausa para correção: a versão analisada e os conflitos que o chatbot mostra ao usuário, com os elementos envolvidos e o motivo |
| [events/etapa-alterada-falha-reextracao.json](events/etapa-alterada-falha-reextracao.json) | `events/etapa-alterada.schema.json` | Falha da reextração de uma correção, que reabre a rodada em vez de encerrar o job |
| [events/correcao-submetida.json](events/correcao-submetida.json) | `events/correcao-submetida.schema.json` | Correção enviada pelo chatbot, por referência à submissão, com as competências do job |
| [events/correcao-proposta.json](events/correcao-proposta.json) | `events/correcao-proposta.schema.json` | Regra reextraída da correção, no corpo, ainda sem linha em `regras` |
| [events/job-encerrado.json](events/job-encerrado.json) | `events/job-encerrado.schema.json` | Encerramento por decisão do usuário (`liberado`) |
| [events/job-encerrado-erro.json](events/job-encerrado-erro.json) | `events/job-encerrado.schema.json` | Encerramento por falha (`erro`) |
| [events/regra-extraida.json](events/regra-extraida.json) | `events/regra-extraida.schema.json` | Primeira versão extraída de uma transcrição, no corpo, com exclusão e elemento genérico, ainda sem linha em `regras` |

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
