#!/usr/bin/env python3
# Popula um banco synapse_db local com dados de demonstração:
#   - as contas develop@synapse.com e staging@synapse.com (usuarios);
#   - três jobs de ponta a ponta (submissao -> regra -> código gerado ->
#     resultado -> simulação), um para cada desfecho de resultados_simulacao:
#     viável, inviável e assercao_violada.
#
# Conecta como o dono do schema (POSTGRES_USER/POSTGRES_PASSWORD) para poder
# escrever em todas as tabelas, incluindo as de produtor único (prompts,
# codigos_gerados, resultados_simulacao, ...) que em produção só codegen e
# worker inserem. É uma decisão deliberada para este script: simplicidade de
# uma única conexão, ao custo de não exercitar os GRANTs por serviço.
#
# Uso:
#   pip install -r deploy/scripts/requirements.txt
#   POSTGRES_PASSWORD=... SEED_USERS_PASSWORD=... python deploy/scripts/seed.py
#
# Idempotente: os ids são derivados deterministicamente (uuid5) da chave de
# cada cenário, e todo INSERT usa ON CONFLICT (id) DO NOTHING. Rodar de novo
# não duplica dados nem falha.
#
# A senha de login das duas contas nunca fica hardcoded aqui: vem de
# SEED_USERS_PASSWORD, lida em tempo de execução, seguindo a regra do
# api/AGENTS.md que proíbe segredo real em arquivo versionado.
from __future__ import annotations

import hashlib
import json
import os
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import bcrypt
import psycopg2
import psycopg2.extras

REQUIRED_ENV_VARS = ("SEED_USERS_PASSWORD",)

SEED_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://synapse.local/deploy/scripts/seed.py")

# Deslocamentos, em minutos a partir de jobs.criado_em, comuns aos três
# cenários: regra confirmada, chamada ao modelo, código extraído e início da
# simulação sempre seguem essa mesma micro-sequência interna.
REGRA_OFFSET = 3
PROMPT_OFFSET = 6
RESPOSTA_OFFSET = 7
CODIGO_OFFSET = 8
SIMULACAO_OFFSET = 11

UPSERT_USUARIO_SQL = """
    INSERT INTO usuarios (login, senha_hash, nome, papel, ativo, criado_em)
    VALUES (%(login)s, %(senha_hash)s, %(nome)s, %(papel)s, true, now())
    ON CONFLICT (login) DO UPDATE SET
        senha_hash = EXCLUDED.senha_hash,
        nome = EXCLUDED.nome,
        papel = EXCLUDED.papel,
        atualizado_em = now()
    RETURNING id
"""

USUARIOS = (
    {"login": "develop@synapse.com", "nome": "Desenvolvimento", "papel": "profissional_rh"},
    {"login": "staging@synapse.com", "nome": "Staging", "papel": "auditor"},
)


# ---------------------------------------------------------------------------
# Cenários de demonstração
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Transicao:
    status_anterior: str | None
    status_novo: str
    ator: str
    minutos: int
    motivo: str | None = None


@dataclass(frozen=True)
class Trilha:
    no: str
    minutos: int
    conclusao: dict


@dataclass(frozen=True)
class Resultado:
    status: str
    assercoes: list
    totais: dict | None = None
    veredito: str | None = None
    decomposicao: dict | None = None


@dataclass(frozen=True)
class Acao:
    acao: str
    minutos: int


@dataclass(frozen=True)
class Cenario:
    chave: str
    usuario_login: str
    base: datetime
    vigencia_inicio: str
    vigencia_fim: str
    loja: list
    marca: list
    cargo: list
    percentual: float
    competencias: list
    orcamento: float
    resultado: Resultado
    transicoes: list
    trilhas: list
    resultado_minutos: int = 20
    acao: Acao | None = None
    explicacao_texto: str | None = None


