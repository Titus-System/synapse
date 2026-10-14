package synapse.api.job;

import java.math.BigDecimal;
import java.sql.Timestamp;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

import org.jspecify.annotations.Nullable;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import tools.jackson.databind.JsonNode;

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

	private static final String STATUS_SEM_ALTERNATIVA = "sem_alternativa";

	private static final String MOTIVO_ANTECIPADA = "simulacao_concluida_antecipada";

	private final JobRepository repository;

	private final MaquinaDeEstadosDoJob maquina;

	private final VersoesDaRegra versoes;

	private final Outbox outbox;

	private final RodadasCorrecaoRepository rodadas;

	JobEventosService(JobRepository repository, MaquinaDeEstadosDoJob maquina, VersoesDaRegra versoes, Outbox outbox,
			RodadasCorrecaoRepository rodadas) {
		this.repository = repository;
		this.maquina = maquina;
		this.versoes = versoes;
		this.outbox = outbox;
		this.rodadas = rodadas;
	}

	@Transactional
	boolean registrarMetaSugerida(MetaVendaSugeridaDto evento) {
		UUID jobId = Objects.requireNonNull(evento.job_id());
		this.repository.bloquearJob(jobId);
		return this.repository.registrarMetaSugerida(evento);
	}

	@Transactional
	EtapaAplicada aplicarEtapaAlterada(UUID jobId, EtapaDoGrafo etapa, String status, @Nullable String causa) {
		return aplicarEtapaAlterada(jobId, etapa, status, causa, null, null);
	}

	@Transactional
	EtapaAplicada aplicarEtapaAlterada(UUID jobId, EtapaDoGrafo etapa, String status, @Nullable String causa,
			@Nullable UUID regraId, @Nullable JsonNode conflitos) {
		return aplicarEtapaAlterada(jobId, etapa, status, causa, regraId, conflitos, null);
	}

	@Transactional
	EtapaAplicada aplicarEtapaAlterada(UUID jobId, EtapaDoGrafo etapa, String status, @Nullable String causa,
			@Nullable UUID regraId, @Nullable JsonNode conflitos, @Nullable UUID submissaoId) {
		List<ContextoDoJob> contextos = this.repository.buscarContextoComTrava(jobId);
		if (contextos.isEmpty()) {
			return resultadoCorrecao(DesfechoCorrecao.JOB_INEXISTENTE, regraId, null, conflitos);
		}
		JobStatus atual = contextos.getFirst().status();
		if ("aguardando_correcao".equals(status)) {
			if (etapa != EtapaDoGrafo.CONFIRMACAO) {
				return resultadoCorrecao(DesfechoCorrecao.EVENTO_INVALIDO, regraId, null, conflitos);
			}
			return pausarPorConflitos(jobId, atual, regraId, conflitos);
		}
		if (etapa == EtapaDoGrafo.EXTRACAO_PARAMETROS && STATUS_ERRO.equals(status)) {
			// Sem referências, só a ausência de histórico permite reconhecer a extração
			// inicial.
			if (regraId != null || submissaoId != null || atual == JobStatus.AGUARDANDO_CONFIRMACAO_PARAMETROS
					|| !this.rodadas.buscarUltima(jobId).isEmpty()) {
				return falharReextracao(jobId, atual, regraId, submissaoId);
			}
		}
		if (etapa == EtapaDoGrafo.SUGESTAO_ADAPTACAO && STATUS_SEM_ALTERNATIVA.equals(status)) {
			EventoEstadoDto encerrada = encerrarIteracao(jobId, atual, JobStatus.SIMULACAO_INVIAVEL,
					MotivoDaParada.SEM_ALTERNATIVA, MotivoDaParada.NENHUMA_TAXA_COUBE);
			return (encerrada != null) ? EtapaAplicada.comum(encerrada, FimDaIteracao.SEM_ALTERNATIVA)
					: EtapaAplicada.comum(null, FimDaIteracao.SEM_ALTERNATIVA_SEM_EFEITO);
		}
		if (STATUS_ERRO.equals(status) && (etapa == EtapaDoGrafo.DECISAO || etapa == EtapaDoGrafo.SUGESTAO_ADAPTACAO)) {
			EventoEstadoDto encerrada = encerrarIteracao(jobId, atual, JobStatus.ERRO,
					MotivoDaParada.falhaNaEtapa(etapa, causa), MotivoDaParada.razaoDaFalha(causa));
			if (encerrada != null) {
				return EtapaAplicada.comum(encerrada, FimDaIteracao.FALHA);
			}
		}
		if (etapa == EtapaDoGrafo.DELEGACAO_WORKER && STATUS_INICIADA.equals(status)) {
			return EtapaAplicada.comum(avancarDeGerandoRegra(jobId, JobStatus.SIMULANDO, null, null));
		}
		if (STATUS_ERRO.equals(status)) {
			return EtapaAplicada.comum(avancarDeGerandoRegra(jobId, JobStatus.ERRO,
					MotivoDaParada.falhaNaEtapa(etapa, causa), MotivoDaParada.razaoDaFalha(causa)));
		}
		return EtapaAplicada.comum(null);
	}

	private EtapaAplicada pausarPorConflitos(UUID jobId, JobStatus atual, @Nullable UUID regraId,
			@Nullable JsonNode conflitos) {
		if (regraId != null) {
			List<UUID> existentes = this.rodadas.buscarPorRegra(jobId, regraId);
			if (!existentes.isEmpty()) {
				return resultadoCorrecao(DesfechoCorrecao.DUPLICADA, regraId, existentes.getFirst(), conflitos);
			}
		}
		if (atual != JobStatus.GERANDO_REGRA) {
			return resultadoCorrecao(DesfechoCorrecao.ESTADO_INCOMPATIVEL, regraId, null, conflitos);
		}
		if (regraId == null) {
			return resultadoCorrecao(DesfechoCorrecao.REGRA_AUSENTE, null, null, conflitos);
		}
		if (!this.rodadas.regraPertenceAVersaoAtual(jobId, regraId)) {
			return resultadoCorrecao(DesfechoCorrecao.REGRA_NAO_ATUAL, regraId, null, conflitos);
		}
		if (conflitos == null || !conflitos.isArray() || conflitos.isEmpty()) {
			return resultadoCorrecao(DesfechoCorrecao.CONFLITOS_INVALIDOS, regraId, null, conflitos);
		}
		List<UUID> ultimas = this.rodadas.buscarUltima(jobId);
		if (!this.maquina.avancarSeEm(jobId, JobStatus.GERANDO_REGRA, JobStatus.AGUARDANDO_CONFIRMACAO_PARAMETROS, ATOR,
				"validacao_com_conflitos")) {
			return resultadoCorrecao(DesfechoCorrecao.ESTADO_INCOMPATIVEL, regraId, null, conflitos);
		}
		Timestamp agora = Timestamp.from(Instant.now().truncatedTo(ChronoUnit.MICROS));
		UUID rodadaId = this.rodadas.inserirPendente(jobId, regraId, conflitos,
				ultimas.isEmpty() ? null : ultimas.getFirst(), agora);
		return new EtapaAplicada(DesfechoCorrecao.RODADA_ABERTA, EventoEstadoDto.transicao(jobId,
				JobStatus.GERANDO_REGRA, JobStatus.AGUARDANDO_CONFIRMACAO_PARAMETROS, null), regraId, rodadaId,
				conflitos.size(), null);
	}

	private EtapaAplicada falharReextracao(UUID jobId, JobStatus atual, @Nullable UUID regraId,
			@Nullable UUID submissaoId) {
		if (submissaoId == null) {
			return resultadoCorrecao(
					regraId != null && !this.rodadas.regraPertenceAVersaoAtual(jobId, regraId)
							? DesfechoCorrecao.REGRA_NAO_ATUAL : DesfechoCorrecao.TENTATIVA_AUSENTE,
					regraId, null, null);
		}
		if (regraId == null) {
			return resultadoCorrecao(DesfechoCorrecao.REGRA_AUSENTE, null, null, null);
		}
		var encontradas = this.rodadas.buscarPorSubmissao(jobId, submissaoId);
		if (encontradas.isEmpty()) {
			return resultadoCorrecao(DesfechoCorrecao.TENTATIVA_DESCONHECIDA, regraId, null, null);
		}
		if (encontradas.size() != 1) {
			return resultadoCorrecao(DesfechoCorrecao.TENTATIVA_AMBIGUA, regraId, null, null);
		}
		var rodada = encontradas.getFirst();
		if (!regraId.equals(rodada.regraId())) {
			return resultadoCorrecao(DesfechoCorrecao.REGRA_DIVERGENTE, regraId, rodada.id(), null);
		}
		if ("reextracao_falhou".equals(rodada.estado())) {
			return resultadoCorrecao(DesfechoCorrecao.DUPLICADA, regraId, rodada.id(), rodada.conflitos());
		}
		if (!this.rodadas.regraPertenceAVersaoAtual(jobId, regraId)) {
			return resultadoCorrecao(DesfechoCorrecao.REGRA_NAO_ATUAL, regraId, rodada.id(), null);
		}
		if (atual != JobStatus.AGUARDANDO_CONFIRMACAO_PARAMETROS) {
			return resultadoCorrecao(DesfechoCorrecao.ESTADO_INCOMPATIVEL, regraId, rodada.id(), null);
		}
		if (!"em_reextracao".equals(rodada.estado())) {
			return resultadoCorrecao(DesfechoCorrecao.SEM_REEXTRACAO, regraId, rodada.id(), null);
		}
		Timestamp agora = Timestamp.from(Instant.now().truncatedTo(ChronoUnit.MICROS));
		this.rodadas.fecharReextracao(rodada.id(), agora);
		UUID sucessora = this.rodadas.inserirPendente(jobId, rodada.regraId(), rodada.conflitos(), rodada.id(), agora);
		return resultadoCorrecao(DesfechoCorrecao.REEXTRACAO_FALHOU, rodada.regraId(), sucessora, rodada.conflitos());
	}

	private static EtapaAplicada resultadoCorrecao(DesfechoCorrecao desfecho, @Nullable UUID regraId,
			@Nullable UUID rodadaId, @Nullable JsonNode conflitos) {
		return new EtapaAplicada(desfecho, null, regraId, rodadaId,
				conflitos != null && conflitos.isArray() ? conflitos.size() : 0, null);
	}

	/**
	 * Encerra o job em iteração e amarra o resultado da última alternativa, que pode
	 * ainda não ter chegado pela {@code simulacao-concluida}: as filas não têm ordem
	 * entre si. {@code null}, sem nada gravado, quando o job não está em iteração - a
	 * versão atual não é uma alternativa com resultado inviável, ou o job já saiu do
	 * processamento.
	 */
	private @Nullable EventoEstadoDto encerrarIteracao(UUID jobId, JobStatus status, JobStatus destino, String motivo,
			String razao) {
		if (!status.emProcessamento()) {
			return null;
		}
		List<UUID> resultados = this.repository.buscarResultadoInviavelDaAlternativaAtual(jobId);
		if (resultados.isEmpty()) {
			return null;
		}
		this.maquina.avancarSeEm(jobId, JobStatus.GERANDO_REGRA, JobStatus.SIMULANDO, ATOR, MOTIVO_ANTECIPADA);
		this.maquina.transicionar(jobId, destino, ATOR, motivo);
		this.repository.vincularResultado(jobId, resultados.getFirst());
		return EventoEstadoDto.transicao(jobId, JobStatus.SIMULANDO, destino, razao);
	}

	/**
	 * Como um {@code etapa-alterada} terminou a iteração da taxa nova: a {@code causa} e
	 * o {@code resultado} que vão para log e métrica, de conjunto fechado.
	 * {@code sem_efeito} é o {@code sem_alternativa} que encontra o job fora da iteração:
	 * o da regra original, que não teve alternativa, e a reentrega.
	 */
	enum FimDaIteracao {

		SEM_ALTERNATIVA("sem_alternativa", "aplicado"),

		SEM_ALTERNATIVA_SEM_EFEITO("sem_alternativa", "sem_efeito"),

		FALHA("falha", "aplicado");

		private final String causa;

		private final String resultado;

		FimDaIteracao(String causa, String resultado) {
			this.causa = causa;
			this.resultado = resultado;
		}

		String causa() {
			return this.causa;
		}

		String resultado() {
			return this.resultado;
		}

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
		List<String> origens = this.repository.origemDaVersaoAtualDoResultado(jobId, resultadoId);
		if (origens.isEmpty()) {
			return null;
		}
		boolean avancouDeGerandoRegra = this.maquina.avancarSeEm(jobId, JobStatus.GERANDO_REGRA, JobStatus.SIMULANDO,
				ATOR, MOTIVO_ANTECIPADA);
		if (desfecho == DesfechoDaSimulacao.INVIAVEL && VersoesDaRegra.ORIGEM_SUGESTAO.equals(origens.getFirst())) {
			return absorverAlternativaInviavel(jobId, resultadoId, avancouDeGerandoRegra);
		}
		JobStatus origem = this.maquina.transicionar(jobId, desfecho.destino(), ATOR, desfecho.motivoDaTrilha());
		UUID simulacaoId = amarrarResultado(jobId, resultadoId);
		return new DesfechoAplicado(origem, simulacaoId, avancouDeGerandoRegra, false);
	}

	/**
	 * A alternativa que não coube não é desfecho: o codegen ainda propõe outra taxa ou
	 * anuncia que não há. O job fica em {@code simulando} e o resultado é amarrado para a
	 * auditoria, sem transição. Depois do fim da iteração, a reentrega ou o resultado
	 * atrasado encontram o job fora do processamento e são recusados como qualquer
	 * desfecho fora de ordem.
	 */
	private DesfechoAplicado absorverAlternativaInviavel(UUID jobId, UUID resultadoId, boolean avancouDeGerandoRegra) {
		JobStatus status = JobStatus.deColuna(this.repository.buscarStatusComTrava(jobId));
		if (status != JobStatus.SIMULANDO) {
			throw new TransicaoDeStatusInvalidaException(status, JobStatus.SIMULANDO);
		}
		this.repository.vincularResultado(jobId, resultadoId);
		return DesfechoAplicado.intermediario(avancouDeGerandoRegra);
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

	/**
	 * {@code intermediario} é o resultado inviável de uma alternativa enquanto o codegen
	 * pode tentar outra taxa: não houve transição, e o usuário não o vê.
	 */
	record DesfechoAplicado(JobStatus origem, @Nullable UUID simulacaoId, boolean avancouDeGerandoRegra,
			boolean intermediario) {

		static DesfechoAplicado intermediario(boolean avancouDeGerandoRegra) {
			return new DesfechoAplicado(JobStatus.SIMULANDO, null, avancouDeGerandoRegra, true);
		}

	}

	@Transactional
	@Nullable SugestaoAplicada aplicarSugestaoAdaptacao(UUID jobId, UUID regraOrigemId, UUID resultadoId,
			RepresentacaoRegraDto representacao, @Nullable Integer tentativa) {
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
		// A sugestão só ajusta nucleo.percentual; os parâmetros da versão de origem
		// passam para a nova como estavam, e o hash os cobre pelo mesmo motivo do
		// núcleo - sem isso, uma origem nascida de texto com parâmetros nunca bateria
		// hash com a sugestão que ela mesma originou. Lista vazia é regraOrigemId
		// inexistente: sugestaoElegivel também diria não, mas sem lançar antes dela.
		List<String> parametrosDaOrigem = this.repository.buscarParametrosDaVersao(regraOrigemId);
		if (parametrosDaOrigem.isEmpty()) {
			return null;
		}
		String parametrosJson = parametrosDaOrigem.getFirst();
		ParametrosDaSimulacao parametros = ParametrosExtraidos.deVersaoExistente(parametrosJson);
		String hash = HashDaRegra.calcular(representacao, parametros);
		Boolean valida = this.repository.sugestaoElegivel(jobId, regraOrigemId, resultadoId, hash, percentual,
				representacao);
		if (!Boolean.TRUE.equals(valida)) {
			return null;
		}
		// As filas não têm ordem entre si: a proposta pode anteceder o evento do
		// resultado. Na regra original, ele é o desfecho inviável; na alternativa, é
		// absorvido sem desfecho, e o job segue de simulando para a tentativa seguinte.
		DesfechoAplicado desfechoDaOrigem = null;
		if (contexto.status() != JobStatus.SIMULACAO_INVIAVEL) {
			desfechoDaOrigem = aplicarDesfecho(jobId, resultadoId, DesfechoDaSimulacao.INVIAVEL);
			if (desfechoDaOrigem == null) {
				return null;
			}
			if (!desfechoDaOrigem.intermediario() && desfechoDaOrigem.simulacaoId() == null) {
				// no-concluido pode ter vinculado o resultado antes de sua notificação.
				List<UUID> simulacoes = this.repository.buscarSimulacaoPorResultado(jobId, resultadoId);
				if (!simulacoes.isEmpty()) {
					desfechoDaOrigem = new DesfechoAplicado(desfechoDaOrigem.origem(), simulacoes.getFirst(),
							desfechoDaOrigem.avancouDeGerandoRegra(), false);
				}
			}
		}
		JobStatus origem = this.maquina.transicionar(jobId, JobStatus.GERANDO_REGRA, ATOR,
				"sugestao_adaptacao_proposta");
		Instant agora = Instant.now().truncatedTo(ChronoUnit.MICROS);
		VersaoRegra versao = this.versoes.resolverSugestao(jobId, representacao, parametrosJson, hash, regraOrigemId,
				tentativa, Timestamp.from(agora), agora);
		this.outbox.registrar(jobId, EventoOutbox.REGRA_SUBMETIDA, contexto.regraSubmetida(versao.id()));
		return new SugestaoAplicada(origem, versao, desfechoDaOrigem);
	}

	record SugestaoAplicada(JobStatus origem, VersaoRegra versao, @Nullable DesfechoAplicado desfechoDaOrigem) {
	}

	/**
	 * Grava a versão raiz de um job de texto ou voz a partir da extração do codegen, leva
	 * para o job os parâmetros que o texto disse e registra o {@code regra-submetida} que
	 * reabre o ciclo - tudo na mesma transação. Não move o job: ele segue em
	 * {@code gerando_regra}. A trava do job serializa duas entregas da mesma extração, e
	 * a segunda encontra a versão já gravada, sem regravar parâmetro nem republicar.
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
		ParametrosDaSimulacao parametros = ParametrosExtraidos.validados(extracao.parametros());
		if (parametros == null) {
			return ExtracaoAplicada.descartada(DesfechoDaExtracao.PARAMETROS_INVALIDOS);
		}

		String hash = HashDaRegra.calcular(representacao, parametros);
		List<VersaoRegra> jaGravada = this.repository.buscarRegraPorHash(jobId, hash);
		if (!jaGravada.isEmpty() && VersoesDaRegra.ORIGEM_EXTRACAO.equals(jaGravada.getFirst().origem())) {
			return new ExtracaoAplicada(DesfechoDaExtracao.REENTREGA, jaGravada.getFirst().id(),
					ParametrosGravados.NENHUM);
		}
		if (contexto.status() != JobStatus.GERANDO_REGRA) {
			return ExtracaoAplicada.descartada(DesfechoDaExtracao.ESTADO_INCOMPATIVEL);
		}
		Integer maiorVersao = this.repository.buscarMaiorVersao(jobId);
		if (maiorVersao != null && maiorVersao > 0) {
			return ExtracaoAplicada.descartada(DesfechoDaExtracao.VERSAO_EXISTENTE);
		}

		Instant agora = Instant.now().truncatedTo(ChronoUnit.MICROS);
		gravarParametrosNoJob(jobId, parametros);
		VersaoRegra versao = this.versoes.resolverExtracao(jobId, extracaoId, hash, Timestamp.from(agora), agora);
		this.outbox.registrar(jobId, EventoOutbox.REGRA_SUBMETIDA,
				contexto.com(parametros).regraSubmetida(versao.id()));
		return new ExtracaoAplicada(DesfechoDaExtracao.PERSISTIDA, versao.id(), ParametrosGravados.de(parametros));
	}

	/**
	 * Grava no job o que a extração trouxe, e só isso: um parâmetro que o texto não disse
	 * não é apagado nem recebe padrão aqui. Sem período dito, o job segue com as
	 * competências com que nasceu, que são todas as publicadas. O valor vai como veio,
	 * inclusive inválido - um orçamento negativo é gravado, e quem o aponta é a validação
	 * de domínio do ciclo que este evento reabre.
	 */
	private void gravarParametrosNoJob(UUID jobId, ParametrosDaSimulacao parametros) {
		BigDecimal orcamento = parametros.orcamento();
		if (orcamento != null) {
			this.repository.atualizarOrcamento(jobId, orcamento);
		}
		BigDecimal metaVenda = parametros.meta_venda();
		if (metaVenda != null) {
			this.repository.atualizarMetaVenda(jobId, metaVenda);
		}
		List<String> periodo = parametros.periodoCanonico();
		if (periodo != null) {
			this.repository.atualizarCompetencias(jobId, periodo);
		}
	}

	/**
	 * {@code regraId} existe quando há versão da extração: gravada agora ou reentregue.
	 * {@code parametros} diz quais o job recebeu agora, sem os valores, e é
	 * {@link ParametrosGravados#NENHUM} em todo desfecho que não gravou - inclusive na
	 * reentrega, que não regrava os que a primeira entrega já levou.
	 */
	record ExtracaoAplicada(DesfechoDaExtracao desfecho, @Nullable UUID regraId, ParametrosGravados parametros) {

		static ExtracaoAplicada descartada(DesfechoDaExtracao desfecho) {
			return new ExtracaoAplicada(desfecho, null, ParametrosGravados.NENHUM);
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

		PARAMETROS_INVALIDOS("descartada", "parametros_invalidos"),

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
