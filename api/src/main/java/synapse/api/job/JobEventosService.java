package synapse.api.job;

import java.sql.Timestamp;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

import org.jspecify.annotations.Nullable;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import synapse.api.core.outbox.EventoOutbox;
import synapse.api.core.outbox.Outbox;
import synapse.api.job.JobRepository.ContextoDoJob;
import synapse.api.job.JobRepository.ExtracaoDaRegra;
import synapse.api.job.VersoesDaRegra.VersaoRegra;

@Service
class JobEventosService {

	// Mantém a identificação operacional do logger anterior à consolidação.
	private static final Logger log = LoggerFactory.getLogger("synapse.api.job.SimulacaoConcluidaService");

	private static final String ATOR = "evento";

	private static final String STATUS_INICIADA = "iniciada";

	private static final String STATUS_ERRO = "erro";

	private final JobRepository repository;

	private final MaquinaDeEstadosDoJob maquina;

	private final VersoesDaRegra versoes;

	private final Outbox outbox;

	JobEventosService(JobRepository repository, MaquinaDeEstadosDoJob maquina, VersoesDaRegra versoes, Outbox outbox) {
		this.repository = repository;
		this.maquina = maquina;
		this.versoes = versoes;
		this.outbox = outbox;
	}

	/**
	 * O evento {@code estado} da transição aplicada, ou {@code null} quando a combinação
	 * não move o job ou ele já saiu de {@code gerando_regra}.
	 */
	@Transactional
	@Nullable EventoEstadoDto aplicarEtapaAlterada(UUID jobId, EtapaDoGrafo etapa, String status) {
		if (etapa == EtapaDoGrafo.DELEGACAO_WORKER && STATUS_INICIADA.equals(status)) {
			return avancarDeGerandoRegra(jobId, JobStatus.SIMULANDO, null, null);
		}
		if (STATUS_ERRO.equals(status)) {
			return avancarDeGerandoRegra(jobId, JobStatus.ERRO, MotivoDaParada.falhaNaEtapa(etapa),
					MotivoDaParada.FALHA_ANTES_DA_SIMULACAO);
		}
		return null;
	}

	private @Nullable EventoEstadoDto avancarDeGerandoRegra(UUID jobId, JobStatus destino,
			@Nullable String motivoDaTrilha, @Nullable String razao) {
		boolean avancou = this.maquina.avancarSeEm(jobId, JobStatus.GERANDO_REGRA, destino, ATOR, motivoDaTrilha);
		return avancou ? EventoEstadoDto.transicao(jobId, JobStatus.GERANDO_REGRA, destino, razao) : null;
	}

	@Transactional
	void registrarNoConcluido(UUID jobId, UUID eventoId, EtapaDoGrafo no, NoConcluidoDto evento) {
		this.repository.exigirJobExistente(jobId);

		UUID simulacaoId = evento.simulacao_id();
		UUID regraId = evento.regra_id();
		UUID codigoGeradoId = evento.codigo_gerado_id();
		if (no == EtapaDoGrafo.GERACAO_CODIGO && regraId != null && codigoGeradoId != null) {
			simulacaoId = this.repository.registrarSimulacao(jobId, regraId, codigoGeradoId, simulacaoId,
					Objects.requireNonNull(evento.concluido_em()));
		}

		this.repository.inserirTrilhaNo(eventoId, jobId, simulacaoId, no, evento);
	}

	@Transactional
	@Nullable DesfechoAplicado concluirSimulacao(UUID jobId, UUID resultadoId, DesfechoDaSimulacao desfecho) {
		return aplicarDesfecho(jobId, resultadoId, desfecho);
	}

	private @Nullable DesfechoAplicado aplicarDesfecho(UUID jobId, UUID resultadoId, DesfechoDaSimulacao desfecho) {
		// A trava também protege o ciclo atual contra resultados de versões anteriores.
		this.repository.bloquearJob(jobId);
		Boolean atual = this.repository.resultadoPertenceAVersaoAtual(jobId, resultadoId);
		if (!Boolean.TRUE.equals(atual)) {
			return null;
		}
		boolean avancouDeGerandoRegra = this.maquina.avancarSeEm(jobId, JobStatus.GERANDO_REGRA, JobStatus.SIMULANDO,
				"evento", "simulacao_concluida_antecipada");
		JobStatus origem = this.maquina.transicionar(jobId, desfecho.destino(), "evento", desfecho.motivoDaTrilha());
		UUID simulacaoId = amarrarResultado(jobId, resultadoId);
		return new DesfechoAplicado(origem, simulacaoId, avancouDeGerandoRegra);
	}

