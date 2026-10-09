"""Gera o `regra.py` dos casos de geração (T-243) com o modelo real (T-244).

Uso na pasta codegen:
    poetry run python -m scripts.gerar_casos_geracao --saida PASTA [--casos PASTA] [--caso ID ...]

Para cada caso de PASTA_DOS_CASOS/<id>/caso.json (o formato da T-243, em
worker/tests/fixtures/casos_geracao por padrão), monta o mesmo prompt que o nó
`code_generation` monta (`montar_prompt_geracao`), chama o mesmo modelo registrado para
`code_generation` (`app.graph.core.llm.registry`) e extrai o `regra.py` como o nó
`extract_code` extrai (`app.codigo_gerado.extrair_codigo`), gravando `SAIDA/<id>.py` para o
avaliador do worker (`scripts.avaliar_geracao`, em worker/) rodar.

Não executa o código gerado - só monta o prompt, chama o modelo e extrai o texto; a execução é
do avaliador do worker. Falha com mensagem clara, sem chamar o modelo, quando o provedor não
está configurado. Imprime em stdout, por caso, uma linha JSON com o identificador do prompt e o
desfecho da chamada - nunca o prompt, o código ou a resposta do modelo. Os arquivos gravados em
SAIDA não são versionados.

Sai com 0 quando todos os casos pedidos produziram um `regra.py`, 1 quando algum não produziu
(resposta vazia/bloqueada/truncada, ou sem um bloco de código válido) e 2 em erro de uso -
pasta de casos ausente, caso inexistente ou fora do formato, provedor não configurado -, sem
chamar o modelo. O caso que não produz código tem o `<id>.py` de uma rodada anterior apagado da
pasta de saída: o avaliador nunca deve pontuar um arquivo que esta rodada não gerou.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import simplejson
from langchain_core.messages import HumanMessage
from pydantic import ValidationError

from app.codigo_gerado import CodigoInvalidoError, extrair_codigo
from app.graph.core.llm.registry import get_model
from app.prompts.geracao_codigo import montar_prompt_geracao
from app.representacao_regra import RepresentacaoRegra
from app.resposta_modelo import extrair_resposta

CASOS_PADRAO = (
    Path(__file__).resolve().parents[2] / "worker" / "tests" / "fixtures" / "casos_geracao"
)
ARQUIVO_CASO = "caso.json"

# O único motivo de parada que conta como sucesso - o mesmo que `code_generation` exige.
_FINISH_REASON_ACEITO = "STOP"


class CasoInvalidoError(Exception):
    """Um caso fora do formato: `caso.json` ausente, sem representação ou que não valida."""


def identificador_do_prompt(prompt: str) -> str:
    """Hash estável do prompt, para rastrear qual texto gerou qual arquivo sem gravá-lo."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]


def carregar_representacoes(ids: Sequence[str], pasta_casos: Path) -> dict[str, RepresentacaoRegra]:
    """Valida todos os casos pedidos de uma vez, antes de qualquer chamada ao modelo.

    Levanta `CasoInvalidoError` no primeiro caso fora do formato, para a rodada não gastar
    chamada nenhuma quando um dos casos não serve.
    """
    regras: dict[str, RepresentacaoRegra] = {}
    for caso_id in ids:
        arquivo = pasta_casos / caso_id / ARQUIVO_CASO
        if not arquivo.is_file():
            raise CasoInvalidoError(f"{caso_id}: {ARQUIVO_CASO} não encontrado em {pasta_casos}")
        # use_decimal=True: ValorRegra exige Decimal para número, e um float do json padrão
        # falha a validação estrita (percentual, por exemplo, chega como 0.025 em caso.json).
        dados = simplejson.loads(arquivo.read_text(encoding="utf-8"), use_decimal=True)
        if not isinstance(dados, dict) or "representacao" not in dados:
            raise CasoInvalidoError(f"{caso_id}: {ARQUIVO_CASO} não tem representacao")
        try:
            regras[caso_id] = RepresentacaoRegra.model_validate(dados["representacao"])
        except ValidationError:
            raise CasoInvalidoError(
                f"{caso_id}: a representação não valida em representacao-regra.schema.json"
            ) from None
    return regras


def _casos_pedidos(pasta_casos: Path, ids: Sequence[str] | None) -> list[str]:
    if ids:
        return list(ids)
    return sorted(p.name for p in pasta_casos.iterdir() if p.is_dir())


async def gerar_regra(caso_id: str, regra: RepresentacaoRegra) -> dict[str, Any]:
    """Monta o prompt da regra, chama o modelo registrado e extrai o `regra.py`.

    O registro de retorno nunca carrega o prompt, o código ou a resposta do modelo - só o
    identificador do prompt, o motivo de parada e o desfecho. Um erro do provedor se propaga
    como está (mesma semântica do nó `code_generation`); só a resposta vazia/bloqueada/truncada
    e a extração inválida são desfechos reportados por caso.
    """
    prompt = montar_prompt_geracao(regra)
    registro: dict[str, Any] = {"caso": caso_id, "prompt_id": identificador_do_prompt(prompt)}

    model = get_model("code_generation")
    resposta = await model.ainvoke([HumanMessage(content=prompt)])
    content, finish_reason = extrair_resposta(resposta)
    registro["finish_reason"] = finish_reason

    if not content or finish_reason != _FINISH_REASON_ACEITO:
        registro["ok"] = False
        registro["motivo"] = "resposta do modelo vazia, bloqueada ou truncada"
        return registro
    try:
        registro["fonte"] = extrair_codigo(content)
    except CodigoInvalidoError as erro:
        registro["ok"] = False
        registro["motivo"] = str(erro)
        return registro
    registro["ok"] = True
    return registro


async def gerar_casos(
    regras: Mapping[str, RepresentacaoRegra], saida: Path
) -> list[dict[str, Any]]:
    saida.mkdir(parents=True, exist_ok=True)
    relatorio = []
    for caso_id, regra in regras.items():
        registro = await gerar_regra(caso_id, regra)
        fonte = registro.pop("fonte", None)
        arquivo = saida / f"{caso_id}.py"
        if registro["ok"]:
            arquivo.write_text(fonte, encoding="utf-8")
        else:
            # Sem apagar, o avaliador pontuaria o arquivo de uma rodada anterior como se fosse
            # desta, e a prova da rodada passaria a valer para um código que ela não gerou.
            arquivo.unlink(missing_ok=True)
        relatorio.append(registro)
    return relatorio


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--saida", type=Path, required=True, help="pasta onde grava <id>.py")
    parser.add_argument(
        "--casos", type=Path, default=CASOS_PADRAO, help="pasta dos casos de geração (T-243)"
    )
    parser.add_argument("--caso", action="append", help="id do caso; repita para vários")
    args = parser.parse_args(argv)

    if not args.casos.is_dir():
        print(f"erro: pasta de casos não encontrada: {args.casos}", file=sys.stderr)
        return 2

    try:
        regras = carregar_representacoes(_casos_pedidos(args.casos, args.caso), args.casos)
    except CasoInvalidoError as erro:
        print(f"erro: {erro}", file=sys.stderr)
        return 2

    try:
        get_model("code_generation")  # falha cedo, sem chamar o modelo, se faltar a chave
    except ValueError as erro:
        print(f"erro: {erro}", file=sys.stderr)
        return 2

    relatorio = asyncio.run(gerar_casos(regras, args.saida))
    for registro in relatorio:
        print(json.dumps(registro, ensure_ascii=False))
    return 0 if all(registro["ok"] for registro in relatorio) else 1


if __name__ == "__main__":
    sys.exit(main())
