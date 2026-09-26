import json
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from shutil import copytree
from typing import Any
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from pydantic import TypeAdapter, ValidationError
from referencing import Registry, Resource

from app.estado import EstadoGrafo, desserializar_estado, serializar_estado
from app.representacao_regra import RepresentacaoRegra
from app.tipos_estado import Competencia, Origem, Veredito

CONTRATOS = Path(__file__).resolve().parents[3] / "contracts"
JOB_ID = UUID("3f2b1c40-0d18-4a51-9f2e-6c1d9a77b021")
RESULTADO_ID = UUID("b81e0f4c-52a9-4f0b-8a3d-7c2e5d10ab93")


def carregar_regra(nome: str = "representacao-regra-elementos.json") -> dict[str, Any]:
    with (CONTRATOS / "examples" / "domain" / nome).open(encoding="utf-8") as arquivo:
        return dict(json.load(arquivo, parse_float=Decimal))


@pytest.fixture
def validador_oficial() -> Draft202012Validator:
    esquemas = [
        json.loads(caminho.read_text(encoding="utf-8"))
        for caminho in (CONTRATOS / "domain").glob("*.schema.json")
    ]
    registro = Registry().with_resources(
        (esquema["$id"], Resource.from_contents(esquema)) for esquema in esquemas
    )
    esquema = json.loads(
        (CONTRATOS / "domain" / "representacao-regra.schema.json").read_text(encoding="utf-8")
    )
    return Draft202012Validator(esquema, registry=registro, format_checker=FormatChecker())


@pytest.fixture
def inicial() -> EstadoGrafo:
    return EstadoGrafo(job_id=JOB_ID, origem="voz", competencias=["2025-08", "2025-11"])


@pytest.fixture
def completo() -> EstadoGrafo:
    regra = carregar_regra()
    regra["especificacoes"][1]["data_inicial"] = date(2025, 11, 24)
    regra["especificacoes"][1]["data_final"] = date(2025, 11, 30)
    regra["especificacoes"][0]["efeito"]["valor"] = Decimal("1234567890.123456789")
    return EstadoGrafo(
        job_id=JOB_ID,
        origem="formulario",
        competencias=["2025-08", "2025-11"],
        orcamento=Decimal("1234567890.123456789"),
        representacao_regra=RepresentacaoRegra.model_validate(regra),
        codigo_gerado="def regra(contexto):\n    return contexto\n",
        referencia_resultado=RESULTADO_ID,
        veredito_recebido="inviavel",
        historico_sugestoes=[RepresentacaoRegra.model_validate(carregar_regra())],
    )


def test_estado_inicial_preserva_ausencias_ao_retomar(inicial: EstadoGrafo) -> None:
    restaurado = desserializar_estado(serializar_estado(inicial))

    assert restaurado == inicial
    assert restaurado.model_dump() == {
        "job_id": JOB_ID,
        "origem": "voz",
        "competencias": ["2025-08", "2025-11"],
        "orcamento": None,
        "representacao_regra": None,
        "codigo_gerado": None,
        "referencia_resultado": None,
        "veredito_recebido": None,
        "historico_sugestoes": [],
    }
    assert isinstance(restaurado.job_id, UUID)


def test_estado_parcial_aguardando_worker_preserva_regra_e_codigo() -> None:
    parcial = EstadoGrafo(
        job_id=JOB_ID,
        origem="reprocessamento",
        competencias=["2025-11"],
        orcamento=Decimal("485000"),
        representacao_regra=RepresentacaoRegra.model_validate(carregar_regra()),
        codigo_gerado="def regra(contexto):\n    return contexto\n",
    )

    restaurado = desserializar_estado(serializar_estado(parcial))

    assert restaurado == parcial
    assert restaurado.referencia_resultado is None
    assert restaurado.veredito_recebido is None
    assert restaurado.historico_sugestoes == []


