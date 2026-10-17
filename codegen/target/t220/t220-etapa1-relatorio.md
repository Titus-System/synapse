# T-220 — Etapa 1: relatório de entrega

Data: 14/10/2026. Componente: codegen.

## Base e preparação

- Branch inicial: `feature/t-215-pausa-validacao-correcao`, árvore limpa.
- Executados `git branch --show-current`, `git status`, `git fetch origin` e
  `git log -5 --oneline`. O fetch precisou de execução fora do sandbox por bloqueio
  de escrita em `.git/FETCH_HEAD`; depois concluiu normalmente.
- Branch criada: `feature/t-220-motor-reextracao`, a partir de `origin/develop`
  em `27b64f7` (sem integrar a branch da T-215).
- Dependências confirmadas no histórico dessa base: T-203 `75e4125`, T-277
  `4db4641`, T-278 `ab6a008` / merge `221e5a9`.
- Lidos os AGENTS da raiz/codegen, skills correction-loop compartilhada/local,
  testing, graph e commit-and-comments compartilhada/local, todos os módulos
  solicitados e os contratos de representação, parâmetros e rebaixamentos.

## Arquivos

Alterados:

- `codegen/.gitignore`: ignora somente `/target/t220/` para os artefatos desta entrega.
- `codegen/app/extracao/motor.py`: delega a montagem dos elementos à função extraída.

Criados:

- `codegen/app/extracao/montagem.py`: montagem da T-203 compartilhada sem mudança de comportamento.
- `codegen/app/extracao/schema_correcao.py`: envelope e schema das seis operações.
- `codegen/app/extracao/correcao.py`: motor determinístico e diagnósticos internos.
- `codegen/tests/app/extracao/test_correcao.py`: 43 casos novos, incluindo parametrizações.
- `codegen/docs/correcao.md`: interface, invariantes, exceções e decisão pendente.

Entregáveis ignorados: este relatório, `t220-etapa1.diff`, `t220-etapa1-status.txt`
e a evidência inicial `testes-red.txt`. O diff inclui os cinco arquivos novos sem
adicioná-los ao índice. Nenhum outro componente ou contrato foi alterado.

## Arquitetura e interface

```python
def aplicar_operacoes_correcao(
    representacao: RepresentacaoRegra,
    parametros: dict[str, ValorRegra],
    operacoes: object,
    competencias_publicadas: Sequence[str],
    *,
    texto_correcao: str = "",
) -> tuple[
    RepresentacaoRegra,
    dict[str, ValorRegra],
    list[Rebaixamento | DiagnosticoOperacao],
]: ...
```

O envelope é um objeto Python já desserializado, com números fracionários em
Decimal. A saída contém regra corrigida, parâmetros completos e diagnósticos desta
aplicação. A documentação versionada em `codegen/docs/correcao.md` define todos os
tipos, exceções e limites para a segunda etapa.

As operações são aplicadas em ordem sobre cópias independentes. Referências mantêm
o significado da versão de entrada durante o lote, inclusive após substituição;
elementos removidos não são redirecionados a outro alvo. Somente no fim, elementos
e seus rebaixamentos sobreviventes recebem `elem.1`, `elem.2`, etc. Diagnósticos de
montagens que foram substituídas ou removidas no mesmo lote não sobrevivem.

Regra final validada por RepresentacaoRegra; parâmetros finais por validar_parametros.
Os valores incoerentes aceitos pelos contratos, inclusive meses não publicados,
permanecem para E2. Competências publicadas não são filtro nem preenchimento padrão.

## Schema das seis operações

Envelope fechado `{"operacoes": [...]}`, obrigatório e não vazio.

| tipo | campos além de tipo |
| --- | --- |
| definir_nucleo | campo: percentual/vigencia/loja/marca/cargo; valor tipado por campo |
| substituir_elemento | ref; elemento: rascunho da T-203 |
| remover_elemento | ref |
| adicionar_elemento | elemento: rascunho da T-203 |
| definir_parametro | campo: orcamento/meta_venda/competencias; valor tipado por campo |
| remover_parametro | campo: orcamento/meta_venda/competencias |

Nenhuma operação permite propriedades extras. O schema de saída reutiliza os
schemas e o registro da extração inicial. A validação de consumo separa envelope
e operações: envelope inválido causa FalhaExtracaoError; item inválido é ignorado
com diagnóstico. Um lote não vazio com todos os itens inválidos é recuperável e
retorna os dados preservados. Rascunhos incompletos recuperáveis passam pela mesma
montagem/rebaixamento da T-203; irrecuperáveis invalidam só a operação.

O texto do modelo nunca é interpretado, importado ou executado. Não foi adicionada
dependência runtime, chamada ao modelo, prompt, função assíncrona, grafo, banco,
mensagem, publicação, histórico ou validação E2/T-224.

## Reaproveitamento da T-203

`montar_elemento` foi extraída do loop de `_montar` para `montagem.py`. Conserva
CONSTRUTOS_HABILITADOS, schemas, lastro literal/numérico, conversor, validação da
representação do elemento e fallback genérico. A extração inicial chama a mesma
função. Os testes existentes não foram alterados ou enfraquecidos.

## Testes e verificações

Ambiente já instalado utilizado, sem instalação de dependências:

```powershell
$py = 'C:\Users\eduar\AppData\Local\pypoetry\Cache\virtualenvs\codegen-5f5nqeI2-py3.13\Scripts\python.exe'
```

Python 3.13.2; pytest 8.4.2; Ruff 0.8.6; mypy 1.20.2. O Python global não tinha
essas ferramentas e `poetry env info --path` não resolveu um ambiente para este
checkout; por isso os comandos usaram explicitamente o interpretador existente.