	/**
	 * Aponta {@code simulacoes.resultado_id} para a linha que o worker gravou, casando
	 * pelo {@code codigo_gerado_id} que a simulação já registrou no momento em que o
	 * código foi executado. Zero linhas casadas acontece quando {@code no-concluido} do
	 * nó {@code geracao_codigo} ({@link JobEventosService}) ainda não criou a linha em
	 * {@code simulacoes} - as duas filas não têm ordem entre si. Nesse caso a transição
	 * segue do mesmo jeito, o evento {@code resultado} do SSE não sai, e é
	 * {@link JobEventosService#registrarNoConcluido} quem amarra o resultado ao chegar
	 * depois (o subselect por {@code codigo_gerado_id} encontra o resultado já gravado).
	 * O {@code resultado_id IS NULL} e o índice único {@code uq_simulacoes_resultado_id}
	 * são a segunda barreira de idempotência, abaixo da que a máquina de estados já dá.
	 */
	private @Nullable UUID amarrarResultado(UUID jobId, UUID resultadoId) {
		List<UUID> amarradas = this.repository.vincularResultado(jobId, resultadoId);
		if (amarradas.isEmpty()) {
			log.atWarn()
				.addKeyValue("resultado_id", resultadoId)
				.log("nenhuma simulação amarrada ao resultado; evento \"resultado\" não será emitido");
			return null;
		}
		return amarradas.getFirst();
	}

	record DesfechoAplicado(JobStatus origem, @Nullable UUID simulacaoId, boolean avancouDeGerandoRegra) {
	}

	@Transactional
	@Nullable SugestaoAplicada aplicarSugestaoAdaptacao(UUID jobId, UUID regraOrigemId, UUID resultadoId,
			RepresentacaoRegraDto representacao) {
		var percentual = representacao.nucleo().percentual();
		if (percentual == null || percentual.signum() <= 0) {
			return null;
		}
		List<ContextoDoJob> contextos = this.repository.buscarContextoComTrava(jobId);
		if (contextos.isEmpty()) {
			return null;
		}
		ContextoDoJob contexto = contextos.getFirst();
		if (!List.of(JobStatus.GERANDO_REGRA, JobStatus.SIMULANDO, JobStatus.SIMULACAO_INVIAVEL)
			.contains(contexto.status())) {
			return null;
		}
		String hash = HashDaRegra.calcular(representacao);
		Boolean valida = this.repository.sugestaoElegivel(jobId, regraOrigemId, resultadoId, hash, percentual,
				representacao);
		if (!Boolean.TRUE.equals(valida)) {
			return null;
		}
		// As filas não têm ordem entre si: a proposta pode anteceder o evento do
		// resultado.
		DesfechoAplicado desfechoOriginal = null;
		if (contexto.status() != JobStatus.SIMULACAO_INVIAVEL) {
			desfechoOriginal = aplicarDesfecho(jobId, resultadoId, DesfechoDaSimulacao.INVIAVEL);
			if (desfechoOriginal == null) {
				return null;
			}
			if (desfechoOriginal.simulacaoId() == null) {
				// no-concluido pode ter vinculado o resultado antes de sua notificação.
				List<UUID> simulacoes = this.repository.buscarSimulacaoPorResultado(jobId, resultadoId);
				if (!simulacoes.isEmpty()) {
					desfechoOriginal = new DesfechoAplicado(desfechoOriginal.origem(), simulacoes.getFirst(),
							desfechoOriginal.avancouDeGerandoRegra());
				}
			}
		}
		JobStatus origem = this.maquina.transicionar(jobId, JobStatus.GERANDO_REGRA, "evento",
				"sugestao_adaptacao_proposta");
		Instant agora = Instant.now().truncatedTo(ChronoUnit.MICROS);
		VersaoRegra versao = this.versoes.resolver(jobId, representacao, hash, "sugestao_adaptacao", regraOrigemId,
				Timestamp.from(agora), agora);
		this.outbox.registrar(jobId, EventoOutbox.REGRA_SUBMETIDA, contexto.regraSubmetida(versao.id()));
		return new SugestaoAplicada(origem, versao, desfechoOriginal);
	}

	record SugestaoAplicada(JobStatus origem, VersaoRegra versao, @Nullable DesfechoAplicado desfechoOriginal) {
	}

