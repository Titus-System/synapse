from prometheus_client import Histogram

from .prometheus import prometheus

# Conta entregas processadas, inclusive continuação após falha transitória; não jobs únicos.
# Uma reentrega sem avanço do grafo é contada separadamente. Tentativas reenfileiradas ainda
# não têm resultado definitivo e não incrementam este contador.
parametros_confirmados = prometheus.register_counter(
    "codegen_parametros_confirmados_total",
    "Mensagens de parametros-confirmados por resultado do consumo",
    ["resultado"],
)
for _resultado in ("ciclo_aberto", "reentrega_ignorada", "descartada"):
    parametros_confirmados.labels(resultado=_resultado)

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
    # Preserve existing bounds and cover the model's 60-second timeout plus retries.
    buckets=(*Histogram.DEFAULT_BUCKETS[:-1], 15, 30, 45, 60, 90, 120, 180, 240, 300, float("inf")),
)

CONSTRUTOS_DA_EXTRACAO = (
    "nucleo",
    "generico",
    "faixa_valor",
    "condicao_limiar",
    "janela_datas",
    "exclusao",
    "bonus_fixo",
    "outro",
)
MOTIVOS_DE_REBAIXAMENTO = ("construto_nao_habilitado", "campo_obrigatorio_ausente")
CLASSES_DE_FALHA_EXTRACAO = (
    "entrada_invalida",
    "transcricao_indisponivel",
    "saida_invalida",
    "provedor",
    "persistencia",
    "publicacao",
    "cancelamento",
)
job_runs.labels(job_name="extract_rule")
job_failures.labels(job_name="extract_rule")
job_duration.labels(job_name="extract_rule")
elementos_extraidos = prometheus.register_counter(
    "codegen_extracao_elementos_total",
    "Campos do núcleo e especificações de extrações concluídas por construto",
    ["construto"],
)
rebaixamentos_extracao = prometheus.register_counter(
    "codegen_extracao_rebaixamentos_total",
    "Elementos rebaixados em extrações concluídas por motivo",
    ["motivo"],
)
falhas_extracao = prometheus.register_counter(
    "codegen_extracao_falhas_total",
    "Tentativas de extração que falharam por classe",
    ["classe"],
)
for _construto in CONSTRUTOS_DA_EXTRACAO:
    elementos_extraidos.labels(construto=_construto)
for _motivo in MOTIVOS_DE_REBAIXAMENTO:
    rebaixamentos_extracao.labels(motivo=_motivo)
for _classe in CLASSES_DE_FALHA_EXTRACAO:
    falhas_extracao.labels(classe=_classe)

# Uma tentativa por job encerrado que ainda tinha checkpoints a remover. `adiada` é a tentativa
# que esbarrou num processamento em andamento ou num ciclo à espera do resultado e será refeita
# quando ele terminar; não é falha. Jobs não encerrados ou já limpos não contam.
limpezas_de_checkpoint = prometheus.register_counter(
    "checkpoint_limpezas_total",
    "Tentativas de limpar os checkpoints de um job encerrado, por resultado",
    ["resultado"],
)

limpeza_de_checkpoint_duracao = prometheus.register_histogram(
    "checkpoint_limpeza_duracao_seconds",
    "Duração de uma tentativa de limpeza dos checkpoints de um job encerrado, por resultado",
    ["resultado"],
)

# Uma contagem por chamada ao modelo que teve falha de provedor (429, 5xx, timeout ou conexão),
# no desfecho dela: `recuperado` quando uma nova tentativa funcionou, `esgotado` quando a janela
# acabou. Não conta cada tentativa nem a espera interrompida por um job encerrado.
falhas_do_provedor = prometheus.register_counter(
    "llm_provider_failures_total",
    "Chamadas ao modelo com falha de provedor, por nó e desfecho",
    ["no", "desfecho"],
)

# Tempo entre a primeira falha de provedor de uma chamada e o fim da espera, em qualquer
# desfecho. É espera por um terceiro, e não o tempo de execução do nó (`job_duration_seconds`).
# A contagem é maior que a soma de `llm_provider_failures_total`: a espera encerrada por um job
# encerrado, ou por uma falha que não é do provedor, é medida aqui e não tem desfecho lá.
espera_do_provedor = prometheus.register_histogram(
    "llm_provider_wait_seconds",
    "Tempo de espera pelo provedor indisponível, por nó",
    ["no"],
    buckets=(30, 60, 120, 240, 360, 480, 600, 720, float("inf")),
)
for _no in ("extracao_parametros", "geracao_codigo"):
    espera_do_provedor.labels(no=_no)
    for _desfecho in ("recuperado", "esgotado"):
        falhas_do_provedor.labels(no=_no, desfecho=_desfecho)
