from collections.abc import Mapping
from typing import Literal

from prometheus_client import Counter, Gauge, Histogram, generate_latest


class Prometheus:
    """
    Abstraction over prometheus_client for both infrastructure and domain metrics.
    """

    def __init__(self) -> None:
        self._counters: dict[str, Counter] = {}
        self._gauges: dict[str, Gauge] = {}
        self._histograms: dict[str, Histogram] = {}

    def register_counter(
        self, name: str, description: str, labels: list[str] | None = None
    ) -> Counter:
        if name not in self._counters:
            self._counters[name] = Counter(name, description, labels or [])
        return self._counters[name]

    def register_gauge(self, name: str, description: str, labels: list[str] | None = None) -> Gauge:
        if name not in self._gauges:
            self._gauges[name] = Gauge(name, description, labels or [])
        return self._gauges[name]

    def register_histogram(
        self, name: str, description: str, labels: list[str] | None = None
    ) -> Histogram:
        if name not in self._histograms:
            self._histograms[name] = Histogram(name, description, labels or [])
        return self._histograms[name]

    def get_all(self) -> bytes:
        """Return all metrics in Prometheus text format"""
        data: bytes = generate_latest()
        return data

    def get_all_by_prefix(self, prefix: str) -> bytes:
        """Return all registered metrics objects whose name starts with `prefix`."""
        gauges = self.get_gauges_by_prefix(prefix)
        histograms = self.get_histograms_by_prefix(prefix)
        counters = self.get_counters_by_prefix(prefix)
        return counters + histograms + gauges

    def get_counters_by_prefix(self, prefix: str) -> bytes:
        return self._get_metric_by_prefix("counter", prefix)

    def get_histograms_by_prefix(self, prefix: str) -> bytes:
        return self._get_metric_by_prefix("histogram", prefix)

    def get_gauges_by_prefix(self, prefix: str) -> bytes:
        return self._get_metric_by_prefix("gauge", prefix)

    def _get_metric_by_prefix(
        self, metric_type: Literal["counter", "histogram", "gauge"], prefix: str
    ) -> bytes:
        lines: list[str] = []
        types_map: dict[str, Mapping[str, Counter | Gauge | Histogram]] = {
            "counter": self._counters,
            "histogram": self._histograms,
            "gauge": self._gauges,
        }
        metrics = types_map[metric_type]

        for name, metric in metrics.items():
            if not name.startswith(prefix):
                continue
            for collected in metric.collect():
                lines.append(f"# HELP {collected.name} {collected.documentation}")
                lines.append(f"# TYPE {collected.name} {metric_type}")
                for sample in collected.samples:
                    label_str = ",".join(f'{k}="{v}"' for k, v in sample.labels.items())
                    if label_str:
                        line = f"{sample.name}{{{label_str}}} {sample.value}"
                    else:
                        line = f"{sample.name} {sample.value}"
                    lines.append(line)
        return ("\n".join(lines) + "\n").encode("utf-8")


prometheus = Prometheus()
