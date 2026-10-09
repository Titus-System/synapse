package synapse.api.job;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.sql.Timestamp;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;

import org.jspecify.annotations.Nullable;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import tools.jackson.databind.JsonNode;

import org.springframework.dao.EmptyResultDataAccessException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import synapse.api.core.logging.CorrelationContext;
import synapse.api.core.outbox.EventoOutbox;
import synapse.api.core.outbox.Outbox;
import synapse.api.core.security.AcessoDoUsuario;
import synapse.api.core.sse.EmissoresSse;
import synapse.api.core.sse.EventoSse;
import synapse.api.job.JobRepository.DadosConsulta;
import synapse.api.job.JobRepository.DadosDoJob;
import synapse.api.job.JobRepository.JobDeOrigem;
import synapse.api.job.JobRepository.VersaoAnterior;
import synapse.api.job.VersoesDaRegra.VersaoRegra;

@Service
class JobService {

	// Mantém a identificação operacional do logger anterior à consolidação.
	private static final Logger log = LoggerFactory.getLogger("synapse.api.job.BuscarJobService");

	private final JobRepository repository;

	private final MaquinaDeEstadosDoJob maquina;

	private final Outbox outbox;

	private final VersoesDaRegra versoes;

	private final EmissoresSse emissores;

	private final CorrelationContext correlacao;

	JobService(JobRepository repository, MaquinaDeEstadosDoJob maquina, Outbox outbox, VersoesDaRegra versoes,
			EmissoresSse emissores, CorrelationContext correlacao) {
		this.repository = repository;
		this.maquina = maquina;
		this.outbox = outbox;
		this.versoes = versoes;
		this.emissores = emissores;
		this.correlacao = correlacao;
	}

	@Transactional
	JobCriadoDto criar(CriarJobRequisicao requisicao) {
		List<UUID> usuarios = this.repository.buscarPrimeiroUsuarioAtivo();
		if (usuarios.isEmpty()) {
			throw CriarJobException.semUsuarioAtivo();
		}
		return criar(requisicao, usuarios.getFirst());
	}

	@Transactional
	JobCriadoDto criar(CriarJobRequisicao requisicao, UUID usuarioId) {
		Integer usuariosAtivos = this.repository.contarUsuarioAtivo(usuarioId);
		if (usuariosAtivos == null || usuariosAtivos == 0) {
			throw CriarJobException.semUsuarioAtivo();
		}
		Instant agora = Instant.now().truncatedTo(ChronoUnit.MICROS);
		Timestamp timestamp = Timestamp.from(agora);
		RepresentacaoRegraDto representacao = requisicao.representacao();
		String hash = HashDaRegra.calcular(representacao);
		UUID submissaoId = this.repository.inserirSubmissao(usuarioId, requisicao.origem(), requisicao.conteudo(),
				timestamp);
		String status = JobStatus.GERANDO_REGRA.paraColuna();
		UUID jobId = this.repository.inserirJob(status, usuarioId, submissaoId, requisicao.competencias(),
				requisicao.orcamento(), timestamp);
		this.maquina.registrarCriacao(jobId, JobStatus.GERANDO_REGRA, "usuario");
		UUID regraId = this.repository.inserirRegraInicial(jobId, representacao, hash, timestamp);
		RegraCriadaDto regra = new RegraCriadaDto(regraId, 1, "confirmacao_usuario", representacao, agora);
		this.outbox.registrar(jobId, EventoOutbox.REGRA_SUBMETIDA, new RegraSubmetidaDto(jobId, requisicao.origem(),
				requisicao.competencias(), requisicao.orcamento(), submissaoId, regraId));
		return new JobCriadoDto(jobId, status, requisicao.origem(), requisicao.competencias(), requisicao.orcamento(),
				agora, submissaoId, null, regra);
	}

	/**
	 * {@code REPEATABLE_READ} faz a contagem e a página lerem o mesmo snapshot. O
	 * veredito é o da simulação mais recente do job, e só quando ela terminou com
	 * sucesso.
	 */
	@Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
	PaginaJobsDto listar(ListarJobsRequisicao requisicao, AcessoDoUsuario acesso) {
		long total = this.repository.contarJobs(acesso.usuarioId());
		List<JobResumoDto> itens = this.repository.listarJobs(acesso.usuarioId(), requisicao.tamanho(),
				requisicao.deslocamento());
		return new PaginaJobsDto(itens, requisicao.pagina(), requisicao.tamanho(), total);
	}

