# Extração de regra — T-203, T-278, T-206, T-207, T-205

O motor em `app/extracao/motor.py` recebe texto, competências e o modelo configurado, e retorna a representação da T-004, os diagnósticos de rebaixamento, os parâmetros da simulação (T-278) e a chamada original para auditoria. O repositório em `app/repositorio/extracoes.py` persiste esse resultado no PostgreSQL. Não há publicação nem ligação ao grafo nesta entrega; essas entradas pertencem à T-204 e o consumo pela API pertence à T-202.

## Modelo e representação

`get_model("extraction")` usa o mesmo provedor e modelo já configurados para geração: Gemini `gemini-3.1-flash-lite`, temperatura zero, limite de 8192 tokens, timeout de 60 segundos e duas tentativas de retry do cliente. O motor recebe a instância pelo argumento `modelo` para permitir testes determinísticos, sem outra configuração de LLM. Os metadados vêm de `get_model_metadata("extraction")`.

A chamada pede JSON nativo com `response_json_schema`, sem ferramentas. O rascunho fechado contém `nucleo`, `parametros` e `elementos`, nessa ordem; cada elemento traz `construto_pretendido`, `descricao` e `trecho`. O modelo não fornece referências: o motor atribui `elem.1`, `elem.2`, etc. na ordem dos elementos, solicitada no prompt como a ordem do texto.

O núcleo aceita somente vigência, loja, marca, cargo e percentual. Campos não mencionados permanecem ausentes. Códigos são strings; números são lidos como `Decimal` e permanecem números JSON, inclusive no banco. Percentual negativo e intervalo invertido não são corrigidos nesta etapa. Texto sem regra pode resultar em núcleo vazio e nenhuma especificação.

`parametros` traz orçamento, meta de venda e período da simulação (`orcamento`, `meta_venda`, `competencias`), nunca parte da regra (T-277): cada um, quando o texto o diz, é `{valor, trecho}` no rascunho do modelo. O motor descarta o trecho e guarda só o valor, validado contra `parametros-simulacao.schema.json` (`app/extracao/parametros.py`); o trecho não verificado continua recuperável na resposta bruta auditada em `respostas_modelo`, para a conferência de lastro da T-210. Um parâmetro não dito no texto fica fora de `parametros`; nada dito deixa `parametros` vazio (`{}`). O valor entra como o modelo o devolveu, sem faixa nem correção — orçamento negativo ou competência fora das publicadas são apontados pela validação de domínio (T-280), não aqui. Uma condição de atingimento de meta dentro da regra não é `meta_venda`: permanece em elemento.

O período da simulação só existe quando o texto manda simular um período ou o liga ao orçamento ou à meta ("meta de vender R$ 12 milhões entre setembro e novembro de 2025"); o período ligado à comissão ("comissão de 3% em novembro") é a vigência, em `nucleo.vigencia`. As competências que o motor recebe são as publicadas, que é o que o job tem ao nascer (T-277), e o prompt proíbe copiá-las para `parametros`: sem essa instrução o modelo as devolve como período em todo texto, com um trecho que não está no texto. O schema pede `parametros` antes de `elementos` porque o modelo gera as chaves na ordem das propriedades, e é decidindo os parâmetros primeiro que ele não faz do pedido de simular um período também um elemento, que chegaria à geração como regra a implementar.

`validar_parametros` roda no motor, ao gravar e ao ler a extração. Um valor fora do contrato vira `ValueError` sem o valor, nem na mensagem nem na cadeia da exceção: fora do motor não há supressão, e a exceção do `jsonschema` traz o valor reprovado, que é o que o texto do usuário disse.

O registro explícito de construtos tipados (`app/extracao/registro.py`) habilita hoje `bonus_fixo`, `condicao_limiar`, `janela_datas` e `exclusao`. Não há importação de módulos a partir da resposta da LLM. Para habilitar um construto, seu módulo em `app/extracao/construtos/` fornece schema, instruções e conversor por `Construto` (`app/extracao/construto.py`), e uma linha no registro o habilita; o resultado ainda precisa passar pelo contrato compartilhado. O conversor recebe o rascunho e um `ContextoExtracao` (texto e competências do job) e pode recusar o elemento com `ElementoRebaixadoError(motivo)`, cujo motivo vira o do rebaixamento; qualquer outro `ValueError` é `campo_obrigatorio_ausente`.