No diretório codegen:

1. `python scripts/preparar_contratos.py`: sucesso; copiou os schemas para o
   diretório ignorado de build, sem editar contratos compartilhados.
2. `& $py -m pytest tests/app/extracao/test_correcao.py -q --tb=short`:
   **43 falhas esperadas antes de implementar o comportamento**. O esqueleto
   devolvia as entradas inalteradas e nenhum diagnóstico; o schema era vazio.
   Falharam as alterações esperadas, as renumerações, diagnósticos, montagem,
   isolamento de objetos, rejeições de envelope e definição do schema.
   Evidência completa em `testes-red.txt`. Nenhum caso passou nessa fase.
3. Primeira seleção ampliada incluiu `test_corpus.py`: falhou na coleta por
   `ModuleNotFoundError: google.genai`. Esse módulo contém corpus com modelo real;
   não foi executado. A seleção seguinte ficou nos testes unitários sem rede.
4. Comando focado final:

```powershell
& $py -m pytest -p no:cacheprovider tests/app/extracao/test_correcao.py tests/app/extracao/test_motor.py tests/app/extracao/test_registro.py tests/app/extracao/test_falhas.py tests/app/extracao/test_parametros.py tests/app/extracao/test_chamada.py -q --tb=short
```

Resultado: **106 passed in 4.17s** (43 novos + 63 existentes). Depois desse resultado,
somente uma anotação de tipo foi acrescentada ao adaptador `_VALOR`; nenhum
comportamento foi alterado nem os testes foram repetidos sem necessidade.

5. Ruff foi executado nos quatro módulos de aplicação e no teste novo. A primeira
   checagem encontrou seis linhas longas no teste; `ruff format` corrigiu o formato.
   Checagens finais:

```powershell
& $py -m ruff check app/extracao/correcao.py app/extracao/schema_correcao.py app/extracao/montagem.py app/extracao/motor.py tests/app/extracao/test_correcao.py
& $py -m ruff format --check app/extracao/correcao.py app/extracao/schema_correcao.py app/extracao/montagem.py app/extracao/motor.py tests/app/extracao/test_correcao.py
& $py -m mypy app/extracao/correcao.py app/extracao/schema_correcao.py app/extracao/montagem.py app/extracao/motor.py
```

Resultados: **All checks passed; 5 files already formatted; Success: no issues
found in 4 source files**. Mypy inicialmente pediu a anotação de `_VALOR`, corrigida.

6. `git diff --check`: sucesso. `git check-ignore` confirmou os relatórios ignorados.
   O diff completo foi conferido com `git apply --check --reverse`.

As verificações cobrem os 18 cenários obrigatórios, incluindo campos preservados,
posição, remoção, inclusão, downgrade, referência inexistente, operação desconhecida,
orçamento 600000, remoção de meta, novembro, imutabilidade, incoerência e validação
dos resultados. Cobrem também refs estáveis no lote, descarte de rebaixamento após
remoção, uso do conversor habilitado e lastro compartilhado.

## Problemas e decisão pendente

- O contrato de rebaixamentos não permite representar corretamente operação inválida
  ou referência inexistente. Nenhum motivo incorreto foi reutilizado e nenhum
  contrato foi ampliado.
- Alternativa implementada: `DiagnosticoOperacao(indice, motivo)` local, sem
  `para_contrato`, com motivos `operacao_invalida` e `referencia_inexistente`.
  `Rebaixamento` é reutilizado para os resultados da montagem em que seu significado
  já é válido. A lista de retorno é uma união explícita dos dois tipos.
- Proposta pendente: ampliar os motivos e definir alvo de operação, como
  `operacoes.<posição>`, ou adotar um objeto de diagnóstico próprio. Ampliar apenas
  o enum não basta: refs inexistentes/renumerados precisam de semântica própria.
- Mudanças potenciais: schema compartilhado, exemplos, tipos/serialização/validação
  do codegen, persistência/validação da api e documentação. Produtor: codegen;
  consumidor: api; eventual exposição ao frontend precisa ser avaliada. Consumidores
  antigos podem rejeitar os novos valores. A alteração exige autorização e testes
  dos consumidores relevantes. Não implementada nesta entrega.
- `validar_conteudo` da extração inicial não pode consumir diretamente os diagnósticos
  da correção: exige o histórico de todos os genéricos, que não faz parte desta interface.
- O aviso de cache do pytest no sandbox foi resolvido usando `-p no:cacheprovider`;
  somente as duas pastas temporárias geradas nesta sessão foram removidas após
  autorização, com verificação dos caminhos absolutos.

## Limites verificados e próxima etapa

Não executados: gate completo `make pre-commit` (adiado por pedido explícito),
build Docker, testes de rede/modelo real, integração de broker/banco, outros
componentes e exportação/coleta de telemetria. Não foram criados logs ou métricas,
conforme o escopo explícito; este motor não está conectado a um fluxo da aplicação.
Não há alegação de observabilidade operacional ou recebimento em painel.

Para a etapa 2: gerar/desserializar o envelope com Decimal, fornecer regra,
parâmetros completos, texto e competências à função; decidir o destino auditável
dos diagnósticos locais antes de persistir; integrar chamada, tratamento de falhas
e telemetria nas tarefas próprias. A proposta deve transportar os parâmetros
completos, preservando a diferença entre ausência e null.

Nenhum staging, commit, push, merge ou rebase foi executado. Trabalho encerrado na
etapa 1, com motor determinístico, documentação e testes focados.
