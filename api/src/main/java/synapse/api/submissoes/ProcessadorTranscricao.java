package synapse.api.submissoes;

import java.time.Duration;
import java.time.Clock;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.Objects;
import java.util.UUID;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Semaphore;
import java.util.concurrent.RejectedExecutionException;

import jakarta.annotation.PreDestroy;

import org.jspecify.annotations.Nullable;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import org.springframework.stereotype.Component;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

import synapse.api.core.config.AppProperties;
import synapse.api.core.logging.CorrelationContext;
import synapse.api.core.metrics.AppMetrics;
import synapse.api.job.JobsDeSubmissoes;
import synapse.api.submissoes.SubmissoesRepository.FinalidadeTrabalho;

/**
 * Transcreve os áudios já persistidos, com simultaneidade limitada, em três passos: uma
 * transação curta reserva o trabalho, a chamada ao provedor acontece sem transação
 * aberta, e uma transação nova grava o texto e encerra o trabalho junto com a transição
 * do job, ou a da rodada na correção, e o seu evento de outbox.
 *
 * <p>
 * A chamada externa nunca mantém aberta a transação que grava o job e o seu evento: ela
 * dura até a soma dos tempos limite do cliente, e uma transação desse tamanho prenderia
 * uma conexão do pool e as travas das linhas lidas. É o motivo de a reserva existir.
 *
 * <p>
 * O estado do job, a trilha, o motivo, a rodada, o {@code regra-submetida} e o
 * {@code correcao-submetida} pertencem ao domínio {@code job}, e são alterados pelas
 * operações públicas de {@link JobsDeSubmissoes} dentro da transação final. Este
 * processador não toca a máquina de estados, as rodadas nem o outbox.
 */
@Component
class ProcessadorTranscricao {

	private static final Logger log = LoggerFactory.getLogger(ProcessadorTranscricao.class);

	private final SubmissoesRepository repository;

	private final ClienteDeepgram cliente;

	private final JobsDeSubmissoes jobs;

	private final TransactionTemplate transacao;

	private final CorrelationContext correlacao;

	private final AppMetrics metrics;

	private final AppProperties.Transcription.Processor properties;

	private final Clock relogio;

	private final Semaphore vagas;

	private final ExecutorService executor;

	@Autowired
	ProcessadorTranscricao(SubmissoesRepository repository, ClienteDeepgram cliente, JobsDeSubmissoes jobs,
			PlatformTransactionManager transacoes, CorrelationContext correlacao, AppMetrics metrics,
			AppProperties properties) {
		this(repository, cliente, jobs, transacoes, correlacao, metrics, properties, Clock.systemUTC());
	}

	ProcessadorTranscricao(SubmissoesRepository repository, ClienteDeepgram cliente, JobsDeSubmissoes jobs,
			PlatformTransactionManager transacoes, CorrelationContext correlacao, AppMetrics metrics,
			AppProperties properties, Clock relogio) {
		this.repository = repository;
		this.cliente = cliente;
		this.jobs = jobs;
		this.transacao = new TransactionTemplate(transacoes);
		this.correlacao = correlacao;
		this.metrics = metrics;
		this.properties = properties.transcription().processor();
		this.relogio = relogio;
		this.vagas = new Semaphore(this.properties.concurrency());
		this.executor = Executors.newFixedThreadPool(this.properties.concurrency());
	}

	@PreDestroy
	void encerrar() {
		this.executor.shutdownNow();
	}

	/** O scheduler apenas despacha; nenhuma chamada externa ocupa sua thread. */
	void agendarPendentes() {
		for (int i = 0; i < this.properties.concurrency() && this.vagas.tryAcquire(); i++) {
			try {
				this.executor.execute(() -> {
					try {
						drenar();
					}
					catch (RuntimeException ex) {
						log.atError()
							.addKeyValue("excecao", ex.getClass().getSimpleName())
							.log("ciclo de transcrição interrompido");
					}
					finally {
						this.vagas.release();
					}
				});
			}
			catch (RejectedExecutionException ex) {
				this.vagas.release();
				return;
			}
		}
	}

	/**
	 * Um ciclo: processa os trabalhos elegíveis até não restar nenhum. Uma falha de um
	 * trabalho não interrompe o ciclo - diferente do poller do outbox, não há ordem a
	 * preservar entre trabalhos de jobs distintos.
	 */
	void processarPendentes() {
		if (!this.vagas.tryAcquire()) {
			return;
		}
		try {
			drenar();
		}
		finally {
			this.vagas.release();
		}
	}

	private void drenar() {
		while (!Thread.currentThread().isInterrupted() && !this.executor.isShutdown() && processarUm()) {
			// Enquanto houver trabalho elegível, o ciclo continua.
		}
	}

