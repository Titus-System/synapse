import json
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatResult
from pydantic import Field

from app.prompts.geracao_codigo import montar_prompt_geracao
from scripts.gerar_casos_geracao import (
    CASOS_PADRAO,
    CasoInvalidoError,
    carregar_representacoes,
    gerar_casos,
    identificador_do_prompt,
    main,
)

_CASO_VALIDO = {
    "id": "caso-exemplo",
    "descricao": "x",
    "leitura": "x",
    "representacao": {"nucleo": {}, "especificacoes": []},
    "competencias": ["2025-08"],
}

# Só a assinatura importa para `extrair_codigo`; o corpo nunca roda aqui.
_FONTE_VALIDA = "def aplicar_regra(bases, apuracao_base, competencias):\n    return None\n"
_BLOCO_VALIDO = f"```python\n{_FONTE_VALIDA}```"


class FakeChatModel(GenericFakeChatModel):
    """Modelo roteirizado: devolve as respostas na ordem, com finish_reason STOP por padrão."""

    seen_messages: list[list[BaseMessage]] = Field(default_factory=list)

    def _generate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> ChatResult:
        self.seen_messages.append(list(messages))
        resultado = super()._generate(messages, *args, **kwargs)
        for geracao in resultado.generations:
            geracao.message.response_metadata.setdefault("finish_reason", "STOP")
        return resultado


def _instalar_modelo(
    monkeypatch: pytest.MonkeyPatch, respostas: Iterable[AIMessage]
) -> FakeChatModel:
    replies: Iterator[AIMessage] = iter(respostas)
    model = FakeChatModel(messages=replies)
    monkeypatch.setattr("scripts.gerar_casos_geracao.get_model", lambda nome: model)
    return model


def _escrever_caso(pasta: Path, caso_id: str, **sobrescritas: Any) -> Path:
    diretorio = pasta / caso_id
    diretorio.mkdir(parents=True)
    dados = {**_CASO_VALIDO, "id": caso_id, **sobrescritas}
    (diretorio / "caso.json").write_text(json.dumps(dados), encoding="utf-8")
    return diretorio


def test_identificador_do_prompt_e_estavel_e_distingue_prompts_diferentes() -> None:
    a = identificador_do_prompt("um prompt")
    b = identificador_do_prompt("um prompt")
    c = identificador_do_prompt("outro prompt")

    assert a == b
    assert a != c


async def test_gerar_casos_grava_o_regra_py_e_relata_sem_o_codigo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pasta_casos = tmp_path / "casos"
    _escrever_caso(pasta_casos, "caso-exemplo")
    saida = tmp_path / "saida"
    regras = carregar_representacoes(["caso-exemplo"], pasta_casos)
    _instalar_modelo(monkeypatch, [AIMessage(content=_BLOCO_VALIDO)])

    relatorio = await gerar_casos(regras, saida)

    assert (saida / "caso-exemplo.py").read_text(encoding="utf-8") == _FONTE_VALIDA
    assert relatorio == [
        {
            "caso": "caso-exemplo",
            "prompt_id": identificador_do_prompt(montar_prompt_geracao(regras["caso-exemplo"])),
            "finish_reason": "STOP",
            "ok": True,
        }
    ]


async def test_gerar_casos_relata_resposta_sem_bloco_de_codigo_sem_gravar_arquivo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pasta_casos = tmp_path / "casos"
    _escrever_caso(pasta_casos, "caso-exemplo")
    saida = tmp_path / "saida"
    regras = carregar_representacoes(["caso-exemplo"], pasta_casos)
    _instalar_modelo(monkeypatch, [AIMessage(content="sem bloco de código nenhum")])

    relatorio = await gerar_casos(regras, saida)

    assert relatorio[0]["ok"] is False
    assert "python block" in relatorio[0]["motivo"]
    assert not (saida / "caso-exemplo.py").exists()


async def test_gerar_casos_relata_resposta_truncada_sem_gravar_arquivo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pasta_casos = tmp_path / "casos"
    _escrever_caso(pasta_casos, "caso-exemplo")
    saida = tmp_path / "saida"
    regras = carregar_representacoes(["caso-exemplo"], pasta_casos)
    resposta = AIMessage(content=_BLOCO_VALIDO)
    resposta.response_metadata = {"finish_reason": "MAX_TOKENS"}
    model = FakeChatModel(messages=iter([resposta]))
    monkeypatch.setattr("scripts.gerar_casos_geracao.get_model", lambda nome: model)

    relatorio = await gerar_casos(regras, saida)

    assert relatorio[0] == {
        "caso": "caso-exemplo",
        "prompt_id": identificador_do_prompt(montar_prompt_geracao(regras["caso-exemplo"])),
        "finish_reason": "MAX_TOKENS",
        "ok": False,
        "motivo": "resposta do modelo vazia, bloqueada ou truncada",
    }
    assert not (saida / "caso-exemplo.py").exists()


