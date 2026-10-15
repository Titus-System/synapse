# Extração e aplicação de correções — T-220

O motor síncrono aplica operações sobre uma versão existente sem chamar modelo,
banco, grafo ou broker. `reextracao.reextrair_regra` chama o modelo e entrega suas
operações a esse motor. A integração ao nó do grafo pertence à T-221.

## Chamada assíncrona ao modelo

```python
async def reextrair_regra(
    representacao: RepresentacaoRegra,
    parametros: dict[str, ValorRegra],
    conflitos: Sequence[Mapping[str, object]],
    texto_correcao: str,
    competencias_publicadas: Sequence[str],
    *,
    modelo: BaseChatModel,
    metadados_modelo: dict[str, Any],
) -> ResultadoReextracao: ...
```

O resultado contém `representacao`, `parametros` completos, `rebaixamentos` (a
união dos diagnósticos definida abaixo) e `chamada: ChamadaExtracao`. A chamada
preserva prompt, resposta original, cópia independente dos metadados e consumo de
tokens quando informado, para futura auditoria. As dataclasses de resultado e
chamada não expõem esses conteúdos em `repr`.

O prompt separa instruções fixas, contexto estruturado da regra/parâmetros/conflitos
e texto da correção identificado como não confiável. Textos do contexto também
não são comandos. O modelo recebe o schema fechado, sem ferramentas vinculadas.
A resposta é lida com `simplejson`, `use_decimal=True`, rejeição de NaN e de chaves
duplicadas inclusive em objetos aninhados; depois passa ao aplicador determinístico.

Texto vazio, resposta vazia/bloqueada/truncada, JSON inválido, envelope incompatível
ou falha de validação do resultado geram `FalhaExtracaoError`, derivada de
`FalhaDoJobError`, com etapa `extracao_parametros`. Operações recuperáveis continuam
como diagnósticos, sem transformar todo o lote em falha permanente.

Exceções da chamada ao provedor viram `FalhaChamadaReextracaoError` (RuntimeError,
não FalhaDoJobError), sem mensagem original, causa ou contexto de exceção. Essa
sanitização não classifica códigos do provedor: inclusive erros de configuração
ou schema rejeitado precisam ser diagnosticados na integração operacional.
Cancelamento assíncrono é propagado. O motor não implementa retry próprio.

Não existe serialização de diagnósticos para banco/eventos neste módulo. A
pendência contratual abaixo permanece para a integração, sem bloquear a chamada
e aplicação em memória.

## Interface

```python
from app.extracao.correcao import aplicar_operacoes_correcao, ResultadoCorrecao

def aplicar_operacoes_correcao(
    representacao: RepresentacaoRegra,
    parametros: dict[str, ValorRegra],
    operacoes: object,
    competencias_publicadas: Sequence[str],
    *,
    texto_correcao: str = "",
) -> ResultadoCorrecao: ...
```

- `representacao`: versão atual validada; os `ref` precisam ser únicos.
- `parametros`: conjunto completo atual, validado por `validar_parametros`.
- `operacoes`: envelope Python desserializado `{"operacoes": [...]}`. Não aceita
  texto JSON. Use `Decimal` para números fracionários, conforme `ValorRegra`; a
  integração deve desserializar sem perda de precisão e recusar chaves duplicadas.
- `competencias_publicadas`: contexto explícito para o chamador; não restringe nem
  preenche os parâmetros. Todas as operações já levam valores absolutos, sem
  resolução de período. T-277 permite meses fora das competências publicadas para
  a validação de domínio apontá-los depois. Novembro pode substituir agosto e
  setembro mesmo que não conste dos parâmetros atuais.
- `texto_correcao`: necessário para conferir o lastro dos rascunhos adicionados ou
  substituídos, reaproveitando a T-203. Ausência de trecho literal segue os mesmos
  rebaixamentos da extração inicial. Não há conferência adicional da T-224 nem
  lastro novo para as operações diretas de núcleo e parâmetros.

O retorno é uma tupla de três posições:

```python
type ResultadoCorrecao = tuple[
    RepresentacaoRegra,
    dict[str, ValorRegra],
    list[Rebaixamento | DiagnosticoOperacao],
]
```

