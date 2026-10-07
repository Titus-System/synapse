package synapse.api.job;

import java.time.Duration;
import java.util.Objects;
import java.util.UUID;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import tools.jackson.databind.JsonNode;

import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.dao.EmptyResultDataAccessException;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

import synapse.api.core.logging.CorrelationContext;
import synapse.api.core.messaging.RabbitTopologyConfig;
import synapse.api.core.metrics.AppMetrics;
import synapse.api.core.sse.EmissoresSse;
import synapse.api.core.sse.EventoSse;
import synapse.api.job.JobEventosService.DesfechoAplicado;
import synapse.api.job.JobEventosService.DesfechoDaExtracao;
import synapse.api.job.JobEventosService.ExtracaoAplicada;
import synapse.api.job.JobEventosService.SugestaoAplicada;

/**
 * Consome {@code etapa-alterada}, aplica a transição de estado que a etapa implica
 * ({@link JobEventosService}) e repassa ao stream SSE do job, traduzido para
 * {@link EventoEtapaDto}. Não deduplica por {@code message_id}, que este evento não
 * carrega: uma reentrega encontra o job já fora de {@code gerando_regra} e a transição
 * vira no-op. Nunca lança em entrada inválida: vira descarte com log {@code WARN}, porque
 * uma exceção aqui viraria requeue infinito.
 */
@Component
class EtapaAlteradaConsumidor {

	private static final Logger log = LoggerFactory.getLogger(EtapaAlteradaConsumidor.class);

	private final JobEventosService servico;

	private final EmissoresSse emissores;

	private final CorrelationContext correlacao;

	EtapaAlteradaConsumidor(JobEventosService servico, EmissoresSse emissores, CorrelationContext correlacao) {
		this.servico = servico;
		this.emissores = emissores;
		this.correlacao = correlacao;
	}

	@RabbitListener(queues = RabbitTopologyConfig.ETAPA_ALTERADA)
	void receber(EtapaAlteradaDto evento) {
		UUID jobId = evento.job_id();
		if (jobId == null) {
			log.atWarn().log("etapa-alterada sem job_id; evento descartado");
			return;
		}

		try (var escopo = this.correlacao.abrir(jobId.toString(), null)) {
			EtapaDoGrafo etapa = EtapaDoGrafo.deEvento(evento.etapa());
			String status = evento.status();
			if (etapa == null || !StringUtils.hasText(status)) {
				log.atWarn()
					.addKeyValue("etapa", evento.etapa())
					.log("etapa-alterada com etapa desconhecida; evento descartado");
				return;
			}

			EventoEstadoDto transicao;
			try {
				transicao = this.servico.aplicarEtapaAlterada(jobId, etapa, status);
			}
			catch (EmptyResultDataAccessException ex) {
				log.atWarn().setCause(ex).log("etapa-alterada de job desconhecido; evento descartado");
				return;
			}

			// "etapa" sai antes de "estado" (skill sse): um "estado" terminal fecha o
			// stream.
			this.emissores.emitir(jobId, EventoSse.de("etapa", new EventoEtapaDto(jobId, etapa.paraEvento(), status)));
			if (transicao != null) {
				boolean terminal = JobStatus.deColuna(transicao.status()).terminal();
				this.emissores.emitir(jobId,
						terminal ? EventoSse.ultimo("estado", transicao) : EventoSse.de("estado", transicao));
			}
			log.atDebug().addKeyValue("etapa", etapa.paraEvento()).log("etapa repassada ao stream SSE");
		}
	}

}

/**
 * Consome {@code no-concluido} e grava a trilha de auditoria (T-046): uma linha em
 * {@code trilhas_auditoria} por nó concluído e, no nó {@code geracao_codigo}, a linha em
 * {@code simulacoes} que amarra a versão da regra ao código executado. Deduplica por
 * {@code evento_id} (índice único em {@code trilhas_auditoria}), a chave de idempotência
 * que o próprio contrato prevê. Nunca lança em entrada inválida: vira descarte com log
 * {@code WARN}, porque uma exceção aqui viraria requeue infinito. Não loga
 * {@code conclusao} (`api/AGENTS.md`): nenhum conteúdo de prompt, código ou dataset entra
 * em log.
 */