async def test_gerar_casos_apaga_o_arquivo_da_rodada_anterior_quando_a_geracao_falha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O avaliador roda `<saida>/<id>.py`: um arquivo velho faria a rodada passar por outro."""
    pasta_casos = tmp_path / "casos"
    _escrever_caso(pasta_casos, "caso-exemplo")
    saida = tmp_path / "saida"
    saida.mkdir()
    (saida / "caso-exemplo.py").write_text("# código da rodada anterior\n", encoding="utf-8")
    regras = carregar_representacoes(["caso-exemplo"], pasta_casos)
    _instalar_modelo(monkeypatch, [AIMessage(content="sem bloco")])

    relatorio = await gerar_casos(regras, saida)

    assert relatorio[0]["ok"] is False
    assert not (saida / "caso-exemplo.py").exists()


async def test_gerar_casos_continua_apos_uma_falha_e_grava_os_que_deram_certo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pasta_casos = tmp_path / "casos"
    _escrever_caso(pasta_casos, "caso-a")
    _escrever_caso(pasta_casos, "caso-b")
    saida = tmp_path / "saida"
    regras = carregar_representacoes(["caso-a", "caso-b"], pasta_casos)
    _instalar_modelo(
        monkeypatch,
        [AIMessage(content="sem bloco"), AIMessage(content=_BLOCO_VALIDO)],
    )

    relatorio = await gerar_casos(regras, saida)

    assert [r["ok"] for r in relatorio] == [False, True]
    assert not (saida / "caso-a.py").exists()
    assert (saida / "caso-b.py").is_file()


def test_carregar_representacoes_recusa_representacao_que_nao_valida(tmp_path: Path) -> None:
    pasta_casos = tmp_path / "casos"
    _escrever_caso(pasta_casos, "caso-x", representacao={"nucleo": {"percentual": "dois"}})

    with pytest.raises(CasoInvalidoError, match="caso-x"):
        carregar_representacoes(["caso-x"], pasta_casos)


def test_carregar_representacoes_recusa_caso_sem_representacao(tmp_path: Path) -> None:
    pasta_casos = tmp_path / "casos"
    diretorio = pasta_casos / "caso-y"
    diretorio.mkdir(parents=True)
    (diretorio / "caso.json").write_text(json.dumps({"id": "caso-y"}), encoding="utf-8")

    with pytest.raises(CasoInvalidoError, match="representacao"):
        carregar_representacoes(["caso-y"], pasta_casos)


def test_main_falha_com_mensagem_clara_sem_a_chave_e_sem_chamar_o_modelo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pasta_casos = tmp_path / "casos"
    _escrever_caso(pasta_casos, "caso-exemplo")

    def _sem_chave(nome: str) -> Any:
        raise ValueError("GOOGLE_API_KEY is not configured")

    monkeypatch.setattr("scripts.gerar_casos_geracao.get_model", _sem_chave)

    codigo = main(["--saida", str(tmp_path / "saida"), "--casos", str(pasta_casos)])

    assert codigo == 2
    assert "GOOGLE_API_KEY" in capsys.readouterr().err
    assert not (tmp_path / "saida").exists()


def test_main_falha_de_uso_quando_o_caso_pedido_nao_existe(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pasta_casos = tmp_path / "casos"
    pasta_casos.mkdir()

    codigo = main(
        ["--saida", str(tmp_path / "saida"), "--casos", str(pasta_casos), "--caso", "inexistente"]
    )

    assert codigo == 2
    assert "inexistente" in capsys.readouterr().err


def test_main_falha_de_uso_quando_o_caso_esta_fora_do_formato(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Caso malformado é erro de uso (2), não geração falha (1), e não chega ao modelo."""
    pasta_casos = tmp_path / "casos"
    _escrever_caso(pasta_casos, "caso-x", representacao={"nucleo": {"percentual": "dois"}})
    model = _instalar_modelo(monkeypatch, [AIMessage(content=_BLOCO_VALIDO)])

    codigo = main(["--saida", str(tmp_path / "saida"), "--casos", str(pasta_casos)])

    assert codigo == 2
    assert "caso-x" in capsys.readouterr().err
    assert model.seen_messages == []


def test_main_imprime_uma_linha_json_por_caso_e_o_codigo_de_saida_reflete_a_falha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pasta_casos = tmp_path / "casos"
    _escrever_caso(pasta_casos, "caso-exemplo")
    _instalar_modelo(monkeypatch, [AIMessage(content="sem bloco")])

    codigo = main(["--saida", str(tmp_path / "saida"), "--casos", str(pasta_casos)])

    saida = capsys.readouterr().out.strip()
    registro = json.loads(saida)
    assert registro["caso"] == "caso-exemplo"
    assert registro["ok"] is False
    assert codigo == 1


def test_casos_padrao_aponta_para_as_fixtures_da_t243() -> None:
    assert CASOS_PADRAO.name == "casos_geracao"
    assert CASOS_PADRAO.is_dir()
    assert {p.name for p in CASOS_PADRAO.iterdir() if p.is_dir()} >= {
        "nucleo-controle",
        "generico-admissao",
        "generico-aniversario-loja",
    }
