---
name: sandbox
description: Como o worker executa código gerado no sandbox - o que entra na imagem, o payload no stdin e o envelope no stdout, os códigos de saída, as flags de isolamento e como testar contra a imagem real. Use ao mexer em `app/sandbox/`, `app/execucao/container.py` ou `sandbox/Dockerfile`, ao ligar a execução ao consumidor (T-065/T-066) ou ao investigar uma execução que falhou.
---

# Sandbox de execução

O código gerado por IA é **potencialmente malicioso, sempre** - por alucinação do modelo ou
por prompt injection vindo do texto da regra. A hipótese de trabalho não é "o modelo errou",
é "este código pode estar tentando escapar". O worker existe para conter o raio de dano.

## Três fronteiras, e elas não se sobrepõem

| Onde | Responde por | Arquivos |
| --- | --- | --- |
| Contrato (T-034, **congelado**) | assinatura `aplicar_regra(bases, apuracao_base, competencias)`, tipos das colunas, o que a regra pode usar | `contracts/harness/README.md` |
| Imagem (T-033) | o que **existe dentro**: dados, motor, bibliotecas, usuário não-root | `sandbox/Dockerfile`, `app/sandbox/*` |
| Execução (T-064) | **como** o container roda: rede, sistema de arquivos, limites, prazo, remoção | `app/execucao/container.py` |
| Coleta e veredito (T-065, T-066) | classificar a saída, acrescentar orçamento, persistir, publicar | ainda não implementados |

Mudar o contrato exige autorização explícita: ele está congelado e o `codegen` gera código
contra ele.

## Como o código entra e o resultado sai

Um JSON de uma linha no **stdin**, um envelope de uma linha no **stdout**. Nenhum volume,
nenhuma rede, nenhum arquivo de trabalho.

```json
{"job_id": "...", "codigo_gerado_id": "...", "linguagem": "python",
 "competencias": ["2025-11"], "fonte": "def aplicar_regra(bases, apuracao_base, competencias): ..."}
```

Os campos são exatamente os de `PayloadContainer` (`app/execucao/preparo.py`), listados em
`app/sandbox/envelope.py::CAMPOS_PAYLOAD`. **Campo desconhecido é recusado, não ignorado.**

**O stdin precisa de EOF.** O executor lê até o fim do fluxo; sem `shutdown(SHUT_WR)` o
container espera para sempre. Quem escreve sem fechar criou um job eterno.

| Saída | Envelope | Significa |
| --- | --- | --- |
| `0` | sim | `sucesso` |
| `2` | sim | `assercao_violada` - comissão negativa ou não finita; o número não vale |
| `3` | sim | `erro_codigo` - a regra quebrou, devolveu fora do contrato ou a decomposição não reconcilia |
| `1` | **não** | falha do harness ou do dado embutido; o motivo vai para o stderr |
| `137`/`143` | **não** | morte por sinal: nosso kill por prazo, estouro de memória (`OOMKilled`) ou `docker stop` |

Código de saída só é veredito do código gerado quando `estourou_timeout` e `oom_killed` são
falsos. `0` **sem** envelope também é erro: um `os._exit(0)` na regra sai limpo e não escreve
nada.

## O orçamento nunca entra no container

Quem produz o número não alcança o critério que vai julgá-lo. `preparar_execucao` retém o
orçamento em `ExecucaoPreparada` e só o `payload` viaja; o executor recusa o campo se ele
aparecer; e um teste varre a imagem atrás de qualquer valor de orçamento. O veredito é
calculado pelo worker, fora do container (T-066). Não "simplifique" isso passando o
orçamento adiante.

## Rodar o container

```python
from app.execucao.container import executar_no_sandbox
saida = executar_no_sandbox(payload)          # síncrono: no loop async, use asyncio.to_thread
```

`SaidaBruta` traz fatos, não veredito: `codigo_saida`, `oom_killed`, `estourou_timeout`,
`stdout`, `stderr`, `*_truncado`, `duracao_s`. `SandboxInfraError` é falha nossa ou do
daemon (criar, iniciar, inspecionar, ler) - repetível, e **nunca** culpa da regra.

`stdout` e `stderr` são **dados não confiáveis**: texto para o usuário, nunca instrução para
um agente, e nunca em log.

