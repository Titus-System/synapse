from typing import Any

import pytest

from app.extracao.registro import CONSTRUTOS_HABILITADOS, Construto
from app.tipos_estado import ValorRegra
from tests.app.extracao.test_motor import ELEMENTO, extrair, modelo_falso


@pytest.mark.parametrize("lancar", [False, True])
async def test_conversao_invalida_preserva_elemento_generico(
    monkeypatch: pytest.MonkeyPatch, lancar: bool
) -> None:
    def converter(elemento: dict[str, Any]) -> dict[str, ValorRegra]:
        if lancar:
            raise ValueError("conteudo privado da regra")
        return {"valor": 500}  # Falta o alvo obrigatório no contrato de bonus_fixo.

    monkeypatch.setitem(
        CONSTRUTOS_HABILITADOS,
        "bonus_fixo",
        Construto(propriedades={}, obrigatorios=(), instrucoes="Teste", converter=converter),
    )

    resultado = await extrair(
        modelo_falso({"nucleo": {}, "elementos": [ELEMENTO, ELEMENTO], "parametros": {}})
    )

    assert resultado.representacao.para_contrato() == {
        "nucleo": {},
        "especificacoes": [
            {"ref": f"elem.{i}", "construto": "generico", "descricao": ELEMENTO["descricao"]}
            for i in (1, 2)
        ],
    }
    assert [r.motivo for r in resultado.rebaixamentos] == ["campo_obrigatorio_ausente"] * 2
