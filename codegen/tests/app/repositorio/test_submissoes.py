from typing import Any
from uuid import uuid4

import pytest

from app.repositorio.submissoes import TranscricaoIndisponivelError, buscar_transcricao
from tests.app.repositorio.test_regras import _sessionmaker


async def test_le_somente_transcricao_por_id_sem_buscar_binario() -> None:
    submissao_id = uuid4()
    sessoes = _sessionmaker({"transcricao": "  Texto privado da regra.  "})

    assert await buscar_transcricao(sessoes, submissao_id) == "  Texto privado da regra.  "

    consulta, parametros = sessoes.sessao.executado_com
    assert str(consulta) == "SELECT transcricao FROM submissoes WHERE id = :submissao_id"
    assert parametros == {"submissao_id": submissao_id}


@pytest.mark.parametrize(
    "linha", [None, {"transcricao": None}, {"transcricao": ""}, {"transcricao": " \n\t"}]
)
async def test_transcricao_indisponivel_e_falha_permanente_sanitizada(
    linha: dict[str, Any] | None,
) -> None:
    with pytest.raises(TranscricaoIndisponivelError) as falha:
        await buscar_transcricao(_sessionmaker(linha), uuid4())

    assert falha.value.etapa == "extracao_parametros"
    assert str(falha.value) == "Transcription unavailable"
    assert falha.value.__context__ is None
