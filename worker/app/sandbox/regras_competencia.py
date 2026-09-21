"""Políticas históricas da T-032, calculadas sem LLM e sem leitura de arquivos."""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import cast

from app.sandbox.ajustes_competencia import AjusteCompetencia
from app.sandbox.assercoes import numero_finito
from app.sandbox.regras_base import (
    CARGO_GERENTE,
    DataFrameLike,
    Registro,
    RegraBaseError,
    TabelaSaida,
    _eventos_por_matricula,
    _extrair_linhas,
    _filtrar_vendas,
    _inteiro,
    _limites_competencia,
    _preparar_rh,
    _texto,
    apurar,
)

TIPOS_PERCENTUAL = frozenset({"substituir_percentual", "copiar_percentual", "adicional_percentual"})
TIPOS = TIPOS_PERCENTUAL | {
    "bonus_final",
    "bonus_base",
    "adicional_periodo",
    "bonus_faixa_individual",
    "bonus_faixa_loja",
}


def _seleciona(regra: Registro, marca: int, cargo: int) -> bool:
    return (
        ("marcas" not in regra or marca in cast(list[int], regra["marcas"]))
        and ("cargos" not in regra or cargo in cast(list[int], regra["cargos"]))
        and cargo not in cast(list[int], regra.get("cargos_excluidos", []))
    )


def _valor(regra: Registro) -> Decimal:
    valor = numero_finito(regra.get("valor"))
    if valor < 0:
        raise RegraBaseError(f"regra {regra.get('id')}: valor negativo")
    return valor


def _bonus_faixa(regra: Registro, base: Decimal) -> Decimal:
    faixas = regra.get("faixas")
    if not isinstance(faixas, list):
        raise RegraBaseError(f"regra {regra.get('id')}: faixas ausentes")
    for faixa in faixas:
        if not isinstance(faixa, Mapping):
            raise RegraBaseError("faixa deve ser objeto")
        teto = faixa.get("maximo_inclusivo")
        if base > numero_finito(faixa.get("minimo_exclusivo")) and (
            teto is None or base <= numero_finito(teto)
        ):
            return _valor(faixa)
    return Decimal(0)