Habilitar o primeiro construto transforma `elementos.items` em um `anyOf`, e com isso o modelo `gemini-3.1-flash-lite` passou a copiar as competências publicadas para `nucleo.vigencia`, a pôr o período a simular na vigência e a descartar o que o núcleo não comporta, em vez de criar o genérico. As descrições do schema de `vigencia`, `competencias` e da variante genérica corrigem isso, e os casos do corpus que cobrem esses comportamentos ficam como a prova. Ao habilitar o próximo construto, rode o corpus inteiro contra o modelo real.

### `bonus_fixo` (T-206)

O rascunho traz `tipo_alvo` (`lista` ou `filtro`), `matriculas` ou `criterios`, e `valor` como `{valor, trecho}`. O lastro de matrículas, cargo e data é o `trecho` do próprio elemento, que o motor já confere como literal do texto.

- **Matrícula**: entra somente a que o trecho cita, como `MATRIC-<número>` ou depois da palavra "matrícula(s)"; `422` vira `MATRIC-422`. A que o trecho não cita é descartada do alvo, e uma lista que fica vazia rebaixa o elemento (`valor_sem_lastro`). O motor não consulta o cadastro.
- **Filtro**: o vocabulário é fechado em `cargo` (resolvido pelo vocabulário canônico) e `admitido_ate` (`AAAA-MM-DD`). Outra chave não cabe no schema do rascunho e rebaixa o elemento como `construto_nao_habilitado`.
- **Data**: `resolver_datas` e `conferir_data` (`lastro.py`) leem `dd/mm`, `dd/mm/aaaa`, `AAAA-MM-DD` e "10 de outubro". O ano que o trecho não diz é o ano comum das competências do job; com mais de um ano o elemento rebaixa com `periodo_nao_resolvido`.
- **Valor**: precisa de lastro numérico e de um trecho sem `%` nem "por cento"; um bônus percentual rebaixa com `campo_obrigatorio_ausente`.
- **Alvo**: lista e filtro não coexistem, e alvo sem critério não é representável; ambos rebaixam com `campo_obrigatorio_ausente`.

### `exclusao` (T-205)

O rascunho traz `dimensao` (`loja`, `marca` ou `cargo`) e `valores`, uma lista de `{valor, trecho}` com um trecho por código, como loja, marca e cargo do núcleo. Cada valor passa por `resolver_codigo` com o seu próprio trecho: sem um código conhecido, o resolvedor usa os códigos que o trecho cita, e um trecho com vários códigos trocaria o desconhecido por outro. Nomes que resolvem para o mesmo código entram uma vez ("gerente", `GERENTE DE LOJA` e `GERENTE QUIOSQUE` viram `150`).

- **Um elemento por dimensão**: excluir um cargo e uma marca são duas exclusões, com `ref` na ordem do texto.
- **Código não resolvido**: um valor fora do vocabulário, ambíguo ou sem lastro rebaixa o elemento inteiro, com o motivo do resolvedor (`codigo_fora_do_vocabulario`, `termo_ambiguo` ou `valor_sem_lastro`), porque excluir só os resolvidos mudaria o resultado sem aviso. O genérico preserva o trecho e leva `campos` com a `dimensao` e os `valores` resolvidos, quando houver.
- **Matrícula**: a dimensão não a admite. `dimensao = matricula` não cabe no schema do rascunho, e um trecho que fala de matrícula não chega à resolução, porque o número de uma matrícula pode coincidir com o código de uma loja; os dois rebaixam com `campo_obrigatorio_ausente`.
- **Alcance**: a exclusão retira os códigos da regra inteira. Um trecho com valor próprio (`%`, `R$`, "por cento", "reais") é a exceção de um efeito, como um bônus ou um acréscimo, e rebaixa com `termo_ambiguo`. A exceção que vale para uma de várias regras independentes, sem valor no trecho, só é separada pelo prompt, que a manda para um genérico junto da regra.
- **Núcleo e exclusão**: a extração não confere um contra o outro. Incluir e excluir o mesmo código produz os dois como foram ditos, e a validação de domínio aponta `exclusao_repetida`.

Cada elemento recuperável vira `generico` quando o construto não está habilitado ou faltam campos válidos. A ausência/invalidez tem prioridade no diagnóstico (`campo_obrigatorio_ausente`); os demais rebaixamentos usam `construto_nao_habilitado`. Se a descrição não é utilizável, um trecho não vazio encontrado literalmente na entrada preserva o elemento. Sem descrição nem trecho recuperável, a extração inteira falha. Referências e diagnósticos têm correspondência de um para um para os genéricos.

