package synapse.api.core.metrics;

import java.util.concurrent.Callable;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;

import org.springframework.stereotype.Component;

/**
 * Métricas de domínio. O que o Actuator já publica sozinho —
 * {@code http_server_requests_seconds}, {@code jvm_*}, {@code process_*},
 * {@code system_*} — não entra aqui.
 */
@Component
public class AppMetrics {

	private final MeterRegistry registry;

	public AppMetrics(MeterRegistry registry) {
		this.registry = registry;
	}

	/**
	 * Executa o job contabilizando execução, duração e falha. {@code jobName} precisa vir
	 * de um conjunto limitado, como {@code "generate_code"} — nunca o id do job.
	 */
	public <T> T recordJob(String jobName, Callable<T> job) throws Exception {
		jobRuns(jobName).increment();
		try {
			return jobDuration(jobName).recordCallable(job);
		}
		catch (Exception ex) {
			jobFailures(jobName).increment();
			throw ex;
		}
	}

	public Counter jobRuns(String jobName) {
		return Counter.builder("job.runs")
			.description("Total number of jobs executed")
			.tag("job_name", jobName)
			.register(this.registry);
	}

	public Counter jobFailures(String jobName) {
		return Counter.builder("job.failures")
			.description("Number of failed executions of jobs")
			.tag("job_name", jobName)
			.register(this.registry);
	}

	public Timer jobDuration(String jobName) {
		return Timer.builder("job.duration")
			.description("Execution duration of jobs")
			.tag("job_name", jobName)
			.register(this.registry);
	}

}
