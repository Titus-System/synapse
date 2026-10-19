"""O banco de um job que itera a taxa nova, gravado como a api e o worker o gravariam (T-271).

Os nós leem daqui o que leriam do Postgres: a versão de cada ciclo, a conta das tentativas, os
totais e as taxas já simuladas. O teste faz o papel da api, que grava a versão de cada proposta
e reabre o ciclo, e o do worker, que grava o resultado e o publica. As consultas reais estão em
`tests/app/repositorio/test_tentativas_postgres.py`.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from app.repositorio.regras import TentativasDeTaxa
from app.repositorio.resultados import TotaisDaSimulacao
from app.representacao_regra import RepresentacaoRegra
from app.sugestao_adaptacao import TaxaSimulada

NUCLEO = {
    "vigencia": {"inicio": "2025-09", "fim": "2025-11"},
    "loja": ["13"],
    "marca": ["10"],
    "cargo": ["100"],
    "percentual": Decimal("0.03"),
}


@dataclass
class Versao:
    versao: int
    origem: str
    regra_origem_id: UUID | None
    representacao: dict[str, Any]

    @property
    def percentual(self) -> Decimal:
        percentual: Decimal = self.representacao["nucleo"]["percentual"]
        return percentual


@dataclass
class HistoricoFalso:
    job_id: UUID
    orcamento: Decimal
    baseline: Decimal
    versoes: dict[UUID, Versao] = field(default_factory=dict)
    # resultado_id -> (versão simulada, comissão apurada)
    resultados: dict[UUID, tuple[UUID, Decimal]] = field(default_factory=dict)

    def instalar(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("app.graph.nodes.load_rule.buscar_regra", self.buscar_regra)
        monkeypatch.setattr(
            "app.graph.nodes.validate_domain.parametros_sem_lastro",
            AsyncMock(return_value=frozenset()),
        )
        monkeypatch.setattr(
            "app.mensageria.roteamento.buscar_regra_do_resultado", self.buscar_regra_do_resultado
        )
        monkeypatch.setattr("app.graph.nodes.decision.contar_tentativas", self.contar_tentativas)
        monkeypatch.setattr("app.graph.nodes.suggest_adaptation.buscar_totais", self.buscar_totais)
        monkeypatch.setattr(
            "app.graph.nodes.suggest_adaptation.buscar_taxas_simuladas",
            self.buscar_taxas_simuladas,
        )

    def gravar_versao(
        self, representacao: dict[str, Any], origem: str, regra_origem_id: UUID | None = None
    ) -> UUID:
        """O que a api faz com a regra extraída e com cada proposta."""
        regra_id = uuid4()
        self.versoes[regra_id] = Versao(
            len(self.versoes) + 1, origem, regra_origem_id, representacao
        )
        return regra_id

    def gravar_proposta(self, proposta: dict[str, Any]) -> UUID:
        representacao = RepresentacaoRegra.model_validate(proposta["representacao"])
        return self.gravar_versao(
            representacao.para_contrato(), "sugestao_adaptacao", UUID(proposta["regra_origem_id"])
        )

    def gravar_resultado(self, regra_id: UUID, simulado: Decimal) -> UUID:
        """O que o worker grava em `resultados_simulacao` antes de publicar o resultado."""
        resultado_id = uuid4()
        self.resultados[resultado_id] = (regra_id, simulado)
        return resultado_id

    async def buscar_regra(self, sessoes: Any, job_id: UUID, regra_id: UUID) -> RepresentacaoRegra:
        assert job_id == self.job_id
        return RepresentacaoRegra.model_validate(self.versoes[regra_id].representacao)

    async def buscar_regra_do_resultado(
        self, sessoes: Any, job_id: UUID, resultado_id: UUID
    ) -> UUID:
        assert job_id == self.job_id
        return self.resultados[resultado_id][0]

    async def contar_tentativas(
        self, sessoes: Any, job_id: UUID, regra_id: UUID
    ) -> TentativasDeTaxa:
        simulada = self.versoes[regra_id]
        feitas = sum(
            1
            for versao in self.versoes.values()
            if versao.origem == "sugestao_adaptacao" and versao.versao <= simulada.versao
        )
        return TentativasDeTaxa(feitas, simulada.origem == "sugestao_adaptacao")

    async def buscar_totais(
        self, sessoes: Any, job_id: UUID, resultado_id: UUID
    ) -> TotaisDaSimulacao:
        _, simulado = self.resultados[resultado_id]
        return TotaisDaSimulacao(simulado, self.orcamento, baseline=self.baseline)

    async def buscar_taxas_simuladas(
        self, sessoes: Any, job_id: UUID, regra_id: UUID
    ) -> list[TaxaSimulada]:
        cadeia = [regra_id]
        while self.versoes[cadeia[-1]].origem == "sugestao_adaptacao":
            origem = self.versoes[cadeia[-1]].regra_origem_id
            assert origem is not None
            cadeia.append(origem)
        return [
            TaxaSimulada(self.versoes[regra].percentual, simulado)
            for regra in cadeia
            for simulada, simulado in self.resultados.values()
            if simulada == regra
        ]
