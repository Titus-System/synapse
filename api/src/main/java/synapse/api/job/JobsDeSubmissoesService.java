package synapse.api.job;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.UUID;
import java.util.concurrent.TimeUnit;

import org.jspecify.annotations.Nullable;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import synapse.api.core.logging.CorrelationContext;
import synapse.api.core.metrics.AppMetrics;
import synapse.api.core.outbox.EventoOutbox;
import synapse.api.core.outbox.Outbox;
import synapse.api.core.security.AcessoDoUsuario;
import synapse.api.core.sse.EmissoresSse;
import synapse.api.core.sse.EventoSse;

@Service
@Transactional(propagation = Propagation.MANDATORY)
class JobsDeSubmissoesService implements JobsDeSubmissoes {

	private static final Logger log = LoggerFactory.getLogger(JobsDeSubmissoesService.class);

	private final JobRepository repository;

	private final MaquinaDeEstadosDoJob maquina;

	private final AutorizadorDeJob autorizador;

	private final Outbox outbox;

	private final CorrelationContext correlacao;

	private final AppMetrics metrics;

	private final EmissoresSse emissores;

	JobsDeSubmissoesService(JobRepository repository, MaquinaDeEstadosDoJob maquina, AutorizadorDeJob autorizador,
			Outbox outbox, CorrelationContext correlacao, AppMetrics metrics, EmissoresSse emissores) {
		this.repository = repository;
		this.maquina = maquina;
		this.autorizador = autorizador;
		this.outbox = outbox;
		this.correlacao = correlacao;
		this.metrics = metrics;
		this.emissores = emissores;
	}

	@Override
	public JobCriado criar(UUID submissaoId, TipoEntrada tipo, AcessoDoUsuario acesso, Instant criadoEm) {
		this.autorizador.exigir(OperacaoJob.CRIAR, null, acesso);
		JobStatus status = tipo == TipoEntrada.TEXTO ? JobStatus.GERANDO_REGRA : JobStatus.AGUARDANDO_TRANSCRICAO;
		UUID id = this.repository.inserirJob(status.paraColuna(), acesso.usuarioId(), submissaoId,
				CompetenciasPublicadas.TODAS, null, Timestamp.from(criadoEm));
		try (var escopo = this.correlacao.abrir(id.toString(), acesso.usuarioId().toString())) {
			this.maquina.registrarCriacao(id, status, "usuario");
			if (tipo == TipoEntrada.TEXTO) {
				this.outbox.registrar(id, EventoOutbox.REGRA_SUBMETIDA, new RegraSubmetidaDto(id, "texto",
						CompetenciasPublicadas.TODAS, null, null, submissaoId, null));
			}
		}
		return new JobCriado(id, status.paraColuna());
	}

	@Override
	public boolean concluirTranscricao(UUID jobId, UUID submissaoId) {
		return encerrarTranscricao(jobId, submissaoId, true);
	}

	@Override
	public boolean falharTranscricao(UUID jobId, UUID submissaoId) {
		return encerrarTranscricao(jobId, submissaoId, false);
	}

	private boolean encerrarTranscricao(UUID jobId, UUID submissaoId, boolean sucesso) {
		var observacao = new ObservacaoTranscricao(jobId, sucesso ? "concluir" : "falhar");
		TransactionSynchronizationManager.registerSynchronization(observacao);
		try (var escopo = this.correlacao.abrir(jobId.toString(), null)) {
			var encontrados = this.repository.buscarContextoComTrava(jobId);
			if (encontrados.isEmpty()) {
				observacao.resultado = "descartada";
				return false;
			}
			var job = encontrados.getFirst();
			if (job.status() != JobStatus.AGUARDANDO_TRANSCRICAO || !"voz".equals(job.origem())
					|| !submissaoId.equals(job.submissaoId())) {
				observacao.resultado = "descartada";
				return false;
			}
			JobStatus destino = sucesso ? JobStatus.GERANDO_REGRA : JobStatus.ERRO;
			String motivo = sucesso ? null : MotivoDaParada.FALHA_NA_TRANSCRICAO;
			JobStatus origem = this.maquina.transicionar(jobId, destino, "sistema", motivo);
			if (sucesso) {
				this.outbox.registrar(jobId, EventoOutbox.REGRA_SUBMETIDA, new RegraSubmetidaDto(jobId, "voz",
						job.competencias(), job.orcamento(), job.metaVenda(), submissaoId, null));
			}
			var estado = EventoEstadoDto.transicao(jobId, origem, destino,
					MotivoDaParada.razaoLocalizada(destino, motivo));
			observacao.anuncio = destino.terminal() ? EventoSse.ultimo("estado", estado)
					: EventoSse.de("estado", estado);
			observacao.resultado = "aplicada";
			return true;
		}
	}

	/**
	 * Mede a chamada até o desfecho da transação que a contém, inclusive rollback, e só
	 * depois do commit anuncia a transição no stream SSE.
	 */
	private final class ObservacaoTranscricao implements TransactionSynchronization {

		private final UUID jobId;

		private final String operacao;

		private final long inicio = System.nanoTime();

		private String resultado = "rollback";

		private @Nullable EventoSse anuncio;

		private ObservacaoTranscricao(UUID jobId, String operacao) {
			this.jobId = jobId;
			this.operacao = operacao;
		}

		@Override
		public void afterCompletion(int status) {
			String desfecho = status == STATUS_COMMITTED ? this.resultado : "rollback";
			metrics.transcricaoTransicao(this.operacao, desfecho)
				.record(System.nanoTime() - this.inicio, TimeUnit.NANOSECONDS);
			try (var escopo = correlacao.abrir(this.jobId.toString(), null)) {
				log.atInfo()
					.addKeyValue("operacao", this.operacao)
					.addKeyValue("resultado", desfecho)
					.log("transição após transcrição finalizada");
				EventoSse anunciar = this.anuncio;
				if (status == STATUS_COMMITTED && anunciar != null) {
					emissores.emitir(this.jobId, anunciar);
				}
			}
		}

	}

}