	@Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
	JobDetalhadoDto buscar(UUID jobId) {
		return consultarJob(jobId);
	}

	/**
	 * O detalhamento sai como foi gravado. Os logs registram só referências e se havia
	 * detalhamento, nunca o conteúdo.
	 */
	@Transactional(readOnly = true)
	DetalhamentoSimulacaoDto detalharSimulacao(UUID jobId, UUID simulacaoId) {
		try (var escopo = this.correlacao.abrir(jobId.toString(), null)) {
			List<DetalhamentoSimulacaoDto> encontrados = this.repository.buscarDetalhamento(jobId, simulacaoId);
			if (encontrados.isEmpty()) {
				log.atWarn()
					.addKeyValue("simulacao_id", simulacaoId)
					.log("detalhamento recusado: simulação não encontrada no job");
				throw new SimulacaoNaoEncontradaException(simulacaoId);
			}
			DetalhamentoSimulacaoDto detalhamento = encontrados.getFirst();
			log.atDebug()
				.addKeyValue("simulacao_id", simulacaoId)
				.addKeyValue("com_detalhamento", detalhamento.linhas() != null)
				.log("detalhamento da simulação consultado");
			return detalhamento;
		}
	}

	private JobDetalhadoDto consultarJob(UUID jobId) {
		try {
			DadosConsulta dados = this.repository.consultarJob(jobId);
			String motivo = motivo(dados.id(), JobStatus.deColuna(dados.status()), dados.motivoDaTrilha());
			List<RegraCriadaDto> regras = this.repository.mapearRegras(dados.regrasJson());
			JobDetalhadoDto job = new JobDetalhadoDto(dados.id(), dados.status(), dados.origem(), dados.competencias(),
					dados.orcamento(), dados.criadoEm(), dados.iniciadoEm(), dados.finalizadoEm(), dados.submissaoId(),
					dados.jobOrigemId(), motivo, regras, null, List.of());
			List<SimulacaoDto> simulacoes = this.repository.listarSimulacoes(jobId);
			SimulacaoDto simulacao = simulacoes.isEmpty() ? null : simulacoes.getLast();
			return new JobDetalhadoDto(job.id(), job.status(), job.origem(), job.competencias(), job.orcamento(),
					job.criado_em(), job.iniciado_em(), job.finalizado_em(), job.submissao_id(), job.job_origem_id(),
					job.motivo(), job.regras(), simulacao, simulacoes);
		}
		catch (EmptyResultDataAccessException ex) {
			throw new JobNaoEncontradoException(jobId);
		}
	}

	/**
	 * A razão da parada corrente. Um job em {@code erro} ou {@code simulacao_inviavel}
	 * cuja causa não se reconhece devolve a resposta sem {@code motivo} e deixa o rastro
	 * no log: a tela cai na mensagem genérica, e quem opera precisa saber que isso
	 * aconteceu.
	 */
	private @Nullable String motivo(UUID jobId, JobStatus status, @Nullable String motivoDaTrilha) {
		String razao = MotivoDaParada.razaoLocalizada(status, motivoDaTrilha);
		if (razao == null && (status == JobStatus.ERRO || status == JobStatus.SIMULACAO_INVIAVEL)) {
			try (var escopo = this.correlacao.abrir(jobId.toString(), null)) {
				log.atWarn()
					.addKeyValue("status", status.paraColuna())
					.addKeyValue("motivo_registrado", motivoDaTrilha != null)
					.log("job parado sem motivo reconhecível; consulta devolvida sem motivo");
			}
		}
		return razao;
	}

	/**
	 * Abre o stream de {@code jobId}. A fotografia é lida uma única vez, sob a trava de
	 * {@link EmissoresSse#inscrever}: se o job não existir,
	 * {@link JobNaoEncontradoException} propaga e nenhum emissor fica registrado - a
	 * requisição responde 404 em vez de virar stream.
	 */
	SseEmitter acompanhar(UUID jobId) {
		return this.emissores.inscrever(jobId, () -> fotografia(jobId));
	}

	private EventoSse fotografia(UUID jobId) {
		JobStatus status = statusAtual(jobId);
		EventoEstadoDto evento = EventoEstadoDto.fotografia(jobId, status);
		return status.terminal() ? EventoSse.ultimo("estado", evento) : EventoSse.de("estado", evento);
	}

	private JobStatus statusAtual(UUID jobId) {
		try {
			String status = this.repository.buscarStatus(jobId);
			return JobStatus.deColuna(status);
		}
		catch (EmptyResultDataAccessException ex) {
			throw new JobNaoEncontradoException(jobId);
		}
	}