@Component
class NoConcluidoConsumidor {

	private static final Logger log = LoggerFactory.getLogger(NoConcluidoConsumidor.class);

	private final JobEventosService servico;

	private final CorrelationContext correlacao;

	NoConcluidoConsumidor(JobEventosService servico, CorrelationContext correlacao) {
		this.servico = servico;
		this.correlacao = correlacao;
	}

	@RabbitListener(queues = RabbitTopologyConfig.NO_CONCLUIDO)
	void receber(NoConcluidoDto evento) {
		UUID jobId = evento.job_id();
		if (jobId == null) {
			log.atWarn().log("no-concluido sem job_id; evento descartado");
			return;
		}

		try (var escopo = this.correlacao.abrir(jobId.toString(), null)) {
			UUID eventoId = evento.evento_id();
			EtapaDoGrafo no = EtapaDoGrafo.deEvento(evento.no());
			if (eventoId == null || no == null || evento.concluido_em() == null || evento.conclusao() == null
					|| !temResumo(evento.conclusao())) {
				log.atWarn().addKeyValue("no", evento.no()).log("no-concluido inválido; evento descartado");
				return;
			}

			if (no == EtapaDoGrafo.CONFIRMACAO) {
				// JobService já grava essa linha na mesma transação da
				// confirmação; gravar de novo aqui duplicaria a trilha.
				log.atInfo().log("no-concluido do nó confirmacao descartado; trilha já gravada pela confirmação");
				return;
			}

			try {
				this.servico.registrarNoConcluido(jobId, eventoId, no, evento);
			}
			catch (EmptyResultDataAccessException ex) {
				log.atWarn().setCause(ex).log("no-concluido de job desconhecido; evento descartado");
				return;
			}
			log.atDebug().addKeyValue("no", no.paraEvento()).log("no-concluido gravado na trilha");
		}
	}

	private static boolean temResumo(JsonNode conclusao) {
		JsonNode resumo = conclusao.path("resumo");
		return resumo.isString() && StringUtils.hasText(resumo.asString());
	}

}

@Component
class SimulacaoConcluidaConsumidor {

	private static final Logger log = LoggerFactory.getLogger(SimulacaoConcluidaConsumidor.class);

	private final JobEventosService servico;

	private final EmissoresSse emissores;

	private final CorrelationContext correlacao;

	SimulacaoConcluidaConsumidor(JobEventosService servico, EmissoresSse emissores, CorrelationContext correlacao) {
		this.servico = servico;
		this.emissores = emissores;
		this.correlacao = correlacao;
	}

	@RabbitListener(queues = RabbitTopologyConfig.SIMULACAO_CONCLUIDA_API)
	void receber(SimulacaoConcluidaDto evento) {
		UUID jobId = evento.job_id();
		UUID resultadoId = evento.resultado_id();
		if (jobId == null || resultadoId == null) {
			log.atWarn().log("simulacao-concluida sem job_id ou resultado_id; evento descartado");
			return;
		}

		try (var escopo = this.correlacao.abrir(jobId.toString(), null)) {
			DesfechoDaSimulacao desfecho = DesfechoDaSimulacao.de(evento.status(), evento.veredito());
			if (desfecho == null) {
				log.atWarn()
					.addKeyValue("status", evento.status())
					.log("simulacao-concluida com status ou veredito desconhecido; evento descartado");
				return;
			}

			DesfechoAplicado aplicado;
			try {
				aplicado = this.servico.concluirSimulacao(jobId, resultadoId, desfecho);
			}
			catch (TransicaoDeStatusInvalidaException ex) {
				log.atWarn()
					.addKeyValue("resultado_id", resultadoId)
					.setCause(ex)
					.log("simulacao-concluida não aplicada; job fora do estado de origem esperado (reentrega ou evento fora de ordem)");
				return;
			}

			if (aplicado == null) {
				log.atWarn()
					.addKeyValue("resultado_id", resultadoId)
					.log("resultado descartado: não pertence à versão atual do job");
				return;
			}

			if (aplicado.avancouDeGerandoRegra()) {
				this.emissores.emitir(jobId, EventoSse.de("estado",
						EventoEstadoDto.transicao(jobId, JobStatus.GERANDO_REGRA, JobStatus.SIMULANDO, null)));
			}

			// "resultado" sai antes de "estado" (skill sse): um "estado" terminal fecha
			// o stream, e o que viesse depois se perderia.
			UUID simulacaoId = aplicado.simulacaoId();
			if (simulacaoId != null) {
				// desfecho != null garante que evento.status() não é nulo (ver
				// DesfechoDaSimulacao.de).
				String status = Objects.requireNonNull(evento.status());
				// O veredito só existe no contrato quando status = sucesso (openapi,
				// EventoResultado); um valor presente por engano num status de erro é
				// descartado aqui, na mesma decisão que DesfechoDaSimulacao.de já toma
				// para a transição - nunca repassado cru do evento não confiável.
				String veredito = "sucesso".equals(status) ? evento.veredito() : null;
				this.emissores.emitir(jobId,
						EventoSse.de("resultado", new EventoResultadoDto(jobId, simulacaoId, status, veredito)));
			}

			JobStatus destino = desfecho.destino();
			EventoEstadoDto eventoEstado = EventoEstadoDto.transicao(jobId, aplicado.origem(), destino,
					desfecho.razaoLocalizada());
			EventoSse eventoSse = destino.terminal() ? EventoSse.ultimo("estado", eventoEstado)
					: EventoSse.de("estado", eventoEstado);
			this.emissores.emitir(jobId, eventoSse);
			log.atDebug().addKeyValue("status", destino.paraColuna()).log("simulacao-concluida aplicada");
		}
	}

}

