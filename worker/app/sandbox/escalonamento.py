"""Vendas escaladas até a meta de venda e o baseline reapurado sobre elas (T-270).

Com ``meta_venda`` no comando, a regra é simulada como se as vendas do período tivessem
atingido a meta: toda venda das competências do job é multiplicada pelo mesmo fator,
``meta_venda / total histórico``, e o baseline é reapurado sobre as vendas escaladas com a
mesma função e as mesmas entradas que geraram o baseline congelado
(``scripts/build_baselines.py``). A apuração não é linear nas vendas (piso de afastamento e
arredondamento por linha), por isso a escala vale para a entrada e nunca para os totais.

Só stdlib, e por isso roda nos dois lados: na imagem do sandbox, onde ``carga.py`` prepara a
entrada da regra, e no processo do worker, que reapura o mesmo baseline por conta própria para
conferir o que volta do container (``app/execucao/bases.py``). Os dois lados chamam estas
funções sobre os mesmos dados, e o resultado é o mesmo número.

Não edita nada do motor: ``regras_competencia.py`` e o que ele importa estão no manifesto dos
baselines, e qualquer alteração neles invalida ``build_baselines --check``.
"""

import math
from collections.abc import Iterable, Mapping, Sequence
from decimal import ROUND_HALF_UP, Decimal

from app.sandbox.assercoes import TabelaApurada
from app.sandbox.regras_base import RegraBaseError
from app.sandbox.regras_competencia import apurar_vigente

CENTAVO = Decimal("0.01")


class MetaVendaError(ValueError):
    """A meta não se aplica às vendas do período: não há venda a escalar, ou a escala sai do
    intervalo de um número finito."""


def total_de_vendas(vendas: Iterable[Mapping[str, object]]) -> Decimal:
    """A soma de ``vlr_venda``, em centavos.

    É o total histórico do período (``totais.vendas_historicas``) e o divisor do fator: uma meta
    igual a ele escala por exatamente 1, e a reapuração reproduz o baseline congelado.
    """
    total = sum((Decimal(str(venda["vlr_venda"])) for venda in vendas), Decimal(0))
    return total.quantize(CENTAVO, rounding=ROUND_HALF_UP)


def fator_de_escala(meta_venda: float, total_historico: Decimal) -> Decimal:
    """``meta_venda / total histórico``, a partir da representação de cada número."""
    if total_historico <= 0:
        raise MetaVendaError("o período não tem vendas a escalar até a meta")
    return Decimal(str(meta_venda)) / total_historico


def escalar_vendas(
    vendas: Sequence[Mapping[str, object]], fator: Decimal
) -> list[dict[str, object]]:
    """Cópias das vendas com ``vlr_venda`` multiplicado pelo fator. As demais colunas não mudam.

    O valor escalado não é arredondado a centavos: arredondar mudaria a proporção entre as
    vendas, que é o que a escala promete preservar.
    """
    escaladas: list[dict[str, object]] = []
    for venda in vendas:
        valor = float(Decimal(str(venda["vlr_venda"])) * fator)
        if not math.isfinite(valor):
            raise MetaVendaError("a venda escalada até a meta não é um número finito")
        escaladas.append({**venda, "vlr_venda": valor})
    return escaladas


def reapurar_baseline(
    rh: Sequence[Mapping[str, object]],
    vendas: Sequence[Mapping[str, object]],
    comissoes: Sequence[Mapping[str, object]],
    eventos_rh: Sequence[Mapping[str, object]],
    regras: Sequence[Mapping[str, object]],
    competencias: Sequence[str],
) -> list[dict[str, object]]:
    """O baseline das competências na forma de ``apuracao_base``, competência a competência.

    É a apuração de ``build_baselines.gerar_artefatos``: ``apurar_vigente`` com o catálogo de
    regras da competência, e cada linha publicada como ``build_baselines._linhas_apuracao_base``
    a publica, com ``cod_marca`` do RH da competência e ``cod_cargo`` de ``cargo``. Sobre as
    vendas históricas, reproduz os baselines congelados linha a linha.

    ``eventos_rh`` vai inteira, como no congelamento: um evento de competência anterior ainda
    afeta o mês. As demais bases são recortadas por competência antes da apuração, que só lê as
    linhas da competência apurada.
    """
    linhas: list[dict[str, object]] = []
    for competencia in competencias:
        rh_do_mes = [registro for registro in rh if registro.get("competencia") == competencia]
        tabela = apurar_vigente(
            rh_do_mes,
            [venda for venda in vendas if venda.get("competencia") == competencia],
            [taxa for taxa in comissoes if taxa.get("competencia") == competencia],
            eventos_rh,
            competencia,
            regras=regras,
        )
        if not isinstance(tabela, TabelaApurada):
            raise TypeError("a reapuração exige a tabela validada pela T-031")
        marcas_do_rh = {str(pessoa["matricula"]): pessoa.get("cod_marca") for pessoa in rh_do_mes}
        for linha in tabela:
            matricula = str(linha["matricula"])
            cod_marca = _cod_marca_vigente(linha, matricula, competencia)
            if cod_marca != marcas_do_rh.get(matricula):
                raise RegraBaseError(
                    f"{competencia}/{matricula}: cod_marca da rastreabilidade difere do rh"
                )
            linhas.append(
                {
                    "matricula": matricula,
                    "cod_loja": linha["cod_loja"],
                    "cod_marca": cod_marca,
                    "cod_cargo": linha["cargo"],
                    "competencia": competencia,
                    "comissao": linha["comissao"],
                }
            )
    return linhas


def _cod_marca_vigente(linha: Mapping[str, object], matricula: str, competencia: str) -> int:
    """A marca que a apuração atribuiu à matrícula, pela mesma trilha que
    ``build_baselines._linhas_apuracao_base`` usa para congelar o baseline:
    ``rastreabilidade.chaves_comissao`` tem de ter exatamente uma marca, porque
    ``apuracao_base`` só tem uma coluna ``cod_marca``. Uma matrícula com vendas em mais de uma
    marca no mês não tem "a" marca, e isso nunca ocorreu nas competências já congeladas (o
    congelamento já recusaria); aqui é a mesma verificação, para a meta não silenciar a
    ambiguidade escalando a venda que a causaria.
    """
    rastreabilidade = linha.get("rastreabilidade")
    chaves = (
        rastreabilidade.get("chaves_comissao") if isinstance(rastreabilidade, Mapping) else None
    )
    if not isinstance(chaves, list) or not chaves:
        raise RegraBaseError(
            f"{competencia}/{matricula}: rastreabilidade.chaves_comissao ausente ou vazia"
        )
    marcas = {chave.get("cod_marca") for chave in chaves if isinstance(chave, Mapping)}
    if len(marcas) != 1:
        raise RegraBaseError(
            f"{competencia}/{matricula}: esperada exatamente uma cod_marca na rastreabilidade; "
            f"encontradas {len(marcas)}"
        )
    (marca,) = marcas
    if not isinstance(marca, int) or isinstance(marca, bool):
        raise RegraBaseError(
            f"{competencia}/{matricula}: cod_marca da rastreabilidade não é inteiro"
        )
    return marca