def apurar_vigente(
    rh: Sequence[Registro] | DataFrameLike,
    vendas: Sequence[Registro] | DataFrameLike,
    comissionamento: Sequence[Registro] | DataFrameLike,
    eventos_rh: Sequence[Registro] | DataFrameLike,
    competencia: str,
    *,
    regras: Sequence[Registro],
) -> TabelaSaida:
    """Aplica base + regras mensais, arredondando uma única vez por matrícula.

    O catálogo versionado é recebido como dado. Taxas e bases extras entram antes
    das proporções/piso; bônus finais depois. Não altera nenhuma tabela de entrada.
    A finalização automática da T-031 vê o resultado completo já com os ajustes.
    """
    politicas = sorted(
        [r for r in regras if r.get("competencia") == competencia], key=lambda r: str(r.get("id"))
    )
    if not politicas:
        raise RegraBaseError(f"competência sem política histórica publicada: {competencia}")
    identificadores: set[str] = set()
    for politica in politicas:
        identificador = _texto(politica, "id", "regras")
        if identificador in identificadores or politica.get("tipo") not in TIPOS:
            raise RegraBaseError(f"regra duplicada ou tipo não suportado: {identificador}")
        identificadores.add(identificador)

    inicio, fim = _limites_competencia(competencia)
    linhas_rh = _extrair_linhas(rh, "rh")
    linhas_vendas = _extrair_linhas(vendas, "vendas")
    eventos = _extrair_linhas(eventos_rh, "eventos_rh")
    pessoas = _preparar_rh(linhas_rh, _eventos_por_matricula(eventos), competencia, inicio, fim)
    validas, _ = _filtrar_vendas(linhas_vendas, pessoas, competencia, inicio, fim)
    vendas_pessoa: dict[str, list[Registro]] = defaultdict(list)
    vendas_loja: dict[int, list[Registro]] = defaultdict(list)
    for _, venda in validas:
        vendas_pessoa[_texto(venda, "matricula", "vendas")].append(venda)
        vendas_loja[_inteiro(venda, "cod_loja", "vendas")].append(venda)

    taxas = [linha.dados.copy() for linha in _extrair_linhas(comissionamento, "comissionamento")]
    taxas_originais = {
        (
            _inteiro(t, "cod_marca", "comissoes"),
            _inteiro(t, "cod_cargo", "comissoes"),
        ): numero_finito(t["percentual_comissao"])
        for t in taxas
        if t.get("competencia") == competencia
    }
    for politica in politicas:
        tipo = politica["tipo"]
        if tipo not in TIPOS_PERCENTUAL:
            continue
        for taxa in taxas:
            marca = _inteiro(taxa, "cod_marca", "comissoes")
            cargo = _inteiro(taxa, "cod_cargo", "comissoes")
            if taxa.get("competencia") != competencia or not _seleciona(politica, marca, cargo):
                continue
            if tipo == "copiar_percentual":
                chave = (_inteiro(politica, "marca_origem", "regras"), cargo)
                if chave not in taxas_originais:
                    raise RegraBaseError(f"percentual de origem ausente: {chave}")
                novo = taxas_originais[chave]
            elif tipo == "substituir_percentual":
                novo = _valor(politica)
            else:
                novo = numero_finito(taxa["percentual_comissao"]) + _valor(politica)
            taxa["percentual_comissao"] = novo

    ajustes: dict[str, AjusteCompetencia] = {}
    for matricula, pessoa in sorted(pessoas.items()):
        if not pessoa.elegivel:
            continue
        cargo = _inteiro(pessoa.dados, "cod_cargo", "rh")
        marca = _inteiro(pessoa.dados, "cod_marca", "rh")
        loja = _inteiro(pessoa.dados, "cod_loja", "rh")
        proprias = vendas_pessoa[matricula]
        base_vendas = vendas_loja[loja] if cargo == CARGO_GERENTE else proprias
        base_extra = Decimal(0)
        comissao_extra = Decimal(0)
        bonus_final = Decimal(0)
        origens: list[Registro] = []
        for politica in politicas:
            tipo = str(politica["tipo"])
            valor = Decimal(0)
            tipo_origem = "percentual"
            if tipo in TIPOS_PERCENTUAL:
                marcas = (
                    {marca}
                    if cargo == CARGO_GERENTE
                    else {_inteiro(v, "cod_marca", "vendas") for v in proprias} | {marca}
                )
                if not any(_seleciona(politica, m, cargo) for m in marcas):
                    continue
                valor = Decimal(0) if tipo == "copiar_percentual" else _valor(politica)
            elif tipo in {"bonus_base", "bonus_final"}:
                if not _seleciona(politica, marca, cargo):
                    continue
                alvos = politica.get("matriculas")
                if isinstance(alvos, list) and matricula not in alvos:
                    continue
                limite = politica.get("admissao_ate")
                if isinstance(limite, str) and pessoa.data_admiss.isoformat() > limite:
                    continue
                valor = _valor(politica)
                tipo_origem = tipo
                if tipo == "bonus_base":
                    base_extra += valor
                else:
                    bonus_final += valor
            elif tipo == "adicional_periodo":
                primeiro = _texto(politica, "inicio", "regras")
                ultimo = _texto(politica, "fim", "regras")
                # data_ref mensal não é data real de venda (T-026/T-027).
                base = sum(
                    (
                        numero_finito(v["vlr_venda"])
                        for v in base_vendas
                        if _seleciona(politica, _inteiro(v, "cod_marca", "vendas"), cargo)
                        and isinstance(v.get("data_venda"), str)
                        and primeiro <= str(v["data_venda"]) <= ultimo
                    ),
                    Decimal(0),
                )
                if not base:
                    continue
                valor = base * _valor(politica)
                comissao_extra += valor
            else:
                # Faixa individual usa a venda própria, inclusive para gerentes;
                # faixa de loja usa todas as vendas da loja, sem base fictícia.
                if tipo == "bonus_faixa_loja" and not _seleciona(politica, marca, cargo):
                    continue
                origem_vendas = vendas_loja[loja] if tipo == "bonus_faixa_loja" else proprias
                base = sum(
                    (
                        numero_finito(v["vlr_venda"])
                        for v in origem_vendas
                        if _seleciona(politica, _inteiro(v, "cod_marca", "vendas"), cargo)
                    ),
                    Decimal(0),
                )
                valor = _bonus_faixa(politica, base)
                if not valor:
                    continue
                bonus_final += valor
                tipo_origem = "bonus_final"
            origens.append(
                {
                    "id": politica["id"],
                    "competencia": competencia,
                    "matricula": matricula,
                    "tipo": tipo_origem,
                    "valor": str(valor),
                    "fonte": politica.get("fonte"),
                }
            )
        ajustes[matricula] = AjusteCompetencia(
            base_extra, comissao_extra, bonus_final, tuple(origens)
        )

    return apurar(rh, vendas, taxas, eventos_rh, competencia, ajustes_competencia=ajustes)
