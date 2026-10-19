package synapse.api.job;

import java.time.Duration;
import java.util.Objects;
import java.util.UUID;

import org.jspecify.annotations.Nullable;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import tools.jackson.databind.JsonNode;

import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.amqp.AmqpRejectAndDontRequeueException;
import org.springframework.amqp.ImmediateRequeueAmqpException;
import org.springframework.amqp.core.Message;
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
import synapse.api.job.JobEventosService.FimDaIteracao;
import synapse.api.job.JobEventosService.SugestaoAplicada;

/** Valida o corpo antes do DTO e só anuncia aplicação depois do commit do serviço. */
@Component
class CorrecaoPropostaConsumidor {

	private static final Logger log = LoggerFactory.getLogger(CorrecaoPropostaConsumidor.class);

	private final CorrecaoPropostaService servico;

	private final CorrelationContext correlacao;

	private final AppMetrics metricas;

	private final EmissoresSse emissores;

	CorrecaoPropostaConsumidor(CorrecaoPropostaService servico, CorrelationContext correlacao, AppMetrics metricas,
			EmissoresSse emissores) {
		this.servico = servico;
		this.correlacao = correlacao;
		this.metricas = metricas;
		this.emissores = emissores;
	}

	@RabbitListener(id = "correcaoProposta", queues = RabbitTopologyConfig.CORRECAO_PROPOSTA,
			containerFactory = "correcaoPropostaContainerFactory")
	void receber(Message mensagem) {
		long inicio = System.nanoTime();
		JsonNode corpo = ValidacaoCorrecaoProposta.ler(mensagem.getBody());
		UUID jobId = ValidacaoCorrecaoProposta.jobId(corpo);
		String resultado = "falha";
		String motivo = "processamento_falhou";
		boolean confirmado = false;
		UUID regraId = null;
		UUID rodadaId = null;
		UUID submissaoId = null;
		try (var escopo = this.correlacao.abrir(jobId == null ? null : jobId.toString(), null)) {
			this.metricas.jobRuns(RabbitTopologyConfig.CORRECAO_PROPOSTA).increment();
			log.atInfo().log("consumo de correcao-proposta iniciado");
			try {
				CorrecaoPropostaDto evento = ValidacaoCorrecaoProposta.validar(corpo);
				submissaoId = evento.submissao_id();
				var aplicada = this.servico.aplicar(evento);
				confirmado = true;
				resultado = aplicada.resultado();
				motivo = aplicada.motivo();
				regraId = aplicada.regraId();
				rodadaId = aplicada.rodadaId();
				if ("aplicada".equals(resultado)) {
					this.emissores.emitir(evento.job_id(),
							EventoSse.de("estado", EventoEstadoDto.transicao(evento.job_id(),
									JobStatus.AGUARDANDO_CONFIRMACAO_PARAMETROS, JobStatus.GERANDO_REGRA, null)));
				}
			}
			catch (AmqpRejectAndDontRequeueException ex) {
				resultado = "invalida";
				motivo = "contrato_invalido";
				this.metricas.jobFailures(RabbitTopologyConfig.CORRECAO_PROPOSTA).increment();
				throw ex;
			}
			catch (RuntimeException ex) {
				if (!confirmado)
					resultado = "falha";
				motivo = confirmado ? "notificacao_falhou" : "processamento_falhou";
				this.metricas.jobFailures(RabbitTopologyConfig.CORRECAO_PROPOSTA).increment();
				throw new ImmediateRequeueAmqpException("correcao-proposta não confirmada");
			}
			finally {
				this.metricas.correcaoProposta(resultado).increment();
				this.metricas.jobDuration(RabbitTopologyConfig.CORRECAO_PROPOSTA)
					.record(Duration.ofNanos(System.nanoTime() - inicio));
				log.atLevel(switch (resultado) {
					case "aplicada", "sem_alteracao", "duplicada" -> org.slf4j.event.Level.INFO;
					default -> org.slf4j.event.Level.WARN;
				})
					.addKeyValue("resultado", resultado)
					.addKeyValue("motivo", motivo)
					.addKeyValue("submissao_id", submissaoId)
					.addKeyValue("regra_id", regraId)
					.addKeyValue("rodada_id", rodadaId)
					.log("consumo de correcao-proposta encerrado");
			}
		}
	}

}