@Component
class SugestaoAdaptacaoConsumidor {

	private static final Logger log = LoggerFactory.getLogger(SugestaoAdaptacaoConsumidor.class);

	private final JobEventosService servico;

	private final EmissoresSse emissores;

	private final CorrelationContext correlacao;

	SugestaoAdaptacaoConsumidor(JobEventosService servico, EmissoresSse emissores, CorrelationContext correlacao) {
		this.servico = servico;
		this.emissores = emissores;
		this.correlacao = correlacao;
	}

	@RabbitListener(queues = RabbitTopologyConfig.SUGESTAO_ADAPTACAO_PROPOSTA)
	void receber(SugestaoAdaptacaoPropostaDto evento) {
		UUID jobId = evento.job_id();
		UUID regraOrigemId = evento.regra_origem_id();
		UUID resultadoId = evento.resultado_id();
		RepresentacaoRegraDto representacao = evento.representacao();
		if (jobId == null || regraOrigemId == null || resultadoId == null || representacao == null
				|| representacao.nucleo() == null || representacao.especificacoes() == null) {
			log.atWarn().log("sugestao-adaptacao-proposta incompleta; evento descartado");
			return;
		}

		try (var escopo = this.correlacao.abrir(jobId.toString(), null)) {
			SugestaoAplicada aplicada;
			try {
				aplicada = this.servico.aplicarSugestaoAdaptacao(jobId, regraOrigemId, resultadoId, representacao);
			}
			catch (TransicaoDeStatusInvalidaException ex) {
				log.atWarn()
					.setCause(ex)
					.log("sugestao-adaptacao-proposta não aplicada; job fora do estado de origem esperado (reentrega ou evento fora de ordem)");
				return;
			}

			if (aplicada == null) {
				log.atWarn()
					.addKeyValue("resultado_id", resultadoId)
					.log("sugestão descartada: origem inválida ou tentativa já realizada");
				return;
			}

			var original = aplicada.desfechoOriginal();
			if (original != null) {
				if (original.avancouDeGerandoRegra()) {
					this.emissores.emitir(jobId, EventoSse.de("estado",
							EventoEstadoDto.transicao(jobId, JobStatus.GERANDO_REGRA, JobStatus.SIMULANDO, null)));
				}
				UUID simulacaoId = original.simulacaoId();
				if (simulacaoId != null) {
					this.emissores.emitir(jobId, EventoSse.de("resultado",
							new EventoResultadoDto(jobId, simulacaoId, "sucesso", "inviavel")));
				}
				this.emissores.emitir(jobId, EventoSse.de("estado", EventoEstadoDto.transicao(jobId, original.origem(),
						JobStatus.SIMULACAO_INVIAVEL, DesfechoDaSimulacao.INVIAVEL.razaoLocalizada())));
			}

			this.emissores.emitir(jobId, EventoSse.de("estado",
					EventoEstadoDto.transicao(jobId, aplicada.origem(), JobStatus.GERANDO_REGRA, null)));
			log.atDebug().addKeyValue("regra_id", aplicada.versao().id()).log("sugestao-adaptacao-proposta aplicada");
		}
	}

}