JSON inválido, chaves duplicadas, núcleo fora do schema, elemento irrecuperável ou resposta sem `finish_reason=STOP` são falha permanente em `extracao_parametros`. A exceção pública não retém o conteúdo bruto nem a exceção do parser. Falhas do provedor seguem para o chamador, responsável pela política de retry. A resposta original e o prompt só são persistidos junto de uma extração válida; a camada que tratar falhas da chamada deve respeitar a mesma proibição de conteúdo em telemetria.

A T-203 não comprova que a LLM preservou todos os números ou resolveu corretamente vocabulário e contexto temporal. A conferência determinística desses valores pertence à T-210. Construtos genéricos conservam a intenção textual para as etapas seguintes; não significam autorização para simulação parcial.

## Persistência e entrega por referência

A fonte canônica é [`modelo-dados.dbml`](../../docs/database/modelo-dados.dbml); a API aplica `020-cria-extracoes-regras.sql`.

| Tabela | Conteúdo |
| --- | --- |
| `prompts` | Texto exato enviado e metadados do modelo; nó `extracao_parametros` |
| `respostas_modelo` | Resposta textual original e consumo de tokens quando informado |
| `extracoes_regras` | `job_id`, `submissao_id`, `resposta_id`, representação completa, diagnósticos e os parâmetros da simulação |

A LLM é chamada fora da transação. `gravar_extracao` grava os três artefatos atomicamente, com UUIDv5 estável por job/submissão e índice único nesse par. Uma reentrega retorna a extração existente, mesmo que receba outro resultado candidato. Na corrida entre escritores, a transação perdedora reverte também seu prompt e sua resposta e lê o vencedor. Falhas SQL são propagadas por uma exceção sanitizada, sem parâmetros do driver.

O codegen tem `SELECT` e `INSERT` na nova tabela; a API tem somente `SELECT`; o worker não tem acesso. A criação da versão de `regras`, transições, auditoria e outbox continuam sob responsabilidade da API.

O contrato de `regra-extraida` exige somente estas referências de negócio:

```json
{
  "job_id": "3f2b1c40-0d18-4a51-9f2e-6c1d9a77b021",
  "submissao_id": "13ed2c69-2903-4e35-a715-59ecf061f3e1",
  "extracao_id": "8a267bec-3e5e-5ed9-b151-710d03f573b8"
}
```

`representacao` é expressamente proibida nesse evento. A mudança quebra o payload anterior por decisão aprovada de cumprir o ADR-001; ainda não havia produtor ou consumidor implementado. Campos futuros do envelope continuam permitidos, conforme a evolução de eventos.

Na T-204, o chamador deve consultar `buscar_extracao` antes da LLM, persistir antes de publicar, aguardar confirmação do broker e só então confirmar a mensagem de entrada. Uma falha entre commit e publicação é recuperada por reentrega e republicação da mesma referência. O codegen não passa a escrever no outbox da API. Na T-202, o consumidor deve verificar `extracao_id`/`job_id`/`submissao_id`, criar a versão raiz e registrar `regra-submetida` em uma transação própria, com idempotência.

## Validação e observabilidade

Os testes unitários usam um modelo roteirizado. Os marcados `llm` (`tests/app/extracao/test_llm.py`) chamam o modelo real e são pulados sem `GOOGLE_API_KEY`; passam as cinco competências publicadas, como o job em produção, para que um modelo que as copie não passe por quem leu o período no texto. Na cota gratuita do provedor (15 requisições por minuto para `gemini-3.1-flash-lite`), rodá-los em sequência pode esbarrar em `429 RESOURCE_EXHAUSTED`. Os testes de persistência sobem PostgreSQL descartável, aplicam o DDL das migrations da API e conectam com o usuário do codegen; não alteram o banco do compose. A suíte da API valida aplicação/rollback pelo Liquibase e permissões dos três serviços.

```sh
make pre-commit
make lint
RUN_POSTGRES_INTEGRATION=1 poetry run pytest tests/app/repositorio/test_extracoes_postgres.py
poetry run pytest -m llm -v tests/app/extracao/test_llm.py
```