/** Consome etapas e anuncia somente os efeitos confirmados pelo serviço transacional. */
@Component
class EtapaAlteradaConsumidor {

	private static final Logger log = LoggerFactory.getLogger(EtapaAlteradaConsumidor.class);

	private final JobEventosService servico;

	private final EmissoresSse emissores;

	private final CorrelationContext correlacao;

	private final AppMetrics metricas;

	EtapaAlteradaConsumidor(JobEventosService servico, EmissoresSse emissores, CorrelationContext correlacao,
			AppMetrics metricas) {
		this.servico = servico;
		this.emissores = emissores;
		this.correlacao = correlacao;
		this.metricas = metricas;
	}

	@RabbitListener(queues = RabbitTopologyConfig.ETAPA_ALTERADA)
	void receber(EtapaAlteradaDto evento) {
		UUID jobId = evento.job_id();
		long inicio = System.nanoTime();
		String resultado = "falha";
		try (var escopo = this.correlacao.abrir(jobId == null ? null : jobId.toString(), null)) {
			EtapaDoGrafo etapa = EtapaDoGrafo.deEvento(evento.etapa());
			String status = evento.status();
			boolean correcao = "aguardando_correcao".equals(status)
					|| (etapa == EtapaDoGrafo.EXTRACAO_PARAMETROS && "erro".equals(status));
			if (jobId == null || etapa == null || !StringUtils.hasText(status)) {
				resultado = "descartada";
				if (correcao) {
					registrar(new EtapaAplicada(DesfechoCorrecao.EVENTO_INVALIDO, null, evento.regra_id(), null, 0,
							null));
				}
				else {
					log.atWarn().log("etapa-alterada inválida; evento descartado");
				}
				return;
			}
			EtapaAplicada aplicada;
			try {
				aplicada = this.servico.aplicarEtapaAlterada(jobId, etapa, status, evento.causa(), evento.regra_id(),
						evento.conflitos(), evento.submissao_id());
			}
			catch (org.springframework.dao.DataAccessException
					| org.springframework.transaction.TransactionException ex) {
				log.atWarn()
					.addKeyValue("resultado", "falha")
					.addKeyValue("regra_id", evento.regra_id())
					.addKeyValue("submissao_id", evento.submissao_id())
					.addKeyValue("classe_falha", "banco")
					.log("falha no consumo de etapa-alterada; mensagem será reentregue");
				throw new FalhaPersistenciaEtapaException();
			}
			resultado = aplicada.desfecho().resultado();
			if (aplicada.desfecho() != DesfechoCorrecao.COMUM) {
				if (correcao) {
					registrar(aplicada);
				}
				else {
					log.atWarn().log("etapa-alterada de job desconhecido; evento descartado");
				}
			}
			if (!aplicada.emitirEtapa()) {
				return;
			}
			JsonNode conflitos = aplicada.desfecho() == DesfechoCorrecao.RODADA_ABERTA ? evento.conflitos() : null;
			this.emissores.emitir(jobId,
					EventoSse.de("etapa", new EventoEtapaDto(jobId, etapa.paraEvento(), status, conflitos)));
			EventoEstadoDto transicao = aplicada.transicao();
			if (transicao != null) {
				boolean terminal = JobStatus.deColuna(transicao.status()).terminal();
				this.emissores.emitir(jobId,
						terminal ? EventoSse.ultimo("estado", transicao) : EventoSse.de("estado", transicao));
			}
			registrarFimDaIteracao(etapa, aplicada.fim());
			if (aplicada.desfecho() == DesfechoCorrecao.COMUM) {
				log.atDebug().addKeyValue("etapa", etapa.paraEvento()).log("etapa repassada ao stream SSE");
			}
		}
		finally {
			this.metricas.etapaAlteradaDuracao(resultado).record(Duration.ofNanos(System.nanoTime() - inicio));
		}
	}

	private void registrar(EtapaAplicada aplicada) {
		DesfechoCorrecao desfecho = aplicada.desfecho();
		var registro = "descartada".equals(desfecho.resultado()) ? log.atWarn() : log.atInfo();
		registro.addKeyValue("regra_id", aplicada.regraId())
			.addKeyValue("rodada_id", aplicada.rodadaId())
			.addKeyValue("resultado", desfecho.resultado())
			.addKeyValue("numero_conflitos", aplicada.numeroConflitos())
			.addKeyValue("motivo_descarte", desfecho.motivo())
			.log("etapa-alterada de correção processada");
		this.metricas.etapaAlteradaCorrecao(desfecho.resultado()).increment();
	}

