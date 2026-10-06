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

	/**
	 * Entregas de {@code regra-extraida} com desfecho definitivo. Conta entregas, não
	 * jobs: a reentrega de uma extração já gravada sai como {@code duplicada}, nunca como
	 * outra {@code persistida}. A tentativa que falha e volta à fila não tem desfecho e
	 * só aparece em {@link #regraExtraidaDuracao}.
	 */
	public Counter regraExtraidaConsumida(String resultado, String motivo) {
		return Counter.builder("regra.extraida.consumo")
			.description("Mensagens de regra-extraida por resultado do consumo")
			.tag("resultado", resultado)
			.tag("motivo", motivo)
			.register(this.registry);
	}

	/** Cada tentativa de consumo de {@code regra-extraida}, inclusive as que falham. */
	public Timer regraExtraidaDuracao(String resultado) {
		return Timer.builder("regra.extraida.consumo.duracao")
			.description("Duração de cada tentativa de consumo de regra-extraida")
			.tag("resultado", resultado)
			.register(this.registry);
	}

}
