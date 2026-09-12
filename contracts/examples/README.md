# Exemplos válidos

Um exemplo por schema de `contracts/`, com a mesma estrutura de diretórios. É o que os testes de cada componente desserializam nos DTOs da sua stack (ADR-002): o exemplo prova que o schema e o DTO descrevem a mesma coisa.

Como todo `contracts/`, isto é insumo de build e nunca dependência de runtime.

| Exemplo | Schema | O que cobre |
| --- | --- | --- |
| [domain/representacao-regra.json](domain/representacao-regra.json) | `domain/representacao-regra.schema.json` | Regra só com o núcleo, que é o alcance da Sprint 1 |
| [domain/representacao-regra-elementos.json](domain/representacao-regra-elementos.json) | `domain/representacao-regra.schema.json` | Faixa de valor, janela de datas e exclusão, sem alteração do schema |
| [domain/representacao-regra-generico.json](domain/representacao-regra-generico.json) | `domain/representacao-regra.schema.json` | Elemento que não corresponde a nenhum construto reconhecido |
| [domain/resultado-simulacao.json](domain/resultado-simulacao.json) | `domain/resultado-simulacao.schema.json` | Totais, asserções e as cinco quebras da decomposição |

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
