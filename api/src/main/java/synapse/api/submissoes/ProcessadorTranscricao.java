package synapse.api.submissoes;

import java.time.Duration;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.Objects;
import java.util.concurrent.TimeUnit;

import org.jspecify.annotations.Nullable;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import org.springframework.stereotype.Component;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

import synapse.api.core.config.AppProperties;
import synapse.api.core.logging.CorrelationContext;
import synapse.api.core.metrics.AppMetrics;
import synapse.api.job.JobsDeSubmissoes;

/**
 * Transcreve os áudios já persistidos, um trabalho por vez, em três passos: uma transação
 * curta reserva o trabalho, a chamada ao provedor acontece sem transação aberta, e uma
 * transação nova grava o texto e encerra o trabalho junto com a transição do job e o seu
 * evento de outbox.
 *
 * <p>
 * A chamada externa nunca mantém aberta a transação que grava o job e o seu evento: ela
 * dura até a soma dos tempos limite do cliente, e uma transação desse tamanho prenderia
 * uma conexão do pool e as travas das linhas lidas. É o motivo de a reserva existir.
 *
 * <p>
 * O estado do job, a trilha, o motivo e o {@code regra-submetida} pertencem ao domínio
 * {@code job}, e são alterados pelas operações públicas de {@link JobsDeSubmissoes}
 * dentro da transação final. Este processador não toca a máquina de estados nem o outbox.
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

	ProcessadorTranscricao(SubmissoesRepository repository, ClienteDeepgram cliente, JobsDeSubmissoes jobs,
			PlatformTransactionManager transacoes, CorrelationContext correlacao, AppMetrics metrics,
			AppProperties properties) {
		this.repository = repository;
		this.cliente = cliente;
		this.jobs = jobs;
		this.transacao = new TransactionTemplate(transacoes);
		this.correlacao = correlacao;
		this.metrics = metrics;
		this.properties = properties.transcription().processor();
	}

	/**
	 * Um ciclo: processa os trabalhos elegíveis até não restar nenhum. Uma falha de um
	 * trabalho não interrompe o ciclo - diferente do poller do outbox, não há ordem a
	 * preservar entre trabalhos de jobs distintos.
	 */
	void processarPendentes() {
		while (processarUm()) {
			// Enquanto houver trabalho elegível, o ciclo continua.
		}
	}

	private boolean processarUm() {
		Instant agora = Instant.now().truncatedTo(ChronoUnit.MICROS);
		var reservados = this.repository.reservarTrabalho(agora, this.properties.reservationTimeout());
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
			else {
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
		Resultado resultado;
		try {
			resultado = Objects.requireNonNull(this.transacao.execute(status -> gravar(trabalho, desfecho)));
		}
		catch (RuntimeException ex) {
			// Nem a mensagem nem a causa: a exceção do driver pode carregar a linha.
			log.atError()
				.addKeyValue("trabalho_id", trabalho.id())
				.addKeyValue("excecao", ex.getClass().getSimpleName())
				.log("processamento da transcrição interrompido");
			resultado = Resultado.INTERROMPIDA;
		}
		this.metrics.transcricaoTrabalho(resultado.rotulo).increment();
		var evento = resultado.falha ? log.atWarn() : log.atInfo();
		evento.addKeyValue("trabalho_id", trabalho.id())
			.addKeyValue("tentativas", trabalho.tentativas())
			.addKeyValue("resultado", resultado.rotulo)
			.addKeyValue("classe_motivo", desfecho.classeDoMotivo)
			.log("transcrição processada");
	}

	/**
	 * A chamada ao provedor, fora de transação. Toda falha termina o job em erro neste
	 * esqueleto; as novas tentativas com espera crescente são da T-237, e por isso o
	 * desfecho distingue a falha transitória da permanente somente no sinal observável.
	 */
	private Desfecho transcrever(SubmissoesRepository.TrabalhoReservado trabalho) {
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
			String texto = this.cliente.transcrever(audio.bytes(), "audio/" + audio.formato());
			if (EntradaSubmissao.semConteudo(texto)) {
				return Desfecho.falha("texto_vazio", "texto_vazio");
			}
			return Desfecho.sucesso(texto);
		}
		catch (TranscricaoTransitoriaException ex) {
			return Desfecho.falha("transitoria", "falhou_transitoria");
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
	 * A porta devolve false quando o job já saiu da espera - cancelado pelo usuário
	 * enquanto o provedor respondia, por exemplo. Nesse caso o trabalho é descartado e
	 * nada mais é gravado: nem o texto, nem a transição, nem o evento.
	 */
	private Resultado gravar(SubmissoesRepository.TrabalhoReservado trabalho, Desfecho desfecho) {
		if (!this.repository.reservaAindaENossa(trabalho.id(), trabalho.tentativas())) {
			return Resultado.RESERVA_PERDIDA;
		}
		Instant agora = Instant.now().truncatedTo(ChronoUnit.MICROS);
		String texto = desfecho.texto;
		if (texto == null) {
			boolean aplicada = this.jobs.falharTranscricao(trabalho.jobId(), trabalho.submissaoId());
			this.repository.encerrarTrabalho(trabalho.id(), aplicada ? "falhou" : "descartado", agora);
			return aplicada ? desfecho.resultado() : Resultado.DESCARTADA;
		}
		if (!this.jobs.concluirTranscricao(trabalho.jobId(), trabalho.submissaoId())) {
			this.repository.encerrarTrabalho(trabalho.id(), "descartado", agora);
			return Resultado.DESCARTADA;
		}
		this.repository.gravarTranscricao(trabalho.submissaoId(), texto, agora);
		this.repository.encerrarTrabalho(trabalho.id(), "concluido", agora);
		return Resultado.CONCLUIDA;
	}

	/** O que a chamada ao provedor produziu: o texto, ou a classe da falha. */
	private record Desfecho(@Nullable String texto, String classeDoMotivo, String medidaDaChamada) {

		private static Desfecho sucesso(String texto) {
			return new Desfecho(texto, "nenhum", "concluida");
		}

		private static Desfecho falha(String classeDoMotivo, String medidaDaChamada) {
			return new Desfecho(null, classeDoMotivo, medidaDaChamada);
		}

		private Resultado resultado() {
			return "transitoria".equals(this.classeDoMotivo) ? Resultado.FALHOU_TRANSITORIA
					: Resultado.FALHOU_PERMANENTE;
		}

	}

	/** O desfecho do trabalho, já considerando a transação final. */
	private enum Resultado {

		CONCLUIDA("concluida", false), FALHOU_TRANSITORIA("falhou_transitoria", true),
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
