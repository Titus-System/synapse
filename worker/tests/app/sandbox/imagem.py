"""O que a imagem do sandbox contém e o que ela não contém (T-033).

Uma lista só, usada por dois lados que precisam concordar: os testes sem Docker leem o
Dockerfile e conferem que ele copia exatamente isto; os testes com Docker inspecionam a
imagem construída e conferem que ela contém exatamente isto.
"""

from app.sandbox.carga import competencias_publicadas

# pandas mais o fecho transitivo que ele exige. Nada além: a lista da T-034 é "pandas e a
# biblioteca padrão", e cada pacote a mais é superfície de ataque.
DISTRIBUICOES_PERMITIDAS = frozenset(
    {"pandas", "numpy", "python-dateutil", "pytz", "six", "tzdata"}
)

MODULOS_DA_IMAGEM = frozenset(
    {
        "__init__.py",
        "ajustes_competencia.py",
        "assercoes.py",
        "carga.py",
        "envelope.py",
        "executor.py",
        "harness.py",
        "regras_base.py",
        "resultado.py",
    }
)

# daemon.py importa docker, app.config e app.core.logger; regras_competencia.py só serve
# para recomputar baselines, e aqui o baseline é dado congelado.
MODULOS_PROIBIDOS = frozenset({"daemon.py", "regras_competencia.py"})

DADOS_DA_IMAGEM = frozenset(
    {
        "rh.jsonl",
        "vendas.jsonl",
        "comissoes.jsonl",
        "eventos_rh.jsonl",
        "schema.json",
        "baselines/manifesto.json",
        *(f"baselines/baseline-{competencia}.jsonl" for competencia in competencias_publicadas()),
        *(
            f"baselines/auditoria/baseline-{competencia}.jsonl"
            for competencia in competencias_publicadas()
        ),
    }
)

# normalization_report.json é relatório da T-026, não é base; regras_competencia.jsonl é
# insumo do recálculo, que o harness não faz.
DADOS_PROIBIDOS = frozenset({"normalization_report.json", "regras_competencia.jsonl"})

# Módulos que só podem usar a biblioteca padrão. O envelope, em particular, precisa disso
# para o worker poder importá-lo sem tocar no caminho que executa código gerado.
MODULOS_SO_STDLIB = frozenset(
    {
        "__init__.py",
        "ajustes_competencia.py",
        "assercoes.py",
        "envelope.py",
        "regras_base.py",
        "resultado.py",
    }
)
