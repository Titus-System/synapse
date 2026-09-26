# Imagem do sandbox (T-033): o container efêmero, sem rede e somente-leitura, onde o código
# gerado pela IA é executado. O contexto de build é a RAIZ do monorepo:
#
#   docker build -f worker/sandbox/Dockerfile -t synapse-sandbox:local .
#
# As flags de isolamento (--network none, --read-only, limites de CPU e memória, timeout)
# são de quem sobe o container (T-064), não da imagem. O que a imagem garante é o que
# existe dentro dela. O porquê de cada arquivo que entra e de cada um que fica de fora:
# worker/docs/t033-imagem-sandbox.md.

FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/opt/venv/bin:$PATH"

RUN python -m venv /opt/venv

COPY worker/sandbox/requirements.txt /tmp/requirements.txt

# --only-binary: falha em vez de compilar da fonte em silêncio. Não há compilador nesta
# imagem, e compilador no sandbox seria superfície que não se justifica.
# O pip sai do venv ao final: a lista de bibliotecas é a da T-034, e nada além dela.
RUN pip install --only-binary=:all: -r /tmp/requirements.txt \
    && pip uninstall -y pip


FROM python:3.12-slim AS runtime

# PYTHONHASHSEED: a reexecução para auditoria precisa devolver o mesmo número, e a ordem de
# iteração de set no código gerado não pode variar entre execuções.
# LANG e PYTHONIOENCODING: reforço. O payload é lido em binário e decodificado como UTF-8
# no próprio código, então o locale do container é irrelevante para a correção.
# OMP/OPENBLAS: uma thread só, para a soma de ponto flutuante não depender do número de núcleos.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=0 \
    PYTHONIOENCODING=utf-8 \
    LANG=C.UTF-8 \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Os diretórios são criados aqui, antes dos COPY. `--chmod` num COPY aplica o mesmo modo aos
# arquivos e aos diretórios que ele cria, e diretório sem bit de execução não pode ser
# percorrido: com 0444 o import falhava com ModuleNotFoundError e os dados ficavam
# inalcançáveis. Já existentes, os diretórios mantêm 0755 e só os arquivos levam 0444.
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /app/app/sandbox /app/sandbox/data/domrock/baselines/auditoria

COPY --from=builder /opt/venv /opt/venv

# O Python da imagem base traz o próprio pip em /usr/local. O venv não o enxerga, mas o
# binário fica no PATH e essa superfície não se justifica: sem rede ele não instala nada, e
# sem ele a lista de bibliotecas é a da T-034 também para quem procurar fora do venv.
# Caminho absoluto: `python` no PATH é o do venv, que já não tem pip.
RUN /usr/local/bin/python -m pip uninstall -y pip

# Código: lista branca, um arquivo por linha, nunca `COPY worker/app`. Módulo novo que
# ninguém listou não entra na imagem. Ficam de fora: daemon.py (importa docker, app.config
# e app.core.logger) e regras_competencia.py (só recomputa baselines, e o baseline aqui é
# dado congelado). O layout espelha o repositório (app/sandbox/), porque resultado.py
# importa os irmãos por app.sandbox.* e carga.py acha os dados relativo ao próprio arquivo.
COPY --chmod=0444 worker/app/__init__.py ./app/__init__.py
COPY --chmod=0444 \
     worker/app/sandbox/__init__.py \
     worker/app/sandbox/ajustes_competencia.py \
     worker/app/sandbox/assercoes.py \
     worker/app/sandbox/carga.py \
     worker/app/sandbox/envelope.py \
     worker/app/sandbox/executor.py \
     worker/app/sandbox/harness.py \
     worker/app/sandbox/regras_base.py \
     worker/app/sandbox/resultado.py \
     ./app/sandbox/

# Dados: as três bases e a tabela de eventos de RH, o schema e os baselines congelados
# (T-032) das cinco competências publicadas (2025-08 a 2025-12; julho foi excluído pela
# T-026). Ficam de fora: normalization_report.json (relatório da T-026, não é base) e
# regras_competencia.jsonl (insumo do recálculo, que o harness não faz).
COPY --chmod=0444 \
     worker/sandbox/data/domrock/rh.jsonl \
     worker/sandbox/data/domrock/vendas.jsonl \
     worker/sandbox/data/domrock/comissoes.jsonl \
     worker/sandbox/data/domrock/eventos_rh.jsonl \
     worker/sandbox/data/domrock/schema.json \
     ./sandbox/data/domrock/
COPY --chmod=0444 \
     worker/sandbox/data/domrock/baselines/baseline-2025-08.jsonl \
     worker/sandbox/data/domrock/baselines/baseline-2025-09.jsonl \
     worker/sandbox/data/domrock/baselines/baseline-2025-10.jsonl \
     worker/sandbox/data/domrock/baselines/baseline-2025-11.jsonl \
     worker/sandbox/data/domrock/baselines/baseline-2025-12.jsonl \
     worker/sandbox/data/domrock/baselines/manifesto.json \
     ./sandbox/data/domrock/baselines/
COPY --chmod=0444 \
     worker/sandbox/data/domrock/baselines/auditoria/baseline-2025-08.jsonl \
     worker/sandbox/data/domrock/baselines/auditoria/baseline-2025-09.jsonl \
     worker/sandbox/data/domrock/baselines/auditoria/baseline-2025-10.jsonl \
     worker/sandbox/data/domrock/baselines/auditoria/baseline-2025-11.jsonl \
     worker/sandbox/data/domrock/baselines/auditoria/baseline-2025-12.jsonl \
     ./sandbox/data/domrock/baselines/auditoria/

USER appuser

# Sem shell no caminho de execução, sem HEALTHCHECK, sem EXPOSE, sem VOLUME: é um container
# de um tiro, sem rede, que lê o payload no stdin e escreve o envelope no stdout.
ENTRYPOINT ["python", "-m", "app.sandbox.executor"]