	@Transactional
	JobCriadoDto confirmar(UUID jobId, ConfirmarParametrosRequisicao requisicao) {
		DadosDoJob dados = carregarJob(jobId);
		this.maquina.transicionar(jobId, JobStatus.GERANDO_REGRA, "usuario", null);

		VersaoAnterior anterior = ultimaVersao(jobId);
		RepresentacaoRegraDto representacao = requisicao.representacao();
		String hash = HashDaRegra.calcular(representacao);
		boolean editado = anterior != null && !hash.equals(anterior.hash());

		Instant agora = Instant.now().truncatedTo(ChronoUnit.MICROS);
		Timestamp timestamp = Timestamp.from(agora);
		VersaoRegra versao = this.versoes.resolver(jobId, representacao, hash, "confirmacao_usuario",
				(anterior != null) ? anterior.id() : null, timestamp, agora);

		BigDecimal orcamento = resolverOrcamento(jobId, requisicao, dados.orcamento());
		List<String> competencias = resolverCompetencias(jobId, requisicao);

		this.outbox.registrar(jobId, EventoOutbox.PARAMETROS_CONFIRMADOS,
				new ParametrosConfirmadosDto(jobId, versao.id()));
		registrarTrilha(jobId, versao.id(), editado, representacao, anterior, timestamp);

		RegraCriadaDto regra = new RegraCriadaDto(versao.id(), versao.versao(), versao.origem(), representacao,
				versao.criadaEm());
		return new JobCriadoDto(jobId, JobStatus.GERANDO_REGRA.paraColuna(), dados.origem(), competencias, orcamento,
				dados.criadoEm(), dados.submissaoId(), dados.jobOrigemId(), regra);
	}

	private DadosDoJob carregarJob(UUID jobId) {
		try {
			return this.repository.buscarDadosParaConfirmacao(jobId);
		}
		catch (EmptyResultDataAccessException ex) {
			throw new JobNaoEncontradoException(jobId);
		}
	}

	private @Nullable VersaoAnterior ultimaVersao(UUID jobId) {
		List<VersaoAnterior> versoes = this.repository.buscarUltimaVersao(jobId);
		return versoes.isEmpty() ? null : versoes.getFirst();
	}

	private BigDecimal resolverOrcamento(UUID jobId, ConfirmarParametrosRequisicao requisicao, BigDecimal atual) {
		BigDecimal novo = requisicao.orcamento();
		if (novo == null) {
			return atual;
		}
		this.repository.atualizarOrcamento(jobId, novo);
		return novo;
	}

	private List<String> resolverCompetencias(UUID jobId, ConfirmarParametrosRequisicao requisicao) {
		List<String> novas = requisicao.competencias();
		if (novas != null) {
			this.repository.atualizarCompetencias(jobId, novas);
			return novas;
		}
		return this.repository.buscarCompetencias(jobId);
	}

	private void registrarTrilha(UUID jobId, UUID regraId, boolean editado, RepresentacaoRegraDto atual,
			@Nullable VersaoAnterior anterior, Timestamp timestamp) {
		List<String> corrigidos = (anterior != null && editado) ? camposCorrigidos(atual.nucleo(), anterior.nucleo())
				: new ArrayList<>();
		if (anterior != null && editado) {
			corrigidos.addAll(especificacoesCorrigidas(atual.especificacoes(), anterior.especificacoes()));
		}
		String resumo = editado ? "usuário corrigiu "
				+ (corrigidos.isEmpty() ? "a representação" : String.join(", ", corrigidos)) + " antes de confirmar"
				: "usuário confirmou os parâmetros";
		Map<String, Object> conclusao = new LinkedHashMap<>();
		conclusao.put("resumo", resumo);
		conclusao.put("editado_pelo_usuario", editado);
		conclusao.put("campos_corrigidos", corrigidos);
		UUID eventoId = UUID.nameUUIDFromBytes(("confirmacao:" + regraId).getBytes(StandardCharsets.UTF_8));
		this.repository.inserirTrilhaConfirmacao(eventoId, jobId, timestamp, regraId, conclusao);
	}

