# Extração e aplicação de correções — T-220/T-224

`reextracao.reextrair_regra` pede ao modelo as operações que uma correção faz sobre a regra e os parâmetros atuais, e `correcao.aplicar_operacoes_correcao` as aplica de forma determinística. Nenhum dos dois acessa banco, grafo ou broker. O nó do grafo que os chama, a persistência e a publicação pertencem à T-221.

## Chamada ao modelo

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
    historico: Sequence[CorrecaoAnterior] = (),
) -> ResultadoReextracao: ...
```

O resultado contém `representacao`, os `parametros` completos, `rebaixamentos` (a união dos diagnósticos definida abaixo) e `chamada: ChamadaExtracao`. A chamada guarda o prompt, a resposta original, uma cópia independente dos metadados e o consumo de tokens quando o provedor o informa, para a auditoria. As dataclasses de resultado e de chamada não expõem esses conteúdos em `repr`.

O prompt separa as instruções fixas, o contexto estruturado da regra, dos parâmetros e dos conflitos, e o texto da correção, identificado como não confiável. Na T-224, o histórico (textos e conflitos das rodadas anteriores) fica **exclusivamente** em `dados_nao_confiaveis_da_correcao.historico`, em ordem cronológica. Ausência de histórico mantém apenas a chave `texto`, como na T-220. O histórico é contexto interpretativo, nunca fonte de lastro para valores novos. Os textos do contexto também não são comandos. O modelo recebe o schema fechado, sem ferramentas vinculadas. A resposta é lida com `simplejson`, com `use_decimal=True`, recusando NaN e chaves duplicadas, inclusive em objetos aninhados, e depois passa ao aplicador.

Texto vazio, resposta vazia, bloqueada ou truncada, JSON inválido, envelope incompatível ou falha na validação do resultado geram `FalhaExtracaoError`, derivada de `FalhaDoJobError`, com etapa `extracao_parametros`. Uma operação recuperável vira diagnóstico, sem tornar o lote inteiro uma falha permanente.

A exceção da chamada ao provedor sobe como veio. `chamar_com_espera_do_provedor` (T-268) a classifica pelo tipo e pelo código ao percorrer a cadeia de causas, espera quando o provedor está indisponível e lança a falha final sem a causa encadeada. Embrulhar a exceção aqui apagaria o código e transformaria um 503 numa reentrega imediata. O cancelamento assíncrono também sobe. O motor não tem retry próprio.

## Interface do aplicador

```python
def aplicar_operacoes_correcao(
    representacao: RepresentacaoRegra,
    parametros: dict[str, ValorRegra],
    operacoes: object,
    competencias_publicadas: Sequence[str],
    *,
    texto_correcao: str,
) -> ResultadoCorrecao: ...
```

- `representacao`: a versão atual validada, com `ref` únicos.
- `parametros`: o conjunto completo atual, validado por `validar_parametros`.
- `operacoes`: o envelope já desserializado, `{"operacoes": [...]}`, e não o texto JSON. Números fracionários chegam como `Decimal`, conforme `ValorRegra`.
- `competencias_publicadas`: resolvem o ano que o trecho não diz, como na extração inicial. Não filtram nem preenchem os parâmetros: um período fora delas é aceito, para a validação de domínio apontá-lo (T-277). "Simula só novembro" pode levar o período a um mês que o job não tinha.
- `texto_correcao`: a fonte do lastro de todo valor novo, nas operações de núcleo, de parâmetro e de elemento.

O retorno é uma tupla de três posições:

```python
type ResultadoCorrecao = tuple[
    RepresentacaoRegra,
    dict[str, ValorRegra],
    list[Rebaixamento | DiagnosticoOperacao],
]
```

A primeira posição é a regra corrigida, e a segunda, os parâmetros completos, inclusive os que a correção não mencionou. A terceira tem os diagnósticos desta aplicação: primeiro as operações não aplicadas, na ordem de entrada, depois os rebaixamentos dos elementos produzidos que sobreviveram, na ordem final da regra. Os rebaixamentos históricos dos genéricos que a regra já tinha não são reconstruídos.

## Schema das operações

`schema_correcao.schema_operacoes_correcao()` produz um JSON Schema fechado. O envelope tem só `operacoes`, obrigatório, um array que pode ser vazio. Cada item tem `tipo` como discriminador, exige também `trecho` (citação literal não vazia do texto **corrente**, inclusive em remoções) e só os campos adicionais indicados:

| Tipo | Campos obrigatórios além de `tipo` e `trecho` | Semântica |
| --- | --- | --- |
| `definir_nucleo` | `campo`, `valor` | Define percentual, vigencia, loja, marca ou cargo. |
| `substituir_elemento` | `ref`, `elemento` | Monta o substituto na posição do original. |
| `remover_elemento` | `ref` | Remove só o elemento referido. |
| `adicionar_elemento` | `elemento` | Monta e acrescenta ao final. |
| `definir_parametro` | `campo`, `valor` | Define orcamento, meta_venda ou competencias. |
| `remover_parametro` | `campo` | Remove um desses três parâmetros por ausência. |

Em `definir_nucleo` e `definir_parametro`, `valor` tem a forma do campo na extração inicial, `{valor, trecho}`, com o trecho literal do texto da correção. loja, marca e cargo são listas de `{valor, trecho}`, um item por código, e a lista vazia tira o filtro. `percentual`, `orcamento` e `meta_venda` são números, sem restrição de coerência. `vigencia` tem `inicio` e `fim` no formato `AAAA-MM`. `competencias` é um array não vazio de `AAAA-MM`. `null` não define nem remove valor. Remover `competencias` devolve o job ao período padrão, todas as competências publicadas, sem materializá-lo aqui.

`ref` tem o formato `elem.<dígitos>`. `elemento` é o rascunho da extração inicial, com `construto_pretendido`, `descricao` e `trecho`, mais os campos do construto em `CONSTRUTOS_HABILITADOS`, cujos campos numéricos também usam `{valor, trecho}`.

```json
{
  "operacoes": [
    {"tipo": "definir_nucleo", "trecho": "3%", "campo": "percentual", "valor": {"valor": 0.03, "trecho": "3%"}},
    {"tipo": "definir_parametro", "trecho": "R$ 600 mil", "campo": "orcamento", "valor": {"valor": 600000, "trecho": "R$ 600 mil"}},
    {"tipo": "remover_parametro", "trecho": "tire a meta", "campo": "meta_venda"},
    {"tipo": "definir_parametro", "trecho": "só novembro", "campo": "competencias", "valor": {"valor": ["2025-11"], "trecho": "só novembro"}}
  ]
}
```

A lista vazia é a resposta a um texto que não pede mudança, e devolve a regra e os parâmetros atuais. Exigir ao menos uma operação levaria o modelo a inventar uma. Pela tabela de transições do loop, na skill [`correction-loop`](../../.agents/skills/correction-loop/SKILL.md) da raiz, a proposta com o hash de uma versão que o job já tem marca a rodada como `reextracao_falhou` e abre uma `pendente` nova.

O schema enviado ao modelo é estrito. O aplicador valida o envelope e cada operação separadamente: uma operação desconhecida, com campo a mais ou com valor inválido é ignorada sem perder as demais.

## Lastro

Todo valor novo passa pela conferência da extração inicial (T-210), contra o texto da correção:

- `percentual`, `orcamento` e `meta_venda` por `conferir_numero`.
- `vigencia` e `competencias` por `conferir_periodo`, com as competências publicadas para o ano implícito.
- Cada código de loja, marca e cargo por `resolver_codigo`, no vocabulário canônico.
- Os elementos substituídos ou acrescentados pela montagem da extração inicial.

O valor que não confere não é aplicado: o campo fica como estava, e a operação sai como `DiagnosticoOperacao` com o motivo da conferência (`valor_sem_lastro`, `codigo_fora_do_vocabulario`, `termo_ambiguo` ou `periodo_nao_resolvido`). Uma lista de códigos só é aplicada se todos resolverem, para o escopo não encolher sem o usuário pedir.

Cada operação passa antes pela validação de `trecho_literal(texto_correcao, operacao["trecho"])`. Trecho inexistente, vazio ou não presente no texto corrente produz `DiagnosticoOperacao(indice, "operacao_sem_trecho")`, sem aplicar qualquer mutação. Isso abrange todas as seis operações, inclusive remoções e filtros vazios. O trecho é necessário, mas não substitui a conferência individual dos valores.

Na T-224, uma operação com trecho válido, mas **valor de elemento** não conferido, produz elemento `generico` e `Rebaixamento(..., "valor_sem_lastro", ...)`, usando o trecho literal da operação como descrição segura, sem introduzir números inventados. A mesma regra vale para a substituição e a inclusão. Sem trecho da operação, o elemento atual não é removido nem substituído. Um núcleo ou parâmetro com valor sem lastro permanece inalterado; valores do histórico não justificam alterações.

## Invariantes e falhas

- As operações são aplicadas na ordem da lista, e a última definição válida de um campo prevalece. Uma operação não aplicada não desfaz as anteriores.
- As referências são as da versão original durante todo o lote. Um elemento substituído continua endereçável pelo `ref` original. Um removido deixa de existir. Um acrescentado não é endereçável no mesmo lote, porque o modelo não atribui `ref`.
- A renumeração ocorre só no final: `elem.1`, `elem.2` e assim por diante. Os rebaixamentos sobreviventes recebem a referência final. Os de elementos removidos ou substituídos de novo são descartados.
- A regra, os parâmetros, as operações e as competências recebidos não são modificados, e as estruturas mutáveis devolvidas não compartilham objetos com eles.
- Nada é interpretado, importado ou executado a partir da resposta do modelo.
- Nenhuma incoerência é corrigida. O motor não consulta a validação de domínio (E2).
- A regra final passa por `RepresentacaoRegra`, e os parâmetros finais, por `validar_parametros`. Cada operação de núcleo ou parâmetro valida o candidato antes de ser aplicada.
- `FalhaExtracaoError("Envelope de correção inválido")`: envelope ausente, com propriedades a mais ou sem o array de operações. A mensagem não contém o payload, e a exceção não encadeia o erro de schema.
- `FalhaExtracaoError("Referências da regra atual ambíguas")`: `ref` duplicado na regra recebida.
- `ValueError` ou `pydantic.ValidationError`: entrada atual inválida ou falha na validação final. `reextrair_regra` as converte em `FalhaExtracaoError`, sem encadear.

## Montagem compartilhada e diagnósticos

`montagem.montar_elemento` é a montagem de elemento da extração inicial, usada por ela e pela correção: registro, schema, conversão, lastro numérico e literal, validação do construto e rebaixamento. `montagem.objeto_sem_duplicatas` e `montagem.consumo_de_tokens` também servem às duas leituras da resposta do modelo.

Os rebaixamentos da montagem continuam sendo `Rebaixamento`, com o vocabulário existente. Para operações não aplicadas, há um tipo local:

```python
@dataclass(frozen=True, slots=True)
class DiagnosticoOperacao:
    indice: int  # Posição da operação no lote, começando em 1.
    motivo: MotivoDiagnostico