def cenarios() -> list[Cenario]:
    assercoes_ok = [
        {"nome": "sem_comissao_negativa", "resultado": "ok", "detalhe": None},
        {"nome": "sem_comissao_sem_venda", "resultado": "ok", "detalhe": None},
        {"nome": "soma_loja_igual_soma_matricula", "resultado": "ok", "detalhe": None},
    ]
    decomposicao_padrao = {
        "elemento": {"nucleo.percentual": 11788.00},
        "loja": {"13": 11788.00},
        "marca": {"10": 11788.00},
        "cargo": {"100": 11788.00},
        "competencia": {"2025-11": 11788.00},
    }

    viavel = Cenario(
        chave="job-viavel",
        usuario_login="develop@synapse.com",
        base=datetime(2025, 11, 20, 9, 0, tzinfo=timezone.utc),
        vigencia_inicio="2025-11",
        vigencia_fim="2025-11",
        loja=["13"],
        marca=["10"],
        cargo=["100"],
        percentual=0.025,
        competencias=["2025-11"],
        orcamento=500000.00,
        resultado=Resultado(
            status="sucesso",
            veredito="viavel",
            totais={
                "baseline": 480312.00,
                "simulado": 492100.00,
                "diferenca_abs": 11788.00,
                "diferenca_pct": 0.0245,
                "orcamento": 500000.00,
            },
            assercoes=assercoes_ok,
            decomposicao=decomposicao_padrao,
        ),
        transicoes=[
            Transicao(None, "aguardando_confirmacao_parametros", "sistema", 0),
            Transicao("aguardando_confirmacao_parametros", "gerando_regra", "usuario", 2),
            Transicao("gerando_regra", "simulando", "evento", 10),
            Transicao("simulando", "aguardando_decisao_usuario", "evento", 21),
            Transicao("aguardando_decisao_usuario", "liberado", "usuario", 30),
        ],
        trilhas=[
            Trilha(
                "confirmacao",
                REGRA_OFFSET,
                {
                    "resumo": "parâmetros do formulário confirmados sem alterações",
                    "fontes": ["submissao-formulario"],
                },
            ),
            Trilha(
                "geracao_codigo",
                CODIGO_OFFSET + 1,
                {
                    "resumo": "código gerado implementando o núcleo",
                    "elementos_implementados": ["nucleo.percentual"],
                    "fontes": ["base_vendas", "base_rh"],
                },
            ),
            Trilha(
                "delegacao_worker",
                SIMULACAO_OFFSET,
                {"resumo": "execução delegada ao worker"},
            ),
            Trilha(
                "interpretacao_resultado",
                22,
                {
                    "resumo": "diferença concentrada na loja 13",
                    "diagnostico": "o percentual da loja 13 respondeu por toda a variação",
                    "concentracao": ["13", "nucleo.percentual"],
                },
            ),
            Trilha(
                "decisao",
                23,
                {"resumo": "resultado viável dentro do orçamento; segue para explicação"},
            ),
            Trilha(
                "explicacao",
                25,
                {"resumo": "regra confirmada com um elemento, sem correções do usuário"},
            ),
        ],
        acao=Acao("confirmar_liberar", 30),
        explicacao_texto=(
            "A regra de +2,5% para a loja 13 (marca 10, cargo 100) em novembro/2025 elevou "
            "o comissionamento de R$ 480.312,00 para R$ 492.100,00, uma diferença de "
            "R$ 11.788,00 (+2,45%). O valor ficou dentro do orçamento de R$ 500.000,00 "
            "informado, e toda a diferença é explicada pelo próprio percentual do núcleo, "
            "sem elementos adicionais."
        ),
    )

    inviavel = Cenario(
        chave="job-inviavel",
        usuario_login="develop@synapse.com",
        base=datetime(2025, 11, 21, 9, 0, tzinfo=timezone.utc),
        vigencia_inicio="2025-11",
        vigencia_fim="2025-11",
        loja=["13"],
        marca=["10"],
        cargo=["100"],
        percentual=0.025,
        competencias=["2025-11"],
        orcamento=485000.00,
        resultado=Resultado(
            status="sucesso",
            veredito="inviavel",
            totais={
                "baseline": 480312.00,
                "simulado": 492100.00,
                "diferenca_abs": 11788.00,
                "diferenca_pct": 0.0245,
                "orcamento": 485000.00,
            },
            assercoes=assercoes_ok,
            decomposicao=decomposicao_padrao,
        ),
        transicoes=[
            Transicao(None, "aguardando_confirmacao_parametros", "sistema", 0),
            Transicao("aguardando_confirmacao_parametros", "gerando_regra", "usuario", 2),
            Transicao("gerando_regra", "simulando", "evento", 10),
            Transicao("simulando", "simulacao_inviavel", "evento", 21),
            Transicao(
                "simulacao_inviavel",
                "arquivado",
                "usuario",
                40,
                motivo=(
                    "orçamento de R$ 485.000,00 insuficiente para a regra simulada; "
                    "usuário optou por arquivar sem propor alternativa"
                ),
            ),
        ],
        trilhas=[
            Trilha(
                "confirmacao",
                REGRA_OFFSET,
                {
                    "resumo": "parâmetros do formulário confirmados sem alterações",
                    "fontes": ["submissao-formulario"],
                },
            ),
            Trilha(
                "geracao_codigo",
                CODIGO_OFFSET + 1,
                {
                    "resumo": "código gerado implementando o núcleo",
                    "elementos_implementados": ["nucleo.percentual"],
                    "fontes": ["base_vendas", "base_rh"],
                },
            ),
            Trilha(
                "delegacao_worker",
                SIMULACAO_OFFSET,
                {"resumo": "execução delegada ao worker"},
            ),
            Trilha(
                "interpretacao_resultado",
                22,
                {
                    "resumo": "diferença concentrada na loja 13",
                    "diagnostico": "o percentual da loja 13 respondeu por toda a variação",
                    "concentracao": ["13", "nucleo.percentual"],
                },
            ),
            Trilha(
                "decisao",
                23,
                {
                    "resumo": "resultado inviável: custo simulado excede o orçamento",
                    "diagnostico": "faltariam R$ 7.100,00 para caber no orçamento informado",
                },
            ),
        ],
        acao=Acao("arquivar", 40),
        explicacao_texto=None,
    )

    assercao_violada = Cenario(
        chave="job-assercao-violada",
        usuario_login="staging@synapse.com",
        base=datetime(2025, 12, 2, 9, 0, tzinfo=timezone.utc),
        vigencia_inicio="2025-12",
        vigencia_fim="2025-12",
        loja=["58"],
        marca=["20"],
        cargo=["300"],
        percentual=0.04,
        competencias=["2025-12"],
        orcamento=300000.00,
        resultado=Resultado(
            status="assercao_violada",
            veredito=None,
            totais=None,
            decomposicao=None,
            assercoes=[
                {"nome": "sem_comissao_negativa", "resultado": "ok", "detalhe": None},
                {
                    "nome": "sem_comissao_sem_venda",
                    "resultado": "violada",
                    "detalhe": (
                        "2025-12, matrícula MATRIC-118: comissão de R$ 42,10 sem venda "
                        "registrada no período"
                    ),
                },
                {"nome": "soma_loja_igual_soma_matricula", "resultado": "ok", "detalhe": None},
            ],
        ),
        resultado_minutos=15,
        transicoes=[
            Transicao(None, "aguardando_confirmacao_parametros", "sistema", 0),
            Transicao("aguardando_confirmacao_parametros", "gerando_regra", "usuario", 2),
            Transicao("gerando_regra", "simulando", "evento", 10),
            Transicao(
                "simulando",
                "erro",
                "evento",
                16,
                motivo=(
                    "asserção 'sem_comissao_sem_venda' violada no sandbox; "
                    "resultado descartado"
                ),
            ),
        ],
        trilhas=[
            Trilha(
                "confirmacao",
                REGRA_OFFSET,
                {
                    "resumo": "parâmetros do formulário confirmados sem alterações",
                    "fontes": ["submissao-formulario"],
                },
            ),
            Trilha(
                "geracao_codigo",
                CODIGO_OFFSET + 1,
                {
                    "resumo": "código gerado implementando o núcleo",
                    "elementos_implementados": ["nucleo.percentual"],
                    "fontes": ["base_vendas", "base_rh"],
                },
            ),
            Trilha(
                "delegacao_worker",
                15,
                {
                    "resumo": "execução retornou assercao_violada; job interrompido",
                    "diagnostico": "asserção sem_comissao_sem_venda violada em 2025-12",
                },
            ),
        ],
        acao=None,
        explicacao_texto=None,
    )

    return [viavel, inviavel, assercao_violada]