def test_estado_completo_preserva_tipos_e_precisao(completo: EstadoGrafo) -> None:
    restaurado = desserializar_estado(serializar_estado(completo))

    assert restaurado == completo
    assert isinstance(restaurado.job_id, UUID)
    assert isinstance(restaurado.referencia_resultado, UUID)
    assert isinstance(restaurado.orcamento, Decimal)
    assert restaurado.orcamento.as_tuple() == Decimal("1234567890.123456789").as_tuple()
    assert isinstance(restaurado.representacao_regra, RepresentacaoRegra)
    elementos = restaurado.representacao_regra.root["especificacoes"]
    assert isinstance(elementos, list)
    janela = elementos[1]
    faixa = elementos[0]
    assert isinstance(janela, dict)
    assert isinstance(janela["data_inicial"], date)
    assert isinstance(janela["data_final"], date)
    assert isinstance(faixa, dict)
    efeito = faixa["efeito"]
    assert isinstance(efeito, dict)
    assert isinstance(efeito["valor"], Decimal)
    assert efeito["valor"].as_tuple() == Decimal("1234567890.123456789").as_tuple()
    assert len(restaurado.historico_sugestoes) == 1
    assert isinstance(restaurado.historico_sugestoes[0], RepresentacaoRegra)


@pytest.mark.parametrize(
    "nome",
    [
        "representacao-regra.json",
        "representacao-regra-elementos.json",
        "representacao-regra-generico.json",
    ],
)
def test_regra_no_estado_valida_contrato_antes_e_depois_do_round_trip(
    nome: str, inicial: EstadoGrafo, validador_oficial: Draft202012Validator
) -> None:
    regra = carregar_regra(nome)
    inicial.representacao_regra = RepresentacaoRegra.model_validate(regra)
    validador_oficial.validate(inicial.representacao_regra.para_contrato())

    restaurado = desserializar_estado(serializar_estado(inicial))

    assert restaurado == inicial
    assert restaurado.representacao_regra is not None
    validador_oficial.validate(restaurado.representacao_regra.para_contrato())
    assert restaurado.representacao_regra.para_contrato() == regra


def test_regra_com_tipos_python_tambem_valida_contrato(
    completo: EstadoGrafo, validador_oficial: Draft202012Validator
) -> None:
    restaurado = desserializar_estado(serializar_estado(completo))

    assert restaurado.representacao_regra is not None
    validador_oficial.validate(restaurado.representacao_regra.para_contrato())


def test_historicos_nao_compartilham_lista(inicial: EstadoGrafo) -> None:
    outro = EstadoGrafo(job_id=JOB_ID, origem="voz", competencias=["2025-11"])

    inicial.historico_sugestoes.append(RepresentacaoRegra.model_validate(carregar_regra()))

    assert outro.historico_sugestoes == []


@pytest.mark.parametrize("campo", ["representacao_regra", "historico_sugestoes"])
@pytest.mark.parametrize(
    "regra",
    [
        {"nucleo": {}},
        {"nucleo": {}, "especificacoes": [{"construto": "generico", "descricao": "bônus"}]},
        {"nucleo": {"percentual": "0.02"}, "especificacoes": []},
        {"nucleo": {}, "especificacoes": [{"ref": "elem.1", "construto": "desconhecido"}]},
        {"nucleo": {}, "especificacoes": [{"ref": "elem.1", "construto": "faixa_valor"}]},
    ],
)
def test_recusa_representacao_incompativel(
    campo: str, regra: dict[str, Any], inicial: EstadoGrafo
) -> None:
    valores = inicial.model_dump()
    valores[campo] = [regra] if campo == "historico_sugestoes" else regra

    with pytest.raises(ValidationError, match="Representação incompatível com T-004"):
        EstadoGrafo.model_validate(valores)


def test_recusa_data_invalida_na_janela(inicial: EstadoGrafo) -> None:
    regra = carregar_regra()
    regra["especificacoes"][1]["data_final"] = "2025-02-30"

    with pytest.raises(ValidationError, match="Representação incompatível com T-004"):
        EstadoGrafo.model_validate({**inicial.model_dump(), "representacao_regra": regra})


@pytest.mark.parametrize("valor", ["abc", "NaN", "Infinity", "-0.01", 0.1])
def test_recusa_orcamento_invalido(valor: object, inicial: EstadoGrafo) -> None:
    with pytest.raises(ValidationError):
        EstadoGrafo.model_validate({**inicial.model_dump(), "orcamento": valor})


