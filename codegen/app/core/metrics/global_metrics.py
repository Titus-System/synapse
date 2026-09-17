from .prometheus import prometheus

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