# ---------------------------------------------------------------------------
# Conteúdo dos artefatos (prompt / resposta / código)
# ---------------------------------------------------------------------------


def nucleo_payload(cenario: Cenario) -> dict:
    return {
        "vigencia": {"inicio": cenario.vigencia_inicio, "fim": cenario.vigencia_fim},
        "loja": cenario.loja,
        "marca": cenario.marca,
        "cargo": cenario.cargo,
        "percentual": cenario.percentual,
    }


def canonical_hash(nucleo: dict, especificacoes: list) -> str:
    payload = {"nucleo": nucleo, "especificacoes": especificacoes}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def modelo_llm() -> dict:
    return {
        "provedor": "openai",
        "modelo": "gpt-4.1",
        "versao": "2025-04-14",
        "parametros": {"temperature": 0, "top_p": 1, "seed": 42},
    }


def prompt_conteudo(nucleo: dict) -> str:
    return (
        "Gere o código Python que calcula o comissionamento para a regra confirmada:\n"
        f"vigência {nucleo['vigencia']['inicio']} a {nucleo['vigencia']['fim']}, "
        f"loja(s) {', '.join(nucleo['loja'])}, marca(s) {', '.join(nucleo['marca'])}, "
        f"cargo(s) {', '.join(nucleo['cargo'])}, percentual {nucleo['percentual']}.\n"
        "Use as bases RH, Vendas e Comissionamento do sandbox; declare no retorno quais "
        "elementos do vocabulário (nucleo.percentual) o código implementa."
    )


