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
	 * Criações confirmadas e recusas de submissão, por tipo e classe fechada de
	 * resultado.
	 */
	public Counter submissaoCriacao(String tipo, String resultado) {
		return Counter.builder("submissoes.criacao")
			.description("Criações confirmadas e recusas de submissão; rollback não conta como aceita")
			.tag("tipo", tipo)
			.tag("resultado", resultado)
			.register(this.registry);
	}

	/**
	 * Trabalhos de transcrição com desfecho, um incremento por trabalho processado.
	 * {@code resultado} vem de um conjunto fechado - {@code concluida},
	 * {@code falhou_transitoria}, {@code falhou_permanente}, {@code descartada},
	 * {@code reserva_perdida} e {@code interrompida}. Só {@code concluida} é conclusão de
	 * negócio: a retomada de uma reserva vencida e a reserva perdida para outra instância
	 * não produzem texto nem evento.
	 */
	public Counter transcricaoTrabalho(String resultado) {
		return Counter.builder("transcricao.trabalhos")
			.description("Trabalhos de transcrição processados, por desfecho; só concluida produz texto e evento")
			.tag("resultado", resultado)
			.register(this.registry);
	}

	/**
	 * Duração da chamada ao provedor, medida também quando ela falha. É distinta de
	 * {@link #transcricaoEspera}, que mede o tempo na fila, e de
	 * {@link #transcricaoTransicao}, que mede a transação final.
	 */
	public Timer transcricaoChamada(String resultado) {
		return Timer.builder("transcricao.chamada")
			.description("Duração da chamada ao provedor de transcrição, inclusive nas falhas")
			.tag("resultado", resultado)
			.register(this.registry);
	}

	/**
	 * Espera do trabalho entre a criação e a primeira reserva. A retomada de uma reserva
	 * vencida não registra espera: ela mediria o tempo da reserva anterior, não da fila.
	 */
	public Timer transcricaoEspera() {
		return Timer.builder("transcricao.espera")
			.description("Tempo entre a criação do trabalho de transcrição e sua primeira reserva")
			.register(this.registry);
	}

	/** Chamadas à porta de transcrição até o término da transação, não jobs únicos. */
	public Timer transcricaoTransicao(String operacao, String resultado) {
		return Timer.builder("transcricao.transicao")
			.description("Chamadas à porta de transcrição até commit ou rollback; descartes não são conclusões")
			.tag("operacao", operacao)
			.tag("resultado", resultado)
			.register(this.registry);
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

	/**
	 * Entregas de {@code simulacao-concluida} consumidas, por desfecho e resultado do
	 * consumo. Conta entregas, não jobs: a reentrega de um desfecho já aplicado sai como
	 * {@code estado_incompativel}, nunca como outra {@code aplicada}. {@code desfecho} é
	 * {@code viavel}, {@code inviavel}, {@code indeterminado}, {@code sem_orcamento},
	 * {@code assercao_violada}, {@code erro_codigo}, {@code erro_infra} ou
	 * {@code desconhecido}; {@code resultado} é {@code aplicada},
	 * {@code estado_incompativel}, {@code versao_anterior} ou {@code invalida}.
	 */
	public Counter simulacaoConcluidaConsumida(String desfecho, String resultado) {
		return Counter.builder("simulacao.concluida.consumo")
			.description("Mensagens de simulacao-concluida por desfecho e resultado do consumo")
			.tag("desfecho", desfecho)
			.tag("resultado", resultado)
			.register(this.registry);
	}

	/**
	 * Parâmetros da simulação extraídos do texto e gravados no job, um incremento por
	 * parâmetro gravado. {@code parametro} vem de um conjunto limitado -
	 * {@code orcamento}, {@code meta_venda}, {@code competencias} -, nunca o valor dito:
	 * o que se mede é quantos jobs chegam com cada parâmetro, e a comparação com
	 * {@code regra.extraida.consumo} por {@code resultado=persistida} dá a proporção.
	 * Conta gravações, não entregas: a reentrega não regrava e não incrementa.
	 */
	public Counter parametroDaSimulacaoGravado(String parametro) {
		return Counter.builder("job.parametros.gravados")
			.description("Parâmetros da simulação extraídos do texto e gravados no job")
			.tag("parametro", parametro)
			.register(this.registry);
	}

}
