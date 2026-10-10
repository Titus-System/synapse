from .prometheus import prometheus

# Uma observação por stdout com envelope reconhecido na coleta, incluindo a quebra
# de linha. O status é o do envelope, mesmo se o detalhamento for recusado depois.
# Sem envelope válido (timeout, OOM, truncamento, infra) não há status a atribuir.
sandbox_envelope_bytes = prometheus.register_histogram(
    "sandbox_envelope_bytes",
    "Tamanho em bytes do stdout do envelope coletado, por status do sandbox",
    ["status"],
    buckets=(1024, 16384, 65536, 262144, 524288, 786432, 943718, 1048576),
)
for _status in ("sucesso", "assercao_violada", "erro_codigo"):
    sandbox_envelope_bytes.labels(status=_status)

request_count = prometheus.register_counter(
    "app_requests_total", "Total HTTP requests", ["method", "endpoint", "status"]
)

request_latency = prometheus.register_histogram(
    "app_request_latency_seconds", "HTTP request latency", ["method", "endpoint"]
)

error_count = prometheus.register_counter(
    "app_errors_total", "Total errors in the application", ["endpoint", "exception_type"]
)

system_memory_usage = prometheus.register_gauge(
    "system_memory_usage_percentage", "System memory usage percentage", ["type"]
)

system_memory_bytes = prometheus.register_gauge(
    "system_memory_bytes", "System memory in bytes", ["type"]
)

system_cpu_usage = prometheus.register_gauge(
    "system_cpu_usage_percentage", "System CPU usage percentage"
)

system_cpu_count = prometheus.register_gauge("system_cpu_count", "Number of CPU cores")

job_runs = prometheus.register_counter(
    "job_runs_total", "Total number of jobs executed", ["job_name"]
)

job_failures = prometheus.register_counter(
    "job_failures_total", "Number of failed executions of jobs", ["job_name"]
)

job_duration = prometheus.register_histogram(
    "job_duration_seconds",
    "Execution duration of jobs in seconds",
    ["job_name"],
)

# Uma por execução no sandbox julgada com cobertura incompleta (T-241), e não por job: a
# reentrega que encontra o resultado já gravado não executa nem julga de novo e não conta, e a
# execução repetida porque a gravação falhou é outra execução e conta de novo.
execucoes_com_cobertura_incompleta = prometheus.register_counter(
    "worker_cobertura_incompleta_total",
    "Execuções no sandbox reprovadas porque o código gerado não cobre os elementos exigidos",
)

# O desfecho de cada execução no sandbox julgada, o mesmo que vai para a linha e o evento:
# o veredito de um sucesso, sem_orcamento num sucesso de job sem orçamento (T-281), e a classe
# nos demais. Conta execuções, não jobs: a reentrega que encontra o resultado já gravado não
# executa nem julga de novo e não conta, e cada tentativa de um erro_infra conta como uma.
DESFECHOS_DA_EXECUCAO = (
    "viavel",
    "inviavel",
    "sem_orcamento",
    "assercao_violada",
    "erro_codigo",
    "erro_infra",
)

execucoes_julgadas = prometheus.register_counter(
    "worker_execucoes_julgadas_total",
    "Execuções no sandbox julgadas pelo worker, por desfecho",
    ["desfecho"],
)
for _desfecho in DESFECHOS_DA_EXECUCAO:
    execucoes_julgadas.labels(desfecho=_desfecho)