def codigo_fonte(nucleo: dict) -> str:
    return (
        "def calcular_comissao(vendas, rh, competencias):\n"
        f"    lojas = {nucleo['loja']!r}\n"
        f"    marcas = {nucleo['marca']!r}\n"
        f"    cargos = {nucleo['cargo']!r}\n"
        f"    percentual = {nucleo['percentual']!r}  # nucleo.percentual\n"
        "    resultado = []\n"
        "    for venda in vendas:\n"
        "        colaborador = rh[venda['matricula']]\n"
        "        if venda['cod_loja'] not in lojas:\n"
        "            continue\n"
        "        if venda['cod_marca'] not in marcas:\n"
        "            continue\n"
        "        if colaborador['cod_cargo'] not in cargos:\n"
        "            continue\n"
        "        resultado.append({\n"
        "            'matricula': venda['matricula'],\n"
        "            'elemento': 'nucleo.percentual',\n"
        "            'valor': venda['vlr_venda'] * percentual,\n"
        "        })\n"
        "    return resultado\n"
    )


def resposta_modelo_conteudo(fonte: str) -> str:
    return "```python\n" + fonte + "```"


# ---------------------------------------------------------------------------
# Inserção
# ---------------------------------------------------------------------------

TRILHA_REFERENCIAS = {
    "confirmacao": ("regra_id",),
    "geracao_codigo": ("regra_id", "prompt_id", "codigo_gerado_id"),
    "delegacao_worker": ("regra_id", "simulacao_id"),
    "interpretacao_resultado": ("regra_id", "simulacao_id"),
    "decisao": ("regra_id", "simulacao_id"),
    "explicacao": ("regra_id", "simulacao_id", "explicacao_id"),
}


def seed_id(*parts: str) -> uuid.UUID:
    return uuid.uuid5(SEED_NAMESPACE, ":".join(parts))


def adapt(value):
    # Dict sempre vira jsonb. list é ambíguo (jsonb array vs. text[] nativo, como
    # jobs.competencias) e por isso não é convertido aqui - quem monta a linha
    # embrulha explicitamente com psycopg2.extras.Json quando o destino é jsonb.
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return psycopg2.extras.Json(value)
    return value


def insert(cur, table: str, row: dict) -> None:
    columns = list(row.keys())
    values = [adapt(row[column]) for column in columns]
    placeholders = ", ".join(["%s"] * len(columns))
    cur.execute(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
        "ON CONFLICT (id) DO NOTHING",
        values,
    )


def seed_usuarios(cur, senha_hash: str) -> dict[str, uuid.UUID]:
    ids: dict[str, uuid.UUID] = {}
    for usuario in USUARIOS:
        cur.execute(
            UPSERT_USUARIO_SQL,
            {
                "login": usuario["login"],
                "nome": usuario["nome"],
                "papel": usuario["papel"],
                "senha_hash": senha_hash,
            },
        )
        ids[usuario["login"]] = cur.fetchone()[0]
    return ids