	private void registrarFimDaIteracao(EtapaDoGrafo etapa, @Nullable FimDaIteracao fim) {
		if (fim == null) {
			return;
		}
		this.metricas.fimDaIteracaoDaTaxa(fim.causa(), fim.resultado()).increment();
		if (fim == FimDaIteracao.SEM_ALTERNATIVA_SEM_EFEITO) {
			log.atInfo()
				.addKeyValue("etapa", etapa.paraEvento())
				.log("sem_alternativa sem iteração em curso; estado do job mantido");
			return;
		}
		log.atInfo()
			.addKeyValue("etapa", etapa.paraEvento())
			.addKeyValue("causa", fim.causa())
			.log(fim == FimDaIteracao.FALHA ? "tentativas de taxa nova interrompidas por falha; job em erro"
					: "tentativas de taxa nova encerradas sem alternativa; job inviável");
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

	private final EmissoresSse emissores;

	private final CorrelationContext correlacao;

	NoConcluidoConsumidor(JobEventosService servico, EmissoresSse emissores, CorrelationContext correlacao) {
		this.servico = servico;
		this.emissores = emissores;
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

			JobEventosService.BuscaMetaAnunciada busca;
			try {
				busca = this.servico.registrarNoConcluido(jobId, eventoId, no, evento);
			}
			catch (EmptyResultDataAccessException ex) {
				log.atWarn().setCause(ex).log("no-concluido de job desconhecido; evento descartado");
				return;
			}
			log.atDebug().addKeyValue("no", no.paraEvento()).log("no-concluido gravado na trilha");
			String status = busca.status();
			if (status != null) {
				// Depois do commit: quem buscar o job agora encontra o campo, ou não o
				// encontra mais.
				this.emissores.emitir(jobId, EventoSse.de("etapa",
						new EventoEtapaDto(jobId, EtapaDoGrafo.SUGESTAO_ADAPTACAO.paraEvento(), status)));
				log.atInfo().addKeyValue("status", status).log("busca da meta maior anunciada");
			}
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

	private static final String INVALIDA = "invalida";

	private static final String DESFECHO_DESCONHECIDO = "desconhecido";

	private final JobEventosService servico;

	private final EmissoresSse emissores;

	private final CorrelationContext correlacao;

	private final AppMetrics metricas;

	SimulacaoConcluidaConsumidor(JobEventosService servico, EmissoresSse emissores, CorrelationContext correlacao,
			AppMetrics metricas) {
		this.servico = servico;
		this.emissores = emissores;
		this.correlacao = correlacao;
		this.metricas = metricas;
	}

	@RabbitListener(queues = RabbitTopologyConfig.SIMULACAO_CONCLUIDA_API)
	void receber(SimulacaoConcluidaDto evento) {
		UUID jobId = evento.job_id();
		UUID resultadoId = evento.resultado_id();
		if (jobId == null || resultadoId == null) {
			contar(null, INVALIDA);
			log.atWarn().log("simulacao-concluida sem job_id ou resultado_id; evento descartado");
			return;
		}

		try (var escopo = this.correlacao.abrir(jobId.toString(), null)) {
			if ("busca_meta".equals(evento.proposito())) {
				this.metricas.execucaoCandidataConsumida().increment();
				log.atInfo()
					.addKeyValue("resultado_id", resultadoId)
					.log("execução candidata consumida; simulação vigente e estado preservados");
				return;
			}
			if (evento.proposito() != null && !"simulacao".equals(evento.proposito())) {
				contar(null, INVALIDA);
				log.atWarn().log("simulacao-concluida com propósito desconhecido; evento descartado");
				return;
			}
			DesfechoDaSimulacao desfecho = DesfechoDaSimulacao.de(evento.status(), evento.veredito());
			if (desfecho == null) {
				contar(null, INVALIDA);
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
				contar(desfecho, "estado_incompativel");
				log.atWarn()
					.addKeyValue("resultado_id", resultadoId)
					.addKeyValue("desfecho", desfecho.paraMetrica())
					.setCause(ex)
					.log("simulacao-concluida não aplicada; job fora do estado de origem esperado (reentrega ou evento fora de ordem)");
				return;
			}

			if (aplicado == null) {
				contar(desfecho, "versao_anterior");
				log.atWarn()
					.addKeyValue("resultado_id", resultadoId)
					.addKeyValue("desfecho", desfecho.paraMetrica())
					.log("resultado descartado: não pertence à versão atual do job");
				return;
			}
			if (aplicado.intermediario()) {
				// O usuário não vê a alternativa que não coube: nem "resultado" nem
				// "estado" saem até o codegen propor a próxima ou anunciar o fim.
				contar(desfecho, "intermediaria");
				log.atInfo()
					.addKeyValue("resultado_id", resultadoId)
					.log("resultado inviável de alternativa registrado; job aguarda a próxima tentativa ou o fim da iteração");
				return;
			}
			if (aplicado.avancouDeGerandoRegra()) {
				this.emissores.emitir(jobId, EventoSse.de("estado",
						EventoEstadoDto.transicao(jobId, JobStatus.GERANDO_REGRA, JobStatus.SIMULANDO, null)));
			}
			contar(desfecho, "aplicada");

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
			log.atInfo()
				.addKeyValue("resultado_id", resultadoId)
				.addKeyValue("desfecho", desfecho.paraMetrica())
				.addKeyValue("status", destino.paraColuna())
				.log("simulacao-concluida aplicada");
		}
	}

	private void contar(@Nullable DesfechoDaSimulacao desfecho, String resultado) {
		String rotulo = (desfecho != null) ? desfecho.paraMetrica() : DESFECHO_DESCONHECIDO;
		this.metricas.simulacaoConcluidaConsumida(rotulo, resultado).increment();
	}

}

/**
 * Consome {@code sugestao-adaptacao-proposta}: grava a versão alternativa com a
 * {@code tentativa} informada e reabre o ciclo do codegen
 * ({@link JobEventosService#aplicarSugestaoAdaptacao}). A proposta pode partir da regra
 * original ou da alternativa anterior que não coube; a reentrega encontra a versão já
 * criada e é descartada. Só a regra original tem desfecho inviável anunciado ao usuário:
 * a alternativa intermediária não sai no SSE. Nada da regra entra em log.
 */
@Component
class SugestaoAdaptacaoConsumidor {

	private static final Logger log = LoggerFactory.getLogger(SugestaoAdaptacaoConsumidor.class);

	private static final int PRIMEIRA_TENTATIVA = 1;

	private static final int ULTIMA_TENTATIVA = 3;

	private static final String TENTATIVA_AUSENTE = "ausente";

	private static final String TENTATIVA_INVALIDA = "invalida";

	private final JobEventosService servico;

	private final EmissoresSse emissores;

	private final CorrelationContext correlacao;

	private final AppMetrics metricas;

	SugestaoAdaptacaoConsumidor(JobEventosService servico, EmissoresSse emissores, CorrelationContext correlacao,
			AppMetrics metricas) {
		this.servico = servico;
		this.emissores = emissores;
		this.correlacao = correlacao;
		this.metricas = metricas;
	}

	@RabbitListener(queues = RabbitTopologyConfig.SUGESTAO_ADAPTACAO_PROPOSTA)
	void receber(SugestaoAdaptacaoPropostaDto evento) {
		UUID jobId = evento.job_id();
		UUID regraOrigemId = evento.regra_origem_id();
		UUID resultadoId = evento.resultado_id();
		RepresentacaoRegraDto representacao = evento.representacao();
		Integer tentativa = evento.tentativa();
		String rotulo = rotuloDaTentativa(tentativa);
		try (var escopo = this.correlacao.abrir(jobId == null ? null : jobId.toString(), null)) {
			if (jobId == null || regraOrigemId == null || resultadoId == null || representacao == null
					|| representacao.nucleo() == null || representacao.especificacoes() == null
					|| TENTATIVA_INVALIDA.equals(rotulo)) {
				contar(rotulo, "invalida");
				log.atWarn()
					.addKeyValue("tentativa", tentativa)
					.log("sugestao-adaptacao-proposta incompleta ou fora do contrato; evento descartado");
				return;
			}
			SugestaoAplicada aplicada;
			try {
				aplicada = this.servico.aplicarSugestaoAdaptacao(jobId, regraOrigemId, resultadoId, representacao,
						tentativa);
			}
			catch (TransicaoDeStatusInvalidaException ex) {
				contar(rotulo, "estado_incompativel");
				log.atWarn()
					.addKeyValue("tentativa", tentativa)
					.setCause(ex)
					.log("sugestao-adaptacao-proposta não aplicada; job fora do estado de origem esperado (reentrega ou evento fora de ordem)");
				return;
			}
			catch (RuntimeException ex) {
				contar(rotulo, "falha");
				throw ex;
			}

			if (aplicada == null) {
				contar(rotulo, "descartada");
				log.atWarn()
					.addKeyValue("resultado_id", resultadoId)
					.addKeyValue("tentativa", tentativa)
					.log("sugestão descartada: origem inválida ou proposta já aplicada");
				return;
			}
			contar(rotulo, "aplicada");

			var daOrigem = aplicada.desfechoDaOrigem();
			if (daOrigem != null) {
				if (daOrigem.avancouDeGerandoRegra()) {
					this.emissores.emitir(jobId, EventoSse.de("estado",
							EventoEstadoDto.transicao(jobId, JobStatus.GERANDO_REGRA, JobStatus.SIMULANDO, null)));
				}
				if (!daOrigem.intermediario()) {
					UUID simulacaoId = daOrigem.simulacaoId();
					if (simulacaoId != null) {
						this.emissores.emitir(jobId, EventoSse.de("resultado",
								new EventoResultadoDto(jobId, simulacaoId, "sucesso", "inviavel")));
					}
					this.emissores.emitir(jobId,
							EventoSse.de("estado", EventoEstadoDto.transicao(jobId, daOrigem.origem(),
									JobStatus.SIMULACAO_INVIAVEL, DesfechoDaSimulacao.INVIAVEL.razaoLocalizada())));
				}
			}

			this.emissores.emitir(jobId, EventoSse.de("estado",
					EventoEstadoDto.transicao(jobId, aplicada.origem(), JobStatus.GERANDO_REGRA, null)));
			log.atInfo()
				.addKeyValue("regra_id", aplicada.versao().id())
				.addKeyValue("versao", aplicada.versao().versao())
				.addKeyValue("tentativa", tentativa)
				.log("sugestao-adaptacao-proposta aplicada; ciclo do codegen reaberto");
		}
	}

	/**
	 * A tag da métrica, de conjunto fechado. Fora da faixa do contrato é evento inválido:
	 * a reentrega não o corrigiria.
	 */
	private static String rotuloDaTentativa(@Nullable Integer tentativa) {
		if (tentativa == null) {
			return TENTATIVA_AUSENTE;
		}
		if (tentativa < PRIMEIRA_TENTATIVA || tentativa > ULTIMA_TENTATIVA) {
			return TENTATIVA_INVALIDA;
		}
		return tentativa.toString();
	}

	private void contar(String tentativa, String resultado) {
		this.metricas.sugestaoAdaptacaoConsumida(tentativa, resultado).increment();
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
		contarParametros(aplicada.parametros());
		switch (desfecho) {
			case PERSISTIDA -> log.atInfo()
				.addKeyValue("resultado", desfecho.resultado())
				.addKeyValue("motivo", desfecho.motivo())
				.addKeyValue("regra_id", aplicada.regraId())
				// Quais parâmetros o job recebeu, nunca os valores: orçamento e meta de
				// venda são dado do usuário (`api/AGENTS.md`).
				.addKeyValue("orcamento_extraido", aplicada.parametros().orcamento())
				.addKeyValue("meta_venda_extraida", aplicada.parametros().metaVenda())
				.addKeyValue("periodo_extraido", aplicada.parametros().periodo())
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

	private void contarParametros(ParametrosGravados parametros) {
		if (parametros.orcamento()) {
			this.metricas.parametroDaSimulacaoGravado("orcamento").increment();
		}
		if (parametros.metaVenda()) {
			this.metricas.parametroDaSimulacaoGravado("meta_venda").increment();
		}
		if (parametros.periodo()) {
			this.metricas.parametroDaSimulacaoGravado("competencias").increment();
		}
	}

}