A primeira posição é a regra corrigida. A segunda contém os parâmetros completos,
inclusive os que não foram mencionados. A terceira contém diagnósticos desta
aplicação: primeiro as operações ignoradas, na ordem de entrada, depois os
rebaixamentos dos elementos produzidos que sobrevivem, na ordem final da regra.
Não reconstrói rebaixamentos históricos dos genéricos já presentes na entrada.

**A lista de diagnósticos não pode ser persistida diretamente no contrato de
rebaixamentos da extração.** Veja a decisão pendente abaixo.

## Schema das operações

`app.extracao.schema_correcao.schema_operacoes_correcao()` produz um JSON Schema
fechado. Envelope: somente `operacoes`, obrigatório, array não vazio. Cada item
tem `tipo` como discriminador e somente os campos indicados:

| Tipo | Campos obrigatórios além de `tipo` | Semântica |
| --- | --- | --- |
| `definir_nucleo` | `campo`, `valor` | Define percentual, vigencia, loja, marca ou cargo. |
| `substituir_elemento` | `ref`, `elemento` | Monta o substituto na posição do original. |
| `remover_elemento` | `ref` | Remove somente o elemento referido. |
| `adicionar_elemento` | `elemento` | Monta e acrescenta ao final. |
| `definir_parametro` | `campo`, `valor` | Define orcamento, meta_venda ou competencias. |
| `remover_parametro` | `campo` | Remove um desses três parâmetros por ausência. |

`percentual`, `orcamento` e `meta_venda` são números, sem restrições de coerência.
`vigencia` contém `inicio` e `fim` no formato `AAAA-MM`; filtros de loja/marca/cargo
são arrays de strings, inclusive vazios. `competencias` é um array não vazio de
`AAAA-MM`. `null` não define nem remove valores. A remoção de `competencias`
restaura a semântica de período padrão por ausência, sem materializá-lo no motor.

`ref` tem o formato `elem.<dígitos>`, compatível com a representação existente.
`elemento` é o rascunho da T-203, com `construto_pretendido`, `descricao` e `trecho`,
acrescido dos campos do registro `CONSTRUTOS_HABILITADOS`. Campos numéricos de
construtos habilitados usam `{valor, trecho}`, como na extração inicial.

```json
{
  "operacoes": [
    {"tipo": "definir_nucleo", "campo": "percentual", "valor": 0.03},
    {"tipo": "definir_parametro", "campo": "orcamento", "valor": 600000},
    {"tipo": "remover_parametro", "campo": "meta_venda"},
    {"tipo": "definir_parametro", "campo": "competencias", "valor": ["2025-11"]}
  ]
}
```

O schema para orientar o modelo é estrito. A aplicação valida separadamente o
envelope e cada operação: um item desconhecido, com campos extras ou valor inválido
é ignorado, sem perder os demais. Rascunhos de elementos passam pela recuperação
da T-203: quando recuperáveis, viram `generico`; quando irrecuperáveis, a operação
é ignorada. Um lote não vazio composto somente por operações ignoradas devolve a
regra e os parâmetros preservados, com diagnósticos. Detectar proposta sem mudança
continua sendo responsabilidade da integração do loop.

Assim, “operação fora do schema” não implica falha permanente de todo o lote. A
falha global se limita ao envelope inutilizável. Esta separação segue a orientação
explícita da tarefa e da skill de correction-loop.

## Invariantes e falhas

- A ordem de aplicação é a ordem da lista; a última definição válida de um campo
  prevalece. Uma operação inválida não desfaz definições válidas anteriores.
- Referências são as da versão original durante todo o lote. Um elemento
  substituído continua endereçável pelo `ref` original. Um removido deixa de existir;
  adicionados não podem ser endereçados no mesmo lote, pois o modelo não atribui refs.
- A renumeração ocorre somente no final: `elem.1`, `elem.2`, etc. Os rebaixamentos
  sobreviventes recebem a referência final; os de elementos removidos ou
  novamente substituídos são descartados.
