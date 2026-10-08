"""Avalia código gerado pela IA contra os casos de geração (T-243).

Uso na pasta worker:
    poetry run python -m scripts.avaliar_geracao --codigo PASTA [--caso ID ...] [--imagem TAG]
        [--json]

Para cada caso, roda ``PASTA/<id>.py`` no sandbox, com o período do caso, e compara o total
simulado e a quebra por elemento com o esperado gravado, com a tolerância do harness: um
centavo por linha do período. O relatório dá um desfecho por caso: ``bate``, ``diverge``,
``falhou_como_esperado`` ou ``falhou_sem_esperar``. Sai com 0 quando todos passam, 1 quando
algum não passa e 2 em erro de uso ou de infraestrutura, sem avaliar nada.

É ferramenta de desenvolvimento: não publica evento, não grava em banco e não tem métrica. O
relatório só tem classe, motivo, totais e referências de elemento; o stdout, o stderr e a
mensagem de erro do código gerado nunca aparecem, porque são dado não confiável.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from app.execucao.container import SandboxInfraError
from scripts.casos_geracao import (
    Avaliacao,
    Caso,
    CasoInvalidoError,
    carregar_casos,
    comparar,
    executar_caso,
    ler_esperado,
    tolerancia_do_periodo,
)

ROTULOS = {
    "bate": "bate",
    "diverge": "diverge",
    "falhou_como_esperado": "falhou como esperado",
    "falhou_sem_esperar": "falhou sem esperar",
}


def avaliar(caso: Caso, fonte: str, *, imagem: str | None = None) -> Avaliacao:
    """Lê o esperado antes de executar: um caso sem esperado gravado não chega ao sandbox."""
    esperado = ler_esperado(caso)
    obtido = executar_caso(caso, fonte, imagem=imagem)
    return comparar(caso.id, esperado, obtido, tolerancia_do_periodo(caso.competencias))


def codigo_de_saida(avaliacoes: Sequence[Avaliacao]) -> int:
    return 0 if all(avaliacao.passou for avaliacao in avaliacoes) else 1


def relatorio_texto(avaliacoes: Sequence[Avaliacao]) -> str:
    linhas: list[str] = []
    for avaliacao in avaliacoes:
        esperado, obtido = avaliacao.esperado, avaliacao.obtido
        cabecalho = f"{avaliacao.caso}: {ROTULOS[avaliacao.desfecho]}"
        if obtido.classe != "sucesso":
            cabecalho += f" ({obtido.classe}/{obtido.motivo})"
        elif esperado.classe != "sucesso":
            cabecalho += " (o caso espera a falha da regra, e o código devolveu um número)"
        linhas.append(cabecalho)
        if obtido.totais is not None:
            simulado = f"obtido {obtido.totais['simulado']:.2f}"
            if esperado.totais is not None:
                simulado = (
                    f"esperado {esperado.totais['simulado']:.2f}, {simulado} "
                    f"(tolerância {avaliacao.tolerancia:.2f})"
                )
            linhas.append(f"  total simulado: {simulado}")
        linhas.extend(
            f"  {diferenca.elemento}: esperado {diferenca.esperado:.2f}, "
            f"obtido {diferenca.obtido:.2f}"
            for diferenca in avaliacao.diferencas
        )
    aprovados = sum(avaliacao.passou for avaliacao in avaliacoes)
    linhas.append(f"{aprovados} de {len(avaliacoes)} casos passaram")
    return "\n".join(linhas)


def relatorio_json(avaliacoes: Sequence[Avaliacao]) -> str:
    return json.dumps(
        [
            {
                "caso": avaliacao.caso,
                "desfecho": avaliacao.desfecho,
                "passou": avaliacao.passou,
                "classe": avaliacao.obtido.classe,
                "motivo": avaliacao.obtido.motivo,
                "simulado_esperado": (
                    avaliacao.esperado.totais["simulado"] if avaliacao.esperado.totais else None
                ),
                "simulado_obtido": (
                    avaliacao.obtido.totais["simulado"] if avaliacao.obtido.totais else None
                ),
                "tolerancia": float(avaliacao.tolerancia),
                "diferencas": [
                    {"elemento": d.elemento, "esperado": d.esperado, "obtido": d.obtido}
                    for d in avaliacao.diferencas
                ],
            }
            for avaliacao in avaliacoes
        ],
        ensure_ascii=False,
        indent=2,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codigo", type=Path, required=True, help="pasta com um <id>.py por caso")
    parser.add_argument("--caso", action="append", help="id do caso; repita para vários")
    parser.add_argument("--imagem", help="imagem do sandbox (padrão: SANDBOX_IMAGE)")
    parser.add_argument("--json", action="store_true", help="relatório em JSON no stdout")
    args = parser.parse_args(argv)

    try:
        casos = carregar_casos(args.caso)
    except CasoInvalidoError as erro:
        print(f"erro: {erro}", file=sys.stderr)
        return 2
    ausentes = [f"{caso.id}.py" for caso in casos if not (args.codigo / f"{caso.id}.py").is_file()]
    if ausentes:
        print(f"erro: faltam em {args.codigo}: {', '.join(ausentes)}", file=sys.stderr)
        return 2

    avaliacoes: list[Avaliacao] = []
    for caso in casos:
        fonte = (args.codigo / f"{caso.id}.py").read_text(encoding="utf-8")
        try:
            avaliacoes.append(avaliar(caso, fonte, imagem=args.imagem))
        except CasoInvalidoError as erro:
            print(f"erro: {erro}", file=sys.stderr)
            return 2
        except SandboxInfraError as erro:
            print(f"erro de infraestrutura: {erro}", file=sys.stderr)
            return 2

    print(relatorio_json(avaliacoes) if args.json else relatorio_texto(avaliacoes))
    return codigo_de_saida(avaliacoes)


if __name__ == "__main__":
    sys.exit(main())