```

`MotivoDiagnostico` é `operacao_invalida`, `operacao_sem_trecho`, `referencia_inexistente` ou um dos motivos de lastro da seção anterior. O tipo não tem `para_contrato`, não guarda payload nem texto e não é subtipo de `Rebaixamento`. Não deve ser passado a `validar_conteudo`, da extração inicial: esse validador exige que todo genérico da regra tenha seu rebaixamento, e a correção recebe uma regra pronta, sem o histórico.

### Destino dos diagnósticos de operação

`contracts/domain/rebaixamentos-extracao.schema.json` tem motivos fechados e só aceita referências de elemento ou de parâmetro. Uma operação desconhecida ou com referência inexistente não é `campo_obrigatorio_ausente` nem `construto_nao_habilitado`, e a operação não tem referência nesse formato. Persistir a lista inteira exige decidir antes entre ampliar o contrato, com motivos e um alvo para a operação, como `operacoes.<posição>`, e deixar os diagnósticos de operação fora da persistência. Ampliar o contrato afeta o schema, os exemplos, a serialização do codegen e a validação na api, e um validador antigo pode recusar os valores novos.

## Integração

O chamador obtém a versão e os parâmetros atuais, os conflitos e o texto, e passa as competências publicadas a `reextrair_regra`. O resultado traz o conjunto completo de parâmetros, nunca um patch. O motor não emite logs nem métricas: a observabilidade da reextração é da T-221, que o chama no caminho real e precisa cumprir os critérios do `AGENTS.md`, inclusive sucesso, falha, duração e correlação.

## Histórico e métricas — T-224

O repositório `app/repositorio/rodadas_correcao.py` recebe `job_id` e a `submissao_correcao_id` atual. Uma CTE recursiva parte da rodada dessa submissão, percorre `rodada_anterior_id` e confere `job_id` **em cada elo**, sem depender de ordem global de criação; seleciona, via `SELECT`, os conflitos e textos das até **cinco** rodadas anteriores (`LIMITE_HISTORICO_CORRECOES = 5`). Rodadas `reextracao_falhou` estão incluídas; uma primeira correção sem predecessora retorna `[]`. A leitura não grava nada em `rodadas_correcao` e não altera o evento `correcao-submetida`.

`reextract_rule` passa exatamente o mesmo histórico para a consulta da resposta previamente gravada e para a chamada nova ao modelo. O estado persistente do grafo conserva apenas referências, sem cópias dos textos. As operações rejeitadas contam em `codegen_extracao_rebaixamentos_total{motivo=...}` junto às demais da T-204; os motivos são definidos por código, nunca por conteúdo do usuário. Logs carregam apenas referências e contagens, sem histórico, texto, prompt ou resposta.