def seed_cenario(cur, cenario: Cenario, usuario_ids: dict[str, uuid.UUID]) -> None:
    usuario_id = usuario_ids[cenario.usuario_login]
    ids = {
        "submissao": seed_id(cenario.chave, "submissao"),
        "job": seed_id(cenario.chave, "job"),
        "regra": seed_id(cenario.chave, "regra"),
        "prompt": seed_id(cenario.chave, "prompt"),
        "resposta_modelo": seed_id(cenario.chave, "resposta_modelo"),
        "codigo_gerado": seed_id(cenario.chave, "codigo_gerado"),
        "resultado": seed_id(cenario.chave, "resultado"),
        "simulacao": seed_id(cenario.chave, "simulacao"),
        "explicacao": seed_id(cenario.chave, "explicacao"),
    }

    nucleo = nucleo_payload(cenario)
    especificacoes: list = []
    criado_em = cenario.base
    fonte = codigo_fonte(nucleo)

    insert(
        cur,
        "submissoes",
        {
            "id": ids["submissao"],
            "usuario_id": usuario_id,
            "tipo": "formulario",
            "conteudo": {"nucleo": nucleo, "texto_livre": None},
            "criado_em": criado_em,
        },
    )

    status_final = cenario.transicoes[-1].status_novo
    insert(
        cur,
        "jobs",
        {
            "id": ids["job"],
            "status": status_final,
            "usuario_id": usuario_id,
            "submissao_id": ids["submissao"],
            "competencias": cenario.competencias,
            "orcamento": cenario.orcamento,
            "criado_em": criado_em,
            "iniciado_em": criado_em + timedelta(minutes=cenario.transicoes[1].minutos),
            "finalizado_em": criado_em + timedelta(minutes=cenario.transicoes[-1].minutos),
            "tentativas": 0,
        },
    )

    for transicao in cenario.transicoes:
        insert(
            cur,
            "job_transicoes",
            {
                "id": seed_id(cenario.chave, "transicao", transicao.status_novo),
                "job_id": ids["job"],
                "status_anterior": transicao.status_anterior,
                "status_novo": transicao.status_novo,
                "ocorrido_em": criado_em + timedelta(minutes=transicao.minutos),
                "ator": transicao.ator,
                "motivo": transicao.motivo,
            },
        )

    if cenario.acao is not None:
        insert(
            cur,
            "job_acoes",
            {
                "id": seed_id(cenario.chave, "acao"),
                "job_id": ids["job"],
                "acao": cenario.acao.acao,
                "executado_em": criado_em + timedelta(minutes=cenario.acao.minutos),
            },
        )

    insert(
        cur,
        "regras",
        {
            "id": ids["regra"],
            "job_id": ids["job"],
            "versao": 1,
            "origem": "confirmacao_usuario",
            "nucleo": nucleo,
            "especificacoes": psycopg2.extras.Json(especificacoes),
            "hash": canonical_hash(nucleo, especificacoes),
            "criada_em": criado_em + timedelta(minutes=REGRA_OFFSET),
        },
    )

    insert(
        cur,
        "prompts",
        {
            "id": ids["prompt"],
            "job_id": ids["job"],
            "no": "geracao_codigo",
            "conteudo": prompt_conteudo(nucleo),
            "modelo": modelo_llm(),
            "criado_em": criado_em + timedelta(minutes=PROMPT_OFFSET),
        },
    )
    insert(
        cur,
        "respostas_modelo",
        {
            "id": ids["resposta_modelo"],
            "job_id": ids["job"],
            "prompt_id": ids["prompt"],
            "conteudo": resposta_modelo_conteudo(fonte),
            "consumo_tokens": {"tokens_in": 2480, "tokens_out": 512, "custo_usd": 0.0187},
            "criado_em": criado_em + timedelta(minutes=RESPOSTA_OFFSET),
        },
    )
    insert(
        cur,
        "codigos_gerados",
        {
            "id": ids["codigo_gerado"],
            "job_id": ids["job"],
            "regra_id": ids["regra"],
            "linguagem": "python",
            "fonte": fonte,
            "prompt_id": ids["prompt"],
            "criado_em": criado_em + timedelta(minutes=CODIGO_OFFSET),
        },
    )

    resultado = cenario.resultado
    insert(
        cur,
        "resultados_simulacao",
        {
            "id": ids["resultado"],
            "job_id": ids["job"],
            "codigo_gerado_id": ids["codigo_gerado"],
            "status": resultado.status,
            "totais": resultado.totais,
            "veredito": resultado.veredito,
            "assercoes": psycopg2.extras.Json(resultado.assercoes),
            "decomposicao": resultado.decomposicao,
            "criado_em": criado_em + timedelta(minutes=cenario.resultado_minutos),
        },
    )
    insert(
        cur,
        "simulacoes",
        {
            "id": ids["simulacao"],
            "criado_em": criado_em + timedelta(minutes=SIMULACAO_OFFSET),
            "regra_id": ids["regra"],
            "job_id": ids["job"],
            "codigo_gerado_id": ids["codigo_gerado"],
            "resultado_id": ids["resultado"],
            "flag_baixa_rastreabilidade": False,
        },
    )

    if cenario.explicacao_texto is not None:
        insert(
            cur,
            "explicacoes",
            {
                "id": ids["explicacao"],
                "resultado_id": ids["resultado"],
                "texto": cenario.explicacao_texto,
                "aderencia_conferida": True,
                "criado_em": criado_em + timedelta(minutes=25),
            },
        )

    for trilha in cenario.trilhas:
        row = {
            "id": seed_id(cenario.chave, "trilha", trilha.no),
            "evento_id": seed_id(cenario.chave, "evento", trilha.no),
            "job_id": ids["job"],
            "no": trilha.no,
            "concluido_em": criado_em + timedelta(minutes=trilha.minutos),
            "conclusao": trilha.conclusao,
        }
        for referencia in TRILHA_REFERENCIAS.get(trilha.no, ()):
            row[referencia] = ids[referencia.removesuffix("_id")]
        insert(cur, "trilhas_auditoria", row)

    insert(
        cur,
        "outbox_events",
        {
            "id": seed_id(cenario.chave, "outbox", "regra-submetida"),
            "job_id": ids["job"],
            "tipo": "regra-submetida",
            "payload": {
                "job_id": str(ids["job"]),
                "submissao_id": str(ids["submissao"]),
                "origem": "formulario",
                "competencias": cenario.competencias,
                "regra_id": str(ids["regra"]),
            },
            "criado_em": criado_em,
            "publicado_em": criado_em + timedelta(seconds=5),
            "tentativas": 1,
        },
    )
    insert(
        cur,
        "outbox_events",
        {
            "id": seed_id(cenario.chave, "outbox", "parametros-confirmados"),
            "job_id": ids["job"],
            "tipo": "parametros-confirmados",
            "payload": {"job_id": str(ids["job"]), "regra_id": str(ids["regra"])},
            "criado_em": criado_em + timedelta(minutes=2),
            "publicado_em": criado_em + timedelta(minutes=2, seconds=5),
            "tentativas": 1,
        },
    )


# ---------------------------------------------------------------------------
# Ponto de entrada
# ---------------------------------------------------------------------------


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def connect():
    return psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=os.environ.get("POSTGRES_PORT", "5432"),
        dbname=os.environ.get("POSTGRES_DB", "synapse_db"),
        user=os.environ.get("POSTGRES_USER", "postgres"),
        password=os.environ.get("POSTGRES_PASSWORD", "postgres"),
    )


def main() -> None:
    missing = [name for name in REQUIRED_ENV_VARS if not os.environ.get(name)]
    if missing:
        print(f"seed: variáveis obrigatórias ausentes: {', '.join(missing)}", file=sys.stderr)
        raise SystemExit(1)

    senha_hash = hash_password(os.environ["SEED_USERS_PASSWORD"])
    connection = connect()
    try:
        with connection, connection.cursor() as cur:
            usuario_ids = seed_usuarios(cur, senha_hash)
            for cenario in cenarios():
                seed_cenario(cur, cenario, usuario_ids)
    finally:
        connection.close()

    print(
        "seed: usuários (develop@synapse.com, staging@synapse.com) e pipeline de "
        "demonstração prontos (3 jobs: viável, inviável, assercao_violada)"
    )


if __name__ == "__main__":
    main()
