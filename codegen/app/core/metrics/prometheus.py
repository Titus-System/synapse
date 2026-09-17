from collections.abc import Mapping
from typing import Literal

from prometheus_client import Counter, Gauge, Histogram, generate_latest


class Prometheus:
    """Abstração sobre prometheus_client para métricas de infraestrutura e domínio."""

    def __init__(self) -> None:
        self._counters: dict[str, Counter] = {}
        self._gauges: dict[str, Gauge] = {}
        self._histograms: dict[str, Histogram] = {}

    def register_counter(
        self, nome: str, descricao: str, rotulos: list[str] | None = None
    ) -> Counter:
        if nome not in self._counters:
            self._counters[nome] = Counter(nome, descricao, rotulos or [])
        return self._counters[nome]

    def register_gauge(self, nome: str, descricao: str, rotulos: list[str] | None = None) -> Gauge:
        if nome not in self._gauges:
            self._gauges[nome] = Gauge(nome, descricao, rotulos or [])
        return self._gauges[nome]

    def register_histogram(
        self, nome: str, descricao: str, rotulos: list[str] | None = None
    ) -> Histogram:
        if nome not in self._histograms:
            self._histograms[nome] = Histogram(nome, descricao, rotulos or [])
        return self._histograms[nome]

    def get_all(self) -> bytes:
        """Retorna todas as métricas no formato de texto do Prometheus."""
        dados: bytes = generate_latest()
        return dados

    def get_all_by_prefix(self, prefixo: str) -> bytes:
        """Retorna as métricas registradas cujo nome começa com ``prefixo``."""
        gauges = self.get_gauges_by_prefix(prefixo)
        histograms = self.get_histograms_by_prefix(prefixo)
        counters = self.get_counters_by_prefix(prefixo)
        return counters + histograms + gauges

    def get_counters_by_prefix(self, prefixo: str) -> bytes:
        return self._get_metric_by_prefix("counter", prefixo)

    def get_histograms_by_prefix(self, prefixo: str) -> bytes:
        return self._get_metric_by_prefix("histogram", prefixo)

    def get_gauges_by_prefix(self, prefixo: str) -> bytes:
        return self._get_metric_by_prefix("gauge", prefixo)

    def _get_metric_by_prefix(
        self, tipo_metrica: Literal["counter", "histogram", "gauge"], prefixo: str
    ) -> bytes:
        linhas: list[str] = []
        tipos_metricas: dict[str, Mapping[str, Counter | Gauge | Histogram]] = {
            "counter": self._counters,
            "histogram": self._histograms,
            "gauge": self._gauges,
        }
        metricas = tipos_metricas[tipo_metrica]

        for nome, metrica in metricas.items():
            if not nome.startswith(prefixo):
                continue
            for coletada in metrica.collect():
                linhas.append(f"# HELP {coletada.name} {coletada.documentation}")
                linhas.append(f"# TYPE {coletada.name} {tipo_metrica}")
                for amostra in coletada.samples:
                    rotulos = ",".join(
                        f'{chave}="{valor}"' for chave, valor in amostra.labels.items()
                    )
                    if rotulos:
                        linha = f"{amostra.name}{{{rotulos}}} {amostra.value}"
                    else:
                        linha = f"{amostra.name} {amostra.value}"
                    linhas.append(linha)
        return ("\n".join(linhas) + "\n").encode("utf-8")


prometheus = Prometheus()