	private static List<String> camposCorrigidos(NucleoRegraDto atual, NucleoRegraDto anterior) {
		List<String> corrigidos = new ArrayList<>();
		if (!Objects.equals(atual.vigencia(), anterior.vigencia())) {
			corrigidos.add("nucleo.vigencia");
		}
		if (!Objects.equals(atual.loja(), anterior.loja())) {
			corrigidos.add("nucleo.loja");
		}
		if (!Objects.equals(atual.marca(), anterior.marca())) {
			corrigidos.add("nucleo.marca");
		}
		if (!Objects.equals(atual.cargo(), anterior.cargo())) {
			corrigidos.add("nucleo.cargo");
		}
		if (percentualDiferente(atual.percentual(), anterior.percentual())) {
			corrigidos.add("nucleo.percentual");
		}
		return corrigidos;
	}

	private static boolean percentualDiferente(@Nullable BigDecimal atual, @Nullable BigDecimal anterior) {
		if (atual == null || anterior == null) {
			return (atual == null) != (anterior == null);
		}
		return atual.compareTo(anterior) != 0;
	}

	private static List<String> especificacoesCorrigidas(List<JsonNode> atuais, List<JsonNode> anteriores) {
		var refs = new LinkedHashSet<String>();
		atuais.forEach(elemento -> refs.add(elemento.path("ref").asString()));
		anteriores.forEach(elemento -> refs.add(elemento.path("ref").asString()));
		return refs.stream()
			.filter(ref -> !atuais.stream()
				.filter(elemento -> ref.equals(elemento.path("ref").asString()))
				.toList()
				.equals(anteriores.stream().filter(elemento -> ref.equals(elemento.path("ref").asString())).toList()))
			.toList();
	}

	@Transactional
	AcaoAplicada executarAcao(UUID jobId, AcaoJob acao) {
		JobStatus origem;
		try {
			origem = this.maquina.transicionar(jobId, acao.destino(), "usuario", null);
		}
		catch (EmptyResultDataAccessException ex) {
			throw new JobNaoEncontradoException(jobId);
		}
		catch (TransicaoDeStatusInvalidaException ex) {
			if (acao.destino() == JobStatus.LIBERADO && ex.origem() == JobStatus.SIMULACAO_INVIAVEL) {
				throw ExecutarAcaoException.simulacaoInviavel();
			}
			throw ExecutarAcaoException.estadoInvalido(acao, ex.origem());
		}
		this.repository.inserirAcao(jobId, acao.paraColuna(), Timestamp.from(Instant.now()));
		EventoEstadoDto evento = EventoEstadoDto.transicao(jobId, origem, acao.destino(), null);
		JobDetalhadoDto job = consultarJob(jobId);
		return new AcaoAplicada(evento, job);
	}

	record AcaoAplicada(EventoEstadoDto evento, JobDetalhadoDto job) {
	}

	@Transactional
	JobCriadoDto reprocessar(UUID origemId, ReprocessarJobRequisicao requisicao) {
		JobDeOrigem origem = carregarOrigem(origemId);
		if (origem.status() != JobStatus.ARQUIVADO) {
			throw ReprocessarJobException.estadoInvalido();
		}
		List<UUID> regras = this.repository.buscarIdUltimaRegra(origemId);
		if (regras.isEmpty()) {
			throw ReprocessarJobException.semRegra();
		}
		List<String> competencias = requisicao.competencias() != null ? requisicao.competencias()
				: origem.competencias();
		BigDecimal orcamento = requisicao.orcamento() != null ? requisicao.orcamento() : origem.orcamento();
		Instant agora = Instant.now().truncatedTo(ChronoUnit.MICROS);
		Timestamp timestamp = Timestamp.from(agora);
		JobStatus status = JobStatus.AGUARDANDO_CONFIRMACAO_PARAMETROS;
		UUID jobId = this.repository.inserirJobReprocessado(status.paraColuna(), origem.usuarioId(), origemId,
				competencias, orcamento, timestamp);
		this.maquina.registrarCriacao(jobId, status, "usuario");
		RegraCriadaDto regra = this.repository.copiarRegra(jobId, regras.getFirst(), timestamp, agora);
		this.outbox.registrar(jobId, EventoOutbox.REGRA_SUBMETIDA,
				new RegraSubmetidaDto(jobId, "reprocessamento", competencias, orcamento, null, regra.id()));
		return new JobCriadoDto(jobId, status.paraColuna(), "reprocessamento", competencias, orcamento, agora, null,
				origemId, regra);
	}

	private JobDeOrigem carregarOrigem(UUID jobId) {
		List<JobDeOrigem> jobs = this.repository.buscarJobDeOrigem(jobId);
		if (jobs.isEmpty()) {
			throw new JobNaoEncontradoException(jobId);
		}
		return jobs.getFirst();
	}

}