	/**
	 * Grava a versão raiz de um job de texto ou voz a partir da extração do codegen e
	 * registra o {@code regra-submetida} que reabre o ciclo, na mesma transação. Não move
	 * o job: ele segue em {@code gerando_regra}. A trava do job serializa duas entregas
	 * da mesma extração, e a segunda encontra a versão já gravada.
	 */
	@Transactional
	ExtracaoAplicada aplicarRegraExtraida(UUID jobId, UUID submissaoId, UUID extracaoId) {
		List<ContextoDoJob> contextos = this.repository.buscarContextoComTrava(jobId);
		if (contextos.isEmpty()) {
			return ExtracaoAplicada.descartada(DesfechoDaExtracao.JOB_INEXISTENTE);
		}
		ContextoDoJob contexto = contextos.getFirst();
		if (!submissaoId.equals(contexto.submissaoId())) {
			return ExtracaoAplicada.descartada(DesfechoDaExtracao.SUBMISSAO_DIVERGENTE);
		}
		List<ExtracaoDaRegra> extracoes = this.repository.buscarExtracao(extracaoId);
		if (extracoes.isEmpty()) {
			return ExtracaoAplicada.descartada(DesfechoDaExtracao.EXTRACAO_INEXISTENTE);
		}
		ExtracaoDaRegra extracao = extracoes.getFirst();
		if (!extracao.jobId().equals(jobId) || !extracao.submissaoId().equals(submissaoId)) {
			return ExtracaoAplicada.descartada(DesfechoDaExtracao.EXTRACAO_DIVERGENTE);
		}
		RepresentacaoRegraDto representacao = RepresentacaoExtraida.validada(extracao.representacao());
		if (representacao == null) {
			return ExtracaoAplicada.descartada(DesfechoDaExtracao.REPRESENTACAO_INVALIDA);
		}

		String hash = HashDaRegra.calcular(representacao);
		List<VersaoRegra> jaGravada = this.repository.buscarRegraPorHash(jobId, hash);
		if (!jaGravada.isEmpty() && VersoesDaRegra.ORIGEM_EXTRACAO.equals(jaGravada.getFirst().origem())) {
			return new ExtracaoAplicada(DesfechoDaExtracao.REENTREGA, jaGravada.getFirst().id());
		}
		if (contexto.status() != JobStatus.GERANDO_REGRA) {
			return ExtracaoAplicada.descartada(DesfechoDaExtracao.ESTADO_INCOMPATIVEL);
		}
		Integer maiorVersao = this.repository.buscarMaiorVersao(jobId);
		if (maiorVersao != null && maiorVersao > 0) {
			return ExtracaoAplicada.descartada(DesfechoDaExtracao.VERSAO_EXISTENTE);
		}

		Instant agora = Instant.now().truncatedTo(ChronoUnit.MICROS);
		VersaoRegra versao = this.versoes.resolverExtracao(jobId, extracaoId, hash, Timestamp.from(agora), agora);
		this.outbox.registrar(jobId, EventoOutbox.REGRA_SUBMETIDA, contexto.regraSubmetida(versao.id()));
		return new ExtracaoAplicada(DesfechoDaExtracao.PERSISTIDA, versao.id());
	}

	/**
	 * {@code regraId} existe quando há versão da extração: gravada agora ou reentregue.
	 */
	record ExtracaoAplicada(DesfechoDaExtracao desfecho, @Nullable UUID regraId) {

		static ExtracaoAplicada descartada(DesfechoDaExtracao desfecho) {
			return new ExtracaoAplicada(desfecho, null);
		}

	}

	/**
	 * Desfecho do consumo de {@code regra-extraida}: o {@code resultado} e o
	 * {@code motivo} que vão para log e métrica, de conjunto fechado. Todo descarte é
	 * definitivo - a reentrega da mesma mensagem não o corrigiria.
	 */
	enum DesfechoDaExtracao {

		PERSISTIDA("persistida", "nenhum"),

		REENTREGA("duplicada", "reentrega"),

		EVENTO_INVALIDO("descartada", "evento_invalido"),

		JOB_INEXISTENTE("descartada", "job_inexistente"),

		SUBMISSAO_DIVERGENTE("descartada", "submissao_divergente"),

		EXTRACAO_INEXISTENTE("descartada", "extracao_inexistente"),

		EXTRACAO_DIVERGENTE("descartada", "extracao_divergente"),

		REPRESENTACAO_INVALIDA("descartada", "representacao_invalida"),

		ESTADO_INCOMPATIVEL("descartada", "estado_incompativel"),

		VERSAO_EXISTENTE("descartada", "versao_existente");

		private final String resultado;

		private final String motivo;

		DesfechoDaExtracao(String resultado, String motivo) {
			this.resultado = resultado;
			this.motivo = motivo;
		}

		String resultado() {
			return this.resultado;
		}

		String motivo() {
			return this.motivo;
		}

	}

}