	private boolean processarUm() {
		Instant agora = agora();
		var reservados = this.repository.reservarTrabalho(agora, this.properties.reservationTimeout(),
				this.properties.maxAttempts());
		if (reservados.isEmpty()) {
			return false;
		}
		var trabalho = reservados.getFirst();
		try (var escopo = this.correlacao.abrir(trabalho.jobId().toString(), null)) {
			if (trabalho.recuperado()) {
				log.atWarn()
					.addKeyValue("trabalho_id", trabalho.id())
					.addKeyValue("tentativas", trabalho.tentativas())
					.log("reserva vencida de transcrição recuperada");
			}
			else if (trabalho.tentativas() == 1) {
				this.metrics.transcricaoEspera()
					.record(Duration.between(trabalho.criadoEm(), agora).toNanos(), TimeUnit.NANOSECONDS);
			}
			log.atInfo()
				.addKeyValue("trabalho_id", trabalho.id())
				.addKeyValue("tentativas", trabalho.tentativas())
				.log("trabalho de transcrição reservado");
			processar(trabalho);
		}
		return true;
	}

	private void processar(SubmissoesRepository.TrabalhoReservado trabalho) {
		Desfecho desfecho = transcrever(trabalho);
		Instant proxima = proximaTentativa(desfecho, agora());
		Resultado resultado;
		try {
			resultado = Objects.requireNonNull(this.transacao.execute(status -> gravar(trabalho, desfecho, proxima)));
		}
		catch (RuntimeException ex) {
			// Nem a mensagem nem a causa: a exceção do driver pode carregar a linha.
			log.atError()
				.addKeyValue("trabalho_id", trabalho.id())
				.addKeyValue("excecao", ex.getClass().getSimpleName())
				.log("processamento da transcrição interrompido");
			resultado = Resultado.INTERROMPIDA;
		}
		this.metrics.transcricaoTrabalho(trabalho.finalidade().paraColuna(), resultado.rotulo).increment();
		var evento = resultado.falha ? log.atWarn() : log.atInfo();
		evento.addKeyValue("trabalho_id", trabalho.id())
			.addKeyValue("finalidade", trabalho.finalidade().paraColuna())
			.addKeyValue("tentativas", trabalho.tentativas())
			.addKeyValue("resultado", resultado.rotulo)
			.addKeyValue("classe_motivo", desfecho.classeDoMotivo)
			.addKeyValue("proxima_tentativa_em", resultado == Resultado.NOVA_TENTATIVA ? proxima.toString() : null)
			.log("transcrição processada");
	}

	/** Mede somente chamadas efetivas; uma reserva esgotada não chama o provedor. */
	private Desfecho transcrever(SubmissoesRepository.TrabalhoReservado trabalho) {
		if (trabalho.limiteEsgotado()) {
			return Desfecho.falha("reserva_vencida", "falhou_transitoria");
		}
		long inicio = System.nanoTime();
		Desfecho desfecho = chamar(trabalho);
		this.metrics.transcricaoChamada(desfecho.medidaDaChamada)
			.record(System.nanoTime() - inicio, TimeUnit.NANOSECONDS);
		return desfecho;
	}

	private Desfecho chamar(SubmissoesRepository.TrabalhoReservado trabalho) {
		try {
			var gravados = this.repository.lerAudio(trabalho.submissaoId());
			if (gravados.isEmpty()) {
				return Desfecho.falha("permanente", "falhou_permanente");
			}
			var audio = gravados.getFirst();
			String texto = this.cliente.transcrever(audio.bytes(), "audio/" + audio.formato(),
					trabalho.respostaInvalida());
			if (EntradaSubmissao.semConteudo(texto)) {
				return Desfecho.falha("texto_vazio", "texto_vazio");
			}
			return Desfecho.sucesso(texto);
		}
		catch (TranscricaoTransitoriaException ex) {
			return new Desfecho(null, "transitoria", "falhou_transitoria", ex.prazoParaNovaTentativa(),
					ex.respostaInvalida(), trabalho.tentativas());
		}
		catch (TranscricaoPermanenteException ex) {
			return Desfecho.falha("permanente", "falhou_permanente");
		}
		catch (RuntimeException ex) {
			// O cliente já registrou o que podia; aqui só a classe, sem a mensagem.
			log.atWarn()
				.addKeyValue("trabalho_id", trabalho.id())
				.addKeyValue("excecao", ex.getClass().getSimpleName())
				.log("chamada de transcrição falhou de forma inesperada");
			return Desfecho.falha("inesperada", "falhou_permanente");
		}
	}