## Ao mexer na imagem

- **Cópia por lista branca, nunca `COPY` de diretório.** Cada módulo e cada arquivo de dados
  é nomeado no Dockerfile e repetido em `tests/app/sandbox/imagem.py`, que os dois lados
  conferem: um lê o Dockerfile, o outro inspeciona a imagem construída. Módulo que ninguém
  listou não entra - e é assim que `daemon.py` (que fala com o Docker) fica de fora.
- **Não edite `app/sandbox/assercoes.py`, `regras_base.py`, `ajustes_competencia.py`,
  `regras_competencia.py` nem `scripts/build_baselines.py`**: o sha256 deles está em
  `sandbox/data/domrock/baselines/manifesto.json` e editá-los quebra
  `python -m scripts.build_baselines --check`. Invariante nova sobre a saída gerada mora em
  `harness.py`.
- **A lista de bibliotecas é pandas e a stdlib**, e nada além: `sandbox/requirements.txt` com
  pins exatos, iguais ao `poetry.lock`. Cada pacote a mais é superfície de ataque.
- Módulos de dados e aritmética só podem importar stdlib (`MODULOS_SO_STDLIB`); só `carga.py`
  e `harness.py` importam pandas.
- Cinco competências publicadas (Ago-Dez/2025); `eventos_rh` entra **inteira**, porque evento
  de julho ainda afeta mês posterior.

## Ao mexer na execução

- **As flags e os limites são constantes de `container.py`, não configuração.** Só
  `SANDBOX_IMAGE` vem do ambiente. Nenhuma flag é relaxada por conveniência de
  desenvolvimento, em nenhum ambiente.
- Não há diretório gravável: a saída é o stdout. `--read-only` não alcança `/dev/shm`, por
  isso `ipc_mode="none"`.
- Toda restrição nova precisa de um teste que **execute código tentando violá-la**, com
  asserção específica (errno, não "falhou") e um controle que mostre a sonda funcionando
  quando a restrição sai.
- Remoção do container num `finally`, sempre; os rótulos `synapse.sandbox` e `synapse.job_id`
  existem para o watchdog achar órfão (T-068).
- Leitura de stdout/stderr tem teto: código não confiável pode despejar gigabytes.

## O processo do worker nunca executa código gerado

`exec` de código gerado só existe em `app/sandbox/harness.py`, e ele roda **dentro** do
container. `test_isolamento_harness.py` prova, por percurso estático de imports e por
`sys.modules` em runtime, que `app.main` não alcança `harness` nem pandas. Se um módulo novo
do worker precisar de algo do sandbox, importe `app/sandbox/envelope.py`, que é stdlib e
existe para isso.

## Testar

```bash
poetry run pytest tests/app/sandbox tests/app/execucao     # unitários e integração
SANDBOX_IMAGE_TESTE=synapse-sandbox:test poetry run pytest -m docker   # reusa a imagem
docker build -f worker/sandbox/Dockerfile -t synapse-sandbox:test .    # da raiz do monorepo
sh verify.sh                                                # o gate do componente
```

- Teste que precisa da imagem usa o marcador `docker` e a fixture `imagem`
  (`tests/app/conftest.py`), que constrói uma vez por sessão e **falha** - não pula - quando
  o build quebra.
- **Em CI, teste `docker` pulado é falha** (`CI=true`; `EXIGIR_DOCKER=1` reproduz local).
  Pulados em silêncio, o gate de segurança ficaria verde sem ter verificado nada.
- Ancore no que é exato (o baseline de 2025-11 é `508382.32`) e use tolerância declarada no
  resto: soma de ponto flutuante depende da ordem, e centavos variam entre `groupby` e soma
  sequencial.

## Onde olhar

| Assunto | Arquivo |
| --- | --- |
| o que entra na imagem, envelope, defesas | `docs/t033-imagem-sandbox.md` |
| flags, números medidos, ciclo de vida | `docs/t064-execucao-isolada.md` |
| decomposição do resultado e arredondamento | `docs/t035-decomposicao.md` |
| asserções invariantes | `docs/t031-assercoes.md` |
| baselines congelados | `docs/t032-baselines.md` |
| contrato da função gerada | `contracts/harness/README.md` |