Motor e repositório não emitem logs nem métricas próprios. O nó `extract_rule` emite início, conclusão e falha com `job_id` e `no = extracao_parametros`, sem conteúdo da regra, do prompt ou da resposta. Nos desfechos, `extra.extracao_reutilizada` indica se a tentativa encontrou um artefato já persistido e dispensou a chamada ao modelo; `false` também cobre falhas anteriores à consulta. A conclusão inclui as contagens por construto e por motivo de rebaixamento, e `extra.parametros_extraidos` lista os nomes dos parâmetros da simulação que o texto trouxe, nunca o valor. A falha inclui a `operacao` que estava em execução: validação da entrada, consulta, carregamento do modelo, extração, gravação ou publicação de cada um dos três eventos.

O `motivo` de falha é definido pelo tipo da exceção: `timeout`, `conexao`, a classe de falha permanente/cancelamento, ou `falha_na_operacao` para erros sem classificação específica. Mensagens e cadeias de exceções não são inspecionadas nem emitidas. A `classe` e os labels das métricas permanecem os mesmos.

Com `job_name = extract_rule`, `job_runs_total` conta execuções do nó, inclusive tentativas que reutilizam o artefato; `job_failures_total` conta as que falham. `job_duration_seconds` mede toda a execução do nó, incluindo banco, retries do provedor e publicações, tanto em sucesso quanto em falha. Os buckets preservam os limites anteriores até 10 segundos e acrescentam 15, 30, 45, 60, 90, 120, 180, 240 e 300 segundos antes de `+Inf`, para distinguir chamadas longas e retries. Os contadores de elementos, rebaixamentos e parâmetros avançam apenas quando o nó conclui. `codegen_extracao_parametros_total` conta, por conclusão, cada um de `orcamento`, `meta_venda` e `competencias` como `extraido` ou `ausente` — sempre um incremento por parâmetro e por conclusão, nunca o valor como label. Uma reentrega descartada pelo checkpoint não executa o nó e não incrementa essas medidas.

Os testes de `tests/app/graph/test_extracao.py` exercitam consumer, roteador e grafo com modelo, banco e produtores falsos; conferem logs serializados e deltas no registry servido por `/metrics`, incluindo recuperação de publicação e durações controladas por relógio falso. Isso verifica a emissão e a exposição local, mas não comprova coleta externa por Prometheus, Alloy ou Grafana.

### `janela_datas` e o efeito compartilhado (T-207)

O rascunho traz `data_inicial`, `data_final` e `efeito`. As datas saem de `resolver_datas` sobre o `trecho` do elemento, que deve cobrir as datas e o efeito; o ano que o texto não diz é o ano comum das competências do job (`periodo_nao_resolvido` se houver mais de um). A evidência do efeito deve estar nesse mesmo trecho, para não aproveitar um valor de outra janela. Um dia só repete a data nas duas pontas, e a janela invertida sai como dita (a validação a aponta). Datas que o trecho não diz, um trecho com mais de duas ou qualquer data inválida no calendário rebaixam com `valor_sem_lastro`; uma data inválida nunca é descartada para aproveitar as demais. Um evento sem datas ("Black Friday") não ganha datas inventadas.

`app/extracao/efeito.py` normaliza o `efeito` e é o módulo que `faixa_valor` (T-208) reutiliza. `acrescimo_pct` e `substituicao_pct` saem em fração. Para números em algarismos, `%` ou "por cento" após o próprio número determinam a divisão por 100; uma fração explicitamente identificada como "fração de 0,01", "0,01 em fração", "0,01 (fração)", "0,01 como fração" ou "fração decimal de 0,01" conserva o valor, sem nova divisão. O marcador deve estar ligado ao número conferido: um dia ou um valor em reais no mesmo trecho não valida o percentual. A aceitação de fração sem marcador no núcleo permanece independente dessa exigência dos efeitos.

Sem algarismos, o efeito percentual exige um número por extenso ligado a `%` ou "por cento", como "dois e meio por cento". Uma frase vaga como "uma fração da comissão" não informa proporção e rebaixa com `valor_sem_lastro`. A unidade monetária é conferida na fonte ao redor do número, inclusive quando o recorte do valor omite `R$`, "real", "reais" ou "centavos". A conferência é por ocorrência: um valor monetário separado no mesmo trecho não invalida uma fração com lastro próprio.

`bonus_fixo` sai em reais e rejeita um trecho com percentual. `acrescimo_base` não está no vocabulário do rascunho, então um efeito que só caberia nele rebaixa o elemento (`campo_obrigatorio_ausente`). `bonus_fixo` usa o mesmo `valor_monetario`.
