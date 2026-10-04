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
import synapse.api.job.JobRepository.ContextoAdaptacao;
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
		List<ContextoAdaptacao> contextos = this.repository.buscarContextoAdaptacaoComTrava(jobId, regraOrigemId);
		if (contextos.isEmpty()) {
			return null;
		}
		ContextoAdaptacao contexto = contextos.getFirst();
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
		RegraSubmetidaDto entrada = contexto.entrada();
		this.outbox.registrar(jobId, EventoOutbox.REGRA_SUBMETIDA, new RegraSubmetidaDto(jobId, entrada.origem(),
				entrada.competencias(), entrada.orcamento(), entrada.submissao_id(), versao.id()));
		return new SugestaoAplicada(origem, versao, desfechoOriginal);
	}

	record SugestaoAplicada(JobStatus origem, VersaoRegra versao, @Nullable DesfechoAplicado desfechoOriginal) {
	}

}
