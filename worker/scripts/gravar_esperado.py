"""Roda a referência de cada caso de geração no sandbox e grava o resultado esperado (T-243).

Uso na pasta worker:
    poetry run python -m scripts.gravar_esperado [--caso ID ...] [--check] [--imagem TAG]

O esperado nunca é escrito à mão: é o que a referência produz no sandbox, só com agregados.
``--check`` roda as referências e compara com o que está gravado, sem escrever.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from app.execucao.container import SandboxInfraError
from scripts.casos_geracao import (
    FALHA_ESPERADA,
    Caso,
    CasoInvalidoError,
    Medicao,
    carregar_casos,
    executar_caso,
    serializar_esperado,
)


class ReferenciaInvalidaError(RuntimeError):
    """A referência não terminou em sucesso nem na falha que um caso pode esperar."""


def medir_referencia(caso: Caso, *, imagem: str | None = None) -> Medicao:
    medicao = executar_caso(caso, caso.referencia.read_text(encoding="utf-8"), imagem=imagem)
    if medicao.classe != "sucesso" and medicao != FALHA_ESPERADA:
        # A referência é código nosso: o tipo da exceção dela pode ser exibido.
        raise ReferenciaInvalidaError(
            f"{caso.id}: a referência terminou em {medicao.classe}/{medicao.motivo}"
            + (f" ({medicao.tipo_erro})" if medicao.tipo_erro else "")
            + "; corrija a referência antes de gravar"
        )
    return medicao


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--caso", action="append", help="id do caso; repita para vários")
    parser.add_argument("--check", action="store_true", help="compara sem escrever")
    parser.add_argument("--imagem", help="imagem do sandbox (padrão: SANDBOX_IMAGE)")
    args = parser.parse_args(argv)

    try:
        casos = carregar_casos(args.caso)
    except CasoInvalidoError as erro:
        print(f"erro: {erro}", file=sys.stderr)
        return 2

    divergentes = 0
    for caso in casos:
        try:
            conteudo = serializar_esperado(caso, medir_referencia(caso, imagem=args.imagem))
        except ReferenciaInvalidaError as erro:
            print(f"erro: {erro}", file=sys.stderr)
            return 1
        except SandboxInfraError as erro:
            print(f"erro de infraestrutura: {erro}", file=sys.stderr)
            return 2

        if args.check:
            gravado = caso.esperado.read_text(encoding="utf-8") if caso.esperado.is_file() else None
            if gravado == conteudo:
                print(f"{caso.id}: confere")
            else:
                divergentes += 1
                print(f"{caso.id}: {'ausente' if gravado is None else 'difere do gravado'}")
        else:
            caso.esperado.write_text(conteudo, encoding="utf-8", newline="\n")
            print(f"{caso.id}: gravado em {caso.esperado.relative_to(caso.diretorio.parent)}")

    return 1 if divergentes else 0


if __name__ == "__main__":
    sys.exit(main())