- Regra, parâmetros, operações e competências recebidos não são modificados.
  As estruturas mutáveis retornadas são independentes das entradas.
- Nada é interpretado, importado ou executado a partir dos dados do modelo.
- Núcleo e parâmetros não mencionados são preservados. Nenhuma incoerência é
  corrigida automaticamente. O motor não consulta E2.
- A regra final passa por `RepresentacaoRegra`; os parâmetros finais passam por
  `validar_parametros`. Operações diretas também validam o candidato antes de aplicá-lo.
- `FalhaExtracaoError("Envelope de correção inválido")`: envelope ausente, vazio,
  com propriedades extras, sem array de operações ou com array vazio. A mensagem
  não contém o payload e a exceção não encadeia erro de schema com dados privados.
- `FalhaExtracaoError("Referências da regra atual ambíguas")`: refs duplicados na
  entrada. Ambas as falhas usam a etapa `extracao_parametros`.
- `ValueError`/`pydantic.ValidationError`: entradas atuais inválidas ou falha na
  validação final. A representação de entrada deve ter sido validada pelo chamador.
  Falhas individuais recuperáveis são convertidas em diagnósticos internos.

## Montagem compartilhada e diagnósticos

`montagem.montar_elemento` foi extraída de `motor._montar` e é usada tanto pela
extração inicial quanto pela correção. Mantém o registro, schema, conversão,
lastro numérico/literal, validação do construto e rebaixamento da T-203.

Rebaixamentos dessa montagem continuam sendo `Rebaixamento` e conservam o
vocabulário existente. Para operações ignoradas, usa-se o tipo local:

```python
@dataclass(frozen=True, slots=True)
class DiagnosticoOperacao:
    indice: int  # Posição da operação no lote, começando em 1.
    motivo: Literal["operacao_invalida", "referencia_inexistente"]
```

Esse tipo não tem `para_contrato`, não retém payload ou texto e não é um subtipo de
`Rebaixamento`. Não deve ser passado a `validar_conteudo`, usado na extração inicial:
esse validador exige correspondência de todos os genéricos da regra com seus
rebaixamentos, enquanto a correção recebe uma regra pronta sem seu histórico.

### Decisão pendente de contrato

`contracts/domain/rebaixamentos-extracao.schema.json` tem motivos fechados e permite
apenas referências de elementos ou parâmetros. Um tipo desconhecido ou referência
ausente não é semanticamente `campo_obrigatorio_ausente` nem
`construto_nao_habilitado`.

Proposta para decisão: permitir `operacao_invalida` e `referencia_inexistente`, com
referência da operação (`operacoes.<posição>`) ou um objeto de diagnóstico próprio.
O motivo novo sozinho não basta: é preciso definir o alvo e a semântica de refs
para elementos inexistentes, removidos ou renumerados.

Uma ampliação exigiria autorização para modificar o schema compartilhado, exemplos,
tipos/serialização do codegen e validação/persistência consumida pela api, além da
documentação e dos testes dos consumidores relevantes. O produtor seria codegen;
api seria o consumidor de persistência, e qualquer exposição posterior ao frontend
precisaria ser avaliada. O risco é um consumidor antigo rejeitar os novos motivos
ou referências: aceitar valores novos não garante compatibilidade com validadores
antigos. Nenhum desses contratos ou consumidores foi alterado nesta etapa.

A alternativa implementada mantém os diagnósticos em memória e reaproveita
`Rebaixamento` somente onde seu significado é válido. A integração de persistência
deve decidir o destino auditável antes de tentar persistir a lista completa.

## Integração seguinte

O chamador deve obter a versão e parâmetros atuais, conflitos e texto e fornecer
as competências publicadas a `reextrair_regra`. O resultado contém o conjunto
completo de parâmetros, nunca um patch. Nó, armazenamento, publicação e telemetria
do fluxo permanecem fora da T-220. Os módulos de extração não emitem logs ou métricas;
exportação e coleta não foram verificadas nesta entrega. Antes de ativar o fluxo
na aplicação, a integração precisa satisfazer os critérios de observabilidade
do AGENTS, incluindo sucesso, falha, duração e correlação.
