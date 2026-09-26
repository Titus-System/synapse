import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.contratos.mensagens import (
    ConclusaoDaTrilha,
    EtapaAlterada,
    ExecutarCodigo,
    ModeloContrato,
    NoConcluido,
    ParametrosConfirmados,
    RegraSubmetida,
    SimulacaoConcluida,
)

type TipoContrato = type[ModeloContrato]
DIRETORIO_EXEMPLOS = Path(__file__).resolve().parents[4] / "contracts" / "examples"


@pytest.mark.parametrize(
    ("caminho_relativo", "tipo_contrato"),
    [
        ("events/regra-submetida.json", RegraSubmetida),
        ("events/regra-submetida-voz.json", RegraSubmetida),
        ("events/parametros-confirmados.json", ParametrosConfirmados),
        ("events/simulacao-concluida.json", SimulacaoConcluida),
        ("events/executar-codigo.json", ExecutarCodigo),
        ("events/etapa-alterada.json", EtapaAlterada),
        ("events/no-concluido.json", NoConcluido),
    ],
)
def test_exemplos_de_evento_desserializam_nos_dtos(
    caminho_relativo: str, tipo_contrato: TipoContrato
) -> None:
    conteudo = (DIRETORIO_EXEMPLOS / caminho_relativo).read_text(encoding="utf-8-sig")

    dto = tipo_contrato.model_validate_json(conteudo)

    assert isinstance(dto, tipo_contrato)


def test_regra_submetida_rejeita_origem_incompativel() -> None:
    caminho_exemplo = DIRETORIO_EXEMPLOS / "events/regra-submetida.json"
    conteudo = json.loads(caminho_exemplo.read_text(encoding="utf-8-sig"))
    conteudo["origem"] = "origem_incompativel"

    with pytest.raises(ValidationError):
        RegraSubmetida.model_validate(conteudo)


def test_no_concluido_desserializa_a_conclusao_no_tipo_da_trilha() -> None:
    caminho_exemplo = DIRETORIO_EXEMPLOS / "events/no-concluido.json"
    conteudo = caminho_exemplo.read_text(encoding="utf-8-sig")

    evento = NoConcluido.model_validate_json(conteudo)

    assert evento.conclusao == ConclusaoDaTrilha(
        resumo="código gerado implementando 2 elementos",
        elementos_implementados=["nucleo.percentual", "elem.1"],
        fontes=["base_vendas", "base_rh"],
    )