@pytest.mark.parametrize("valor", [[], ["2025-13"], ["2025-00"], ["2025-1"], ["2025-11-01"]])
def test_recusa_competencias_invalidas(valor: list[str], inicial: EstadoGrafo) -> None:
    with pytest.raises(ValidationError):
        EstadoGrafo.model_validate({**inicial.model_dump(), "competencias": valor})


@pytest.mark.parametrize(
    ("campo", "valor"),
    [("origem", "arquivo"), ("veredito_recebido", "aprovado"), ("job_id", "invalido")],
)
def test_recusa_identificadores_e_vocabulario_invalidos(
    campo: str, valor: str, inicial: EstadoGrafo
) -> None:
    with pytest.raises(ValidationError):
        EstadoGrafo.model_validate({**inicial.model_dump(), campo: valor})


@pytest.mark.parametrize("veredito", ["viavel", "inviavel", "indeterminado"])
def test_preserva_todos_os_vereditos_oficiais(veredito: str, inicial: EstadoGrafo) -> None:
    estado = EstadoGrafo.model_validate({**inicial.model_dump(), "veredito_recebido": veredito})

    assert desserializar_estado(serializar_estado(estado)) == estado


@pytest.mark.parametrize("campo", ["dataset", "vendas", "rh"])
def test_estado_recusa_campos_de_dados_brutos(campo: str, inicial: EstadoGrafo) -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        EstadoGrafo.model_validate({**inicial.model_dump(), campo: []})


def test_referencia_resultado_recusa_conteudo_do_resultado(inicial: EstadoGrafo) -> None:
    with pytest.raises(ValidationError):
        EstadoGrafo.model_validate({**inicial.model_dump(), "referencia_resultado": {"totais": {}}})


def test_serializacao_revalida_mutacoes_aninhadas(completo: EstadoGrafo) -> None:
    assert completo.representacao_regra is not None
    completo.representacao_regra.root.pop("nucleo")

    with pytest.raises(ValidationError, match="Representação incompatível com T-004"):
        serializar_estado(completo)


def test_round_trip_usa_serializador_oficial_sem_classes_da_aplicacao(
    completo: EstadoGrafo,
) -> None:
    tipo, dados = serializar_estado(completo)
    valores = JsonPlusSerializer(pickle_fallback=False, allowed_msgpack_modules=[]).loads_typed(
        (tipo, dados)
    )

    assert tipo == "msgpack"
    assert isinstance(dados, bytes)
    assert valores == completo.model_dump(mode="python")
    assert serializar_estado(completo) == (tipo, dados)


def test_desserializacao_funciona_em_outro_processo(completo: EstadoGrafo) -> None:
    tipo, dados = serializar_estado(completo)
    programa = (
        "import sys; from app.estado import desserializar_estado, serializar_estado; "
        "estado = desserializar_estado(('msgpack', sys.stdin.buffer.read())); "
        "sys.stdout.buffer.write(serializar_estado(estado)[1])"
    )

    processo = subprocess.run(
        [sys.executable, "-c", programa], input=dados, capture_output=True, check=True
    )

    assert desserializar_estado((tipo, processo.stdout)) == completo


def test_desserializacao_revalida_regra(inicial: EstadoGrafo) -> None:
    valores = {**inicial.model_dump(), "representacao_regra": {"nucleo": {}}}
    dados = JsonPlusSerializer(pickle_fallback=False).dumps_typed(valores)

    with pytest.raises(ValidationError, match="Representação incompatível com T-004"):
        desserializar_estado(dados)


def test_recusa_formato_pickle() -> None:
    with pytest.raises(ValueError, match="msgpack"):
        desserializar_estado(("pickle", b""))


def test_contratos_incorporados_sao_copias_exatas() -> None:
    incorporados = Path(__file__).resolve().parents[2] / "contracts" / "domain"
    fontes = {
        arquivo.name: arquivo.read_bytes()
        for arquivo in (CONTRATOS / "domain").glob("*.schema.json")
    }
    copias = {arquivo.name: arquivo.read_bytes() for arquivo in incorporados.glob("*.schema.json")}

    assert copias == fontes


