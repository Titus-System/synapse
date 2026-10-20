from prometheus_client import Histogram

from app.nos.codigos_conflito import CodigoConflito

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

# Conta execuções do nó; reentregas sem avanço do checkpoint não passam por ele.
job_runs.labels(job_name="validate_domain")
job_failures.labels(job_name="validate_domain")
job_duration.labels(job_name="validate_domain")
resultados_validacao_dominio = prometheus.register_counter(
    "codegen_validacao_dominio_resultados_total",
    "Validações de domínio concluídas por resultado",
    ["resultado"],
)
for _resultado in ("liberada", "barrada"):
    resultados_validacao_dominio.labels(resultado=_resultado)
# Um incremento por conflito de uma regra barrada, por execução do nó.
conflitos_validacao_dominio = prometheus.register_counter(
    "validacao_conflitos_total",
    "Conflitos apontados pela validação de domínio por código",
    ["codigo"],
)
for _codigo in CodigoConflito:
    conflitos_validacao_dominio.labels(codigo=_codigo.value)

# Conta as entregas da pausa à api. A tentativa que falha ao publicar entra também em
# `job_failures_total`, e a reentrega conta outra execução.
job_runs.labels(job_name="report_conflicts")
job_failures.labels(job_name="report_conflicts")
job_duration.labels(job_name="report_conflicts")

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
MOTIVOS_DE_REBAIXAMENTO = (
    "construto_nao_habilitado",
    "campo_obrigatorio_ausente",
    "valor_sem_lastro",
    "codigo_fora_do_vocabulario",
    "termo_ambiguo",
    "periodo_nao_resolvido",
    "operacao_invalida",
    "referencia_inexistente",
    "operacao_sem_trecho",
)
CLASSES_DE_FALHA_EXTRACAO = (
    "entrada_invalida",
    "regra_indisponivel",
    "transcricao_indisponivel",
    "saida_invalida",
    "provedor",
    "persistencia",
    "publicacao",
    "cancelamento",
)
# A extração inicial e a reextração de uma correção (T-221) contam execuções do nó nos mesmos
# contadores de elementos, rebaixamentos e falhas; `job_name` separa o volume de cada uma. Na
# reextração, os rebaixamentos incluem as operações da correção que não foram aplicadas, e os
# elementos são os da regra corrigida inteira. A reentrega que o checkpoint descarta não conta.
for _no in ("extract_rule", "reextract_rule"):
    job_runs.labels(job_name=_no)
    job_failures.labels(job_name=_no)
    job_duration.labels(job_name=_no)
elementos_extraidos = prometheus.register_counter(
    "codegen_extracao_elementos_total",
    "Campos do núcleo e especificações de extrações concluídas por construto",
    ["construto"],
)
rebaixamentos_extracao = prometheus.register_counter(
    "codegen_extracao_rebaixamentos_total",
    "Elementos rebaixados e operações de correção não aplicadas em extrações concluídas,"
    " por motivo",
    ["motivo"],
)
falhas_extracao = prometheus.register_counter(
    "codegen_extracao_falhas_total",
    "Tentativas de extração que falharam por classe",
    ["classe"],
)
PARAMETROS_DA_SIMULACAO = ("orcamento", "meta_venda", "competencias")
parametros_extracao = prometheus.register_counter(
    "codegen_extracao_parametros_total",
    "Extrações concluídas por parâmetro da simulação e se o texto o trouxe",
    ["parametro", "resultado"],
)
for _construto in CONSTRUTOS_DA_EXTRACAO:
    elementos_extraidos.labels(construto=_construto)
for _motivo in MOTIVOS_DE_REBAIXAMENTO:
    rebaixamentos_extracao.labels(motivo=_motivo)
for _classe in CLASSES_DE_FALHA_EXTRACAO:
    falhas_extracao.labels(classe=_classe)
for _parametro in PARAMETROS_DA_SIMULACAO:
    for _resultado in ("extraido", "ausente"):
        parametros_extracao.labels(parametro=_parametro, resultado=_resultado)

# Uma contagem por tentativa de taxa nova no desfecho dela: o veredito da simulação da
# alternativa, contado pela decisão, ou o motivo de não haver alternativa a propor, contado
# pela sugestão. A proposta publicada ainda não é desfecho. Conta execuções do nó: a
# reentrega de um resultado já processado não passa por ele.
TENTATIVAS_DE_TAXA = ("1", "2", "3")
DESFECHOS_DA_TENTATIVA = (
    "viavel",
    "inviavel",
    "indeterminado",
    "sem_margem",
    "incoerente",
    "nao_suportada",
)
tentativas_de_taxa = prometheus.register_counter(
    "codegen_sugestao_adaptacao_tentativas_total",
    "Tentativas de taxa nova por número da tentativa e desfecho",
    ["tentativa", "desfecho"],
)
for _tentativa in TENTATIVAS_DE_TAXA:
    for _desfecho in DESFECHOS_DA_TENTATIVA:
        tentativas_de_taxa.labels(tentativa=_tentativa, desfecho=_desfecho)

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


# Contam publicações de desfecho e execuções de nós, não entrega duplicada já assentada.
# Uma queda entre publicação e checkpoint pode repetir a publicação e sua observação.
buscas_meta = prometheus.register_counter(
    "codegen_busca_meta_total", "Desfechos publicados da busca de meta", ["desfecho", "motivo"]
)
busca_meta_candidatos = prometheus.register_histogram(
    "codegen_busca_meta_candidatos",
    "Candidatos por busca concluída",
    [],
    buckets=(1, 2, 4, 6, 8, 10, 12, float("inf")),
)
busca_meta_espera = prometheus.register_histogram(
    "codegen_busca_meta_espera_seconds",
    "Espera pelo resultado de uma candidata",
    [],
    buckets=(1, 5, 15, 30, 60, 120, 300, 720, float("inf")),
)
busca_meta_processamento = prometheus.register_histogram(
    "codegen_busca_meta_processamento_seconds", "Processamento ativo da busca, inclusive falhas", []
)
for _desfecho, _motivo in (
    ("sugerida", "encontrada"),
    ("sem_solucao", "nao_monotonica"),
    ("sem_solucao", "intervalo_esgotado"),
    ("sem_solucao", "falha_execucao"),
    ("cancelada", "job_encerrado"),
):
    buscas_meta.labels(desfecho=_desfecho, motivo=_motivo)