/**
 * Consome {@code regra-extraida} (T-202): grava a versão raiz de um job de texto ou voz a
 * partir do artefato que o codegen deixou em {@code extracoes_regras} e reabre o ciclo do
 * codegen ({@link JobEventosService#aplicarRegraExtraida}). Sem a versão, o job ficaria
 * em {@code gerando_regra} sem progresso, por isso todo descarte sai em {@code WARN} e na
 * métrica. Descarte confirma a mensagem, porque a reentrega não o corrigiria; falha de
 * banco propaga e vira redelivery. Nada da regra entra em log: só referências.
 */
@Component
class RegraExtraidaConsumidor {

	private static final Logger log = LoggerFactory.getLogger(RegraExtraidaConsumidor.class);

	private static final String FALHA = "falha";

	private final JobEventosService servico;

	private final CorrelationContext correlacao;

	private final AppMetrics metricas;

	RegraExtraidaConsumidor(JobEventosService servico, CorrelationContext correlacao, AppMetrics metricas) {
		this.servico = servico;
		this.correlacao = correlacao;
		this.metricas = metricas;
	}

	@RabbitListener(queues = RabbitTopologyConfig.REGRA_EXTRAIDA)
	void receber(RegraExtraidaDto evento) {
		UUID jobId = evento.job_id();
		try (var escopo = this.correlacao.abrir((jobId != null) ? jobId.toString() : null, null)) {
			log.atInfo().addKeyValue("extracao_id", evento.extracao_id()).log("consumo de regra-extraida iniciado");
			long inicio = System.nanoTime();
			String resultado = FALHA;
			try {
				ExtracaoAplicada aplicada = aplicar(evento);
				resultado = aplicada.desfecho().resultado();
				registrar(aplicada);
			}
			catch (RuntimeException ex) {
				log.atWarn()
					.addKeyValue("classe_falha", ex.getClass().getSimpleName())
					.log("consumo de regra-extraida falhou; a mensagem volta para a fila");
				throw ex;
			}
			finally {
				this.metricas.regraExtraidaDuracao(resultado).record(Duration.ofNanos(System.nanoTime() - inicio));
			}
		}
	}

	private ExtracaoAplicada aplicar(RegraExtraidaDto evento) {
		UUID jobId = evento.job_id();
		UUID submissaoId = evento.submissao_id();
		UUID extracaoId = evento.extracao_id();
		if (jobId == null || submissaoId == null || extracaoId == null) {
			return ExtracaoAplicada.descartada(DesfechoDaExtracao.EVENTO_INVALIDO);
		}
		return this.servico.aplicarRegraExtraida(jobId, submissaoId, extracaoId);
	}

	private void registrar(ExtracaoAplicada aplicada) {
		DesfechoDaExtracao desfecho = aplicada.desfecho();
		this.metricas.regraExtraidaConsumida(desfecho.resultado(), desfecho.motivo()).increment();
		switch (desfecho) {
			case PERSISTIDA -> log.atInfo()
				.addKeyValue("resultado", desfecho.resultado())
				.addKeyValue("motivo", desfecho.motivo())
				.addKeyValue("regra_id", aplicada.regraId())
				.log("regra-extraida persistida; ciclo do codegen reaberto");
			case REENTREGA -> log.atInfo()
				.addKeyValue("resultado", desfecho.resultado())
				.addKeyValue("motivo", desfecho.motivo())
				.addKeyValue("regra_id", aplicada.regraId())
				.log("regra-extraida reentregue; versão já gravada, nada publicado de novo");
			default -> log.atWarn()
				.addKeyValue("resultado", desfecho.resultado())
				.addKeyValue("motivo", desfecho.motivo())
				.log("regra-extraida descartada; job sem nova versão");
		}
	}

}