@pytest.mark.parametrize("falha", ["jsonschema", "pydantic"])
@pytest.mark.parametrize("entrada", ["modelo", "construtor", "adapter", "estado", "historico"])
def test_erro_de_regra_nao_expoe_conteudo(falha: str, entrada: str, inicial: EstadoGrafo) -> None:
    regra = carregar_regra()
    segredo = "REGRA_CONFIDENCIAL_947281"
    regra[segredo] = segredo
    regra["nucleo"]["percentual"] = (
        "VALOR_SIGILOSO_829164" if falha == "jsonschema" else 987654321.125
    )

    with pytest.raises(ValidationError, match="Representação incompatível com T-004") as capturada:
        if entrada == "modelo":
            RepresentacaoRegra.model_validate(regra)
        elif entrada == "construtor":
            RepresentacaoRegra(regra)
        elif entrada == "adapter":
            TypeAdapter(RepresentacaoRegra).validate_python(regra)
        else:
            campo = "representacao_regra" if entrada == "estado" else "historico_sugestoes"
            valor = regra if entrada == "estado" else [regra]
            EstadoGrafo.model_validate({**inicial.model_dump(), campo: valor})

    assert "input_value" not in str(capturada.value)
    for publico in (str(capturada.value), repr(capturada.value.errors()), capturada.value.json()):
        assert segredo not in publico
        assert "VALOR_SIGILOSO_829164" not in publico
        assert "987654321.125" not in publico
        assert "percentual" not in publico


@pytest.mark.parametrize("mutacao", ["raiz", "aninhada", "float"])
def test_para_contrato_recusa_mutacao_invalida(mutacao: str) -> None:
    regra = RepresentacaoRegra.model_validate(carregar_regra())
    if mutacao == "raiz":
        regra.root.pop("nucleo")
    else:
        elementos = regra.root["especificacoes"]
        assert isinstance(elementos, list)
        elemento = elementos[0]
        assert isinstance(elemento, dict)
        if mutacao == "aninhada":
            elemento.pop("efeito")
        else:
            elemento["limite_inferior"] = 987654321.125

    with pytest.raises(ValueError, match="Representação incompatível com T-004") as capturada:
        regra.para_contrato()

    assert "input_value" not in str(capturada.value)
    assert "987654321.125" not in str(capturada.value)


def test_regra_preserva_extensoes_permitidas_pela_t004(
    validador_oficial: Draft202012Validator,
) -> None:
    regra = carregar_regra()
    regra["extensao"] = {"origem": "formulario"}
    regra["nucleo"]["extensao"] = True
    regra["especificacoes"][0]["extensao"] = ["campo_aditivo"]
    validador_oficial.validate(regra)

    assert RepresentacaoRegra.model_validate(regra).para_contrato() == regra


def test_tipos_do_estado_seguem_vocabulario_dos_contratos() -> None:
    submissao = json.loads(
        (CONTRATOS / "events" / "regra-submetida.schema.json").read_text(encoding="utf-8")
    )
    resultado = json.loads(
        (CONTRATOS / "events" / "simulacao-concluida.schema.json").read_text(encoding="utf-8")
    )
    comum = json.loads((CONTRATOS / "domain" / "comum.schema.json").read_text(encoding="utf-8"))

    assert TypeAdapter(Origem).json_schema()["enum"] == submissao["properties"]["origem"]["enum"]
    assert (
        TypeAdapter(Veredito).json_schema()["enum"] == resultado["properties"]["veredito"]["enum"]
    )
    assert (
        TypeAdapter(Competencia).json_schema()["pattern"]
        == comum["$defs"]["competencia"]["pattern"]
    )


def test_artefato_funciona_sem_acesso_a_contracts_do_monorepo(
    tmp_path: Path, completo: EstadoGrafo
) -> None:
    componente = Path(__file__).resolve().parents[2]
    copytree(componente / "app", tmp_path / "app")
    copytree(componente / "contracts", tmp_path / "contracts")
    tipo, dados = serializar_estado(completo)
    programa = (
        "import sys; sys.path.insert(0, sys.argv[1]); "
        "from app.estado import desserializar_estado, serializar_estado; "
        "estado = desserializar_estado(('msgpack', sys.stdin.buffer.read())); "
        "sys.stdout.buffer.write(serializar_estado(estado)[1])"
    )

    processo = subprocess.run(
        [sys.executable, "-I", "-c", programa, str(tmp_path)],
        cwd=tmp_path,
        input=dados,
        capture_output=True,
        check=True,
    )

    assert desserializar_estado((tipo, processo.stdout)) == completo