	/**
	 * A transação final. A trava do trabalho vem antes da do job, que a porta toma: as
	 * outras escritas do job travam só o job ou inserem linhas novas, então a ordem não
	 * fecha ciclo.
	 *
	 * <p>
	 * A porta devolve false quando o job ou a rodada da correção já saiu da espera -
	 * cancelado pelo usuário enquanto o provedor respondia, por exemplo. Nesse caso o
	 * trabalho é descartado e nada mais é gravado: nem o texto, nem a transição, nem o
	 * evento.
	 */
	private Resultado gravar(SubmissoesRepository.TrabalhoReservado trabalho, Desfecho desfecho, Instant proxima) {
		if (!this.repository.reservaAindaENossa(trabalho.id(), trabalho.tentativas(), trabalho.reservadoAte())) {
			return Resultado.RESERVA_PERDIDA;
		}
		Instant agora = agora();
		boolean correcao = trabalho.finalidade() == FinalidadeTrabalho.CORRECAO;
		UUID jobId = trabalho.jobId();
		UUID submissaoId = trabalho.submissaoId();
		String texto = desfecho.texto;
		if (texto == null) {
			if ("transitoria".equals(desfecho.classeDoMotivo)
					&& trabalho.tentativas() < this.properties.maxAttempts()) {
				boolean aguardando = correcao ? this.jobs.aguardandoTranscricaoDaCorrecao(jobId, submissaoId)
						: this.jobs.aguardandoTranscricao(jobId, submissaoId);
				if (!aguardando) {
					this.repository.encerrarTrabalho(trabalho.id(), "descartado", agora);
					return Resultado.DESCARTADA;
				}
				this.repository.reagendar(trabalho.id(), agora, proxima, desfecho.respostaInvalida);
				return Resultado.NOVA_TENTATIVA;
			}
			boolean aplicada = correcao ? this.jobs.falharTranscricaoDaCorrecao(jobId, submissaoId)
					: this.jobs.falharTranscricao(jobId, submissaoId);
			this.repository.encerrarTrabalho(trabalho.id(), aplicada ? "falhou" : "descartado", agora);
			return aplicada ? ("transitoria".equals(desfecho.classeDoMotivo) || trabalho.limiteEsgotado()
					? Resultado.ESGOTADO : Resultado.FALHOU_PERMANENTE) : Resultado.DESCARTADA;
		}
		boolean concluida = correcao ? this.jobs.concluirTranscricaoDaCorrecao(jobId, submissaoId)
				: this.jobs.concluirTranscricao(jobId, submissaoId);
		if (!concluida) {
			this.repository.encerrarTrabalho(trabalho.id(), "descartado", agora);
			return Resultado.DESCARTADA;
		}
		this.repository.gravarTranscricao(submissaoId, texto, agora);
		this.repository.encerrarTrabalho(trabalho.id(), "concluido", agora);
		return Resultado.CONCLUIDA;
	}

	/** O que a chamada ao provedor produziu: o texto, ou a classe da falha. */
	private record Desfecho(@Nullable String texto, String classeDoMotivo, String medidaDaChamada, Duration prazo,
			boolean respostaInvalida, int tentativa) {

		private static Desfecho sucesso(String texto) {
			return new Desfecho(texto, "nenhum", "concluida", Duration.ZERO, false, 0);
		}

		private static Desfecho falha(String classeDoMotivo, String medidaDaChamada) {
			return new Desfecho(null, classeDoMotivo, medidaDaChamada, Duration.ZERO, false, 0);
		}

	}

	private Instant agora() {
		return this.relogio.instant().truncatedTo(ChronoUnit.MICROS);
	}

	private Instant proximaTentativa(Desfecho desfecho, Instant agora) {
		Duration espera = this.properties.initialBackoff();
		for (int i = 1; i < desfecho.tentativa && espera.compareTo(this.properties.maxBackoff()) < 0; i++) {
			try {
				espera = espera.multipliedBy(this.properties.backoffMultiplier());
			}
			catch (ArithmeticException ex) {
				espera = this.properties.maxBackoff();
			}
		}
		if (espera.compareTo(this.properties.maxBackoff()) > 0) {
			espera = this.properties.maxBackoff();
		}
		if (desfecho.prazo.compareTo(espera) > 0) {
			espera = desfecho.prazo;
		}
		return agora.plus(espera);
	}

	/** O desfecho do trabalho, já considerando a transação final. */
	private enum Resultado {

		CONCLUIDA("concluida", false), NOVA_TENTATIVA("nova_tentativa", true), ESGOTADO("esgotado", true),
		FALHOU_PERMANENTE("falhou_permanente", true), DESCARTADA("descartada", false),
		RESERVA_PERDIDA("reserva_perdida", false), INTERROMPIDA("interrompida", true);

		private final String rotulo;

		private final boolean falha;

		Resultado(String rotulo, boolean falha) {
			this.rotulo = rotulo;
			this.falha = falha;
		}

	}

}
