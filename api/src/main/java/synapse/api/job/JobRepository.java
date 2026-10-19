package synapse.api.job;

import java.math.BigDecimal;
import java.sql.Array;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;

import org.jspecify.annotations.Nullable;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.SqlArrayValue;
import org.springframework.stereotype.Repository;

import synapse.api.job.VersoesDaRegra.VersaoRegra;

@Repository
class JobRepository {

	/**
	 * Texto inicial do job: o da própria submissão ou, no job reprocessado, o do primeiro
	 * job da cadeia de origem que tem submissão. Exige o alias {@code j} para jobs.
	 */
	/**
	 * O {@code conclusao.encaminhamento} da decisão que abriu a busca da meta maior, como
	 * o codegen o grava na trilha
	 * ({@code contracts/domain/trilha-conclusao.schema.json}).
	 */
	static final String ENCAMINHAMENTO_BUSCA_META = "busca_meta";

	private static final String JUNCAO_TEXTO_INICIAL = """
			LEFT JOIN LATERAL (
				WITH RECURSIVE cadeia AS (
					SELECT j.submissao_id, j.job_origem_id, 0 AS nivel
					UNION ALL
					SELECT o.submissao_id, o.job_origem_id, c.nivel + 1
					FROM cadeia c
					JOIN jobs o ON o.id = c.job_origem_id
					WHERE c.submissao_id IS NULL
				)
				SELECT si.transcricao
				FROM cadeia c
				JOIN submissoes si ON si.id = c.submissao_id
				ORDER BY c.nivel
				LIMIT 1
			) inicial ON true
			""";

	/** Nome resolvido: o definido pelo usuário, senão o padrão, senão NULL. */
	private static final String NOME_RESOLVIDO = """
			COALESCE(j.nome, NULLIF(left(
				regexp_replace(btrim(inicial.transcricao, E' \\t\\r\\n'), '[ \\t\\r\\n]+', ' ', 'g'),
				50), '')) AS nome
			""";

	private final JdbcTemplate jdbc;

	private final JsonMapper json = JsonMapper.builder()
		.enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS)
		.build();

	private final JsonMapper jsonPadrao = new JsonMapper();

	JobRepository(JdbcTemplate jdbc) {
		this.jdbc = jdbc;
	}

	long contarJobs(UUID usuarioId) {
		return Objects.requireNonNull(this.jdbc.queryForObject("""
				SELECT count(*) FROM jobs WHERE usuario_id = ?
				""", Long.class, usuarioId));
	}

	List<JobResumoDto> listarJobs(UUID usuarioId, int tamanho, long deslocamento) {
		return this.jdbc.query("""
				SELECT j.id, j.status, j.competencias, j.orcamento, j.meta_venda, j.criado_em, j.finalizado_em,
				       j.job_origem_id, rs.veredito,
					   """ + NOME_RESOLVIDO + """
				FROM jobs j
				""" + JUNCAO_TEXTO_INICIAL + """
				LEFT JOIN LATERAL (
				    SELECT s.resultado_id FROM simulacoes s
				    WHERE s.job_id = j.id
				    ORDER BY s.criado_em DESC, s.id DESC
				    LIMIT 1
				) corrente ON true
				LEFT JOIN resultados_simulacao rs ON rs.id = corrente.resultado_id AND rs.status = 'sucesso'
				WHERE j.usuario_id = ?
				ORDER BY j.criado_em DESC, j.id DESC
				LIMIT ? OFFSET ?
				""", (linha, numero) -> resumo(linha), usuarioId, tamanho, deslocamento);
	}

	private static JobResumoDto resumo(ResultSet linha) throws SQLException {
		return new JobResumoDto(Objects.requireNonNull(linha.getObject("id", UUID.class)),
				Objects.requireNonNull(linha.getString("status")), competencias(linha.getArray("competencias")),
				linha.getBigDecimal("orcamento"), linha.getBigDecimal("meta_venda"), linha.getString("veredito"),
				Objects.requireNonNull(instante(linha, "criado_em")), instante(linha, "finalizado_em"),
				linha.getObject("job_origem_id", UUID.class), linha.getString("nome"));
	}

	private static List<String> competencias(Array coluna) throws SQLException {
		return List.of((String[]) coluna.getArray());
	}

	private static @Nullable Instant instante(ResultSet linha, String coluna) throws SQLException {
		OffsetDateTime valor = linha.getObject(coluna, OffsetDateTime.class);
		return valor == null ? null : valor.toInstant();
	}

	List<UUID> buscarProprietario(UUID jobId) {
		return this.jdbc.queryForList("SELECT usuario_id FROM jobs WHERE id = ?", UUID.class, jobId);
	}

	String buscarStatus(UUID jobId) {
		return Objects
			.requireNonNull(this.jdbc.queryForObject("SELECT status FROM jobs WHERE id = ?", String.class, jobId));
	}

	DadosConsulta consultarJob(UUID jobId) {
		return this.jdbc.queryForObject("""
				SELECT
				    j.id,
				    j.status,
				    CASE WHEN j.job_origem_id IS NOT NULL THEN 'reprocessamento' ELSE s.tipo END AS origem,
				    j.competencias,
				    j.orcamento,
				    j.meta_venda,
				    j.criado_em,
				    j.iniciado_em,
				    j.finalizado_em,
				    j.submissao_id,
				    j.job_origem_id,
				    ultima.motivo AS motivo_da_trilha,
				    regras.regras,
					""" + NOME_RESOLVIDO + """

				FROM jobs j
				""" + JUNCAO_TEXTO_INICIAL + """
				LEFT JOIN submissoes s ON s.id = j.submissao_id
				LEFT JOIN LATERAL (
				    SELECT t.motivo
				    FROM job_transicoes t
				    WHERE t.job_id = j.id
				    ORDER BY t.ocorrido_em DESC, t.id DESC
				    LIMIT 1
				) ultima ON true
				JOIN LATERAL (
				    SELECT COALESCE(jsonb_agg(
				        jsonb_build_object(
				            'id', r.id,
				            'versao', r.versao,
				            'origem', r.origem,
				            'nucleo', r.nucleo,
				            'especificacoes', r.especificacoes,
				            'criada_em', r.criada_em
				        ) ORDER BY r.versao
				    ), '[]'::jsonb) AS regras
				    FROM regras r
				    WHERE r.job_id = j.id
				) regras ON true
				WHERE j.id = ?
				""", (rs, rowNum) -> {
			UUID id = rs.getObject("id", UUID.class);
			String status = rs.getString("status");
			String origem = rs.getString("origem");
			List<String> competencias = List.of((String[]) rs.getArray("competencias").getArray());
			BigDecimal orcamento = rs.getBigDecimal("orcamento");
			BigDecimal metaVenda = rs.getBigDecimal("meta_venda");
			Instant criadoEm = rs.getTimestamp("criado_em").toInstant();
			Instant iniciadoEm = rs.getTimestamp("iniciado_em") != null ? rs.getTimestamp("iniciado_em").toInstant()
					: null;
			Instant finalizadoEm = rs.getTimestamp("finalizado_em") != null
					? rs.getTimestamp("finalizado_em").toInstant() : null;
			UUID submissaoId = rs.getObject("submissao_id", UUID.class);
			UUID jobOrigemId = rs.getObject("job_origem_id", UUID.class);

			String motivo = rs.getString("motivo_da_trilha");

			String regras = rs.getString("regras");

			String nome = rs.getString("nome");

			return new DadosConsulta(id, status, origem, competencias, orcamento, metaVenda, criadoEm, iniciadoEm,
					finalizadoEm, submissaoId, jobOrigemId, motivo, regras, nome);
		}, jobId);
	}

	List<SimulacaoDto> listarSimulacoes(UUID jobId) {
		return this.jdbc.query("""
				SELECT s.id, s.regra_id, s.criado_em, s.flag_baixa_rastreabilidade,
				       r.status, r.veredito, r.totais, r.assercoes, r.decomposicao, r.meta_venda
				FROM simulacoes s
				JOIN resultados_simulacao r ON r.id = s.resultado_id
				WHERE s.job_id = ? ORDER BY s.criado_em, s.id
				""", (rs, numero) -> simulacao(rs), jobId);
	}

	private SimulacaoDto simulacao(ResultSet rs) throws SQLException {
		String status = Objects.requireNonNull(rs.getString("status"));
		boolean sucesso = "sucesso".equals(status);
		return new SimulacaoDto(rs.getObject("id", UUID.class), rs.getObject("regra_id", UUID.class),
				rs.getTimestamp("criado_em").toInstant(), status, sucesso ? rs.getString("veredito") : null,
				rs.getBoolean("flag_baixa_rastreabilidade"), sucesso ? resultado(rs) : null,
				rs.getBigDecimal("meta_venda"));
	}

	private ResultadoSimulacaoDto resultado(ResultSet rs) throws SQLException {
		TotaisSimulacaoDto totais = rs.getString("totais") == null ? null
				: this.json.readValue(rs.getString("totais"), TotaisSimulacaoDto.class);
		List<ResultadoAssercaoDto> assercoes = this.json.readValue(rs.getString("assercoes"),
				new TypeReference<List<ResultadoAssercaoDto>>() {
				});
		DecomposicaoResultadoDto decomposicao = rs.getString("decomposicao") == null ? null
				: this.json.readValue(rs.getString("decomposicao"), DecomposicaoResultadoDto.class);
		return new ResultadoSimulacaoDto(totais, assercoes, decomposicao);
	}

	/**
	 * Única leitura de {@code resultados_simulacao.linhas}. O {@code LEFT JOIN} mantém a
	 * simulação ainda sem resultado, que existe e não tem detalhamento.
	 */
	List<DetalhamentoSimulacaoDto> buscarDetalhamento(UUID jobId, UUID simulacaoId) {
		return this.jdbc.query("""
				SELECT s.id, r.linhas
				FROM simulacoes s
				LEFT JOIN resultados_simulacao r ON r.id = s.resultado_id
				WHERE s.id = ? AND s.job_id = ?
				""",
				(rs, numero) -> new DetalhamentoSimulacaoDto(Objects.requireNonNull(rs.getObject("id", UUID.class)),
						rs.getString("linhas")),
				simulacaoId, jobId);
	}

	List<RegraCriadaDto> mapearRegras(String regrasJson) {
		JsonNode raiz = this.json.readTree(regrasJson);
		List<RegraCriadaDto> regras = new ArrayList<>();
		for (JsonNode regra : raiz) {
			NucleoRegraDto nucleo = this.json.readValue(regra.path("nucleo").toString(), NucleoRegraDto.class);
			List<JsonNode> especificacoes = regra.path("especificacoes").valueStream().toList();
			RepresentacaoRegraDto representacao = new RepresentacaoRegraDto(nucleo, especificacoes);
			regras.add(new RegraCriadaDto(UUID.fromString(regra.path("id").asString()), regra.path("versao").asInt(),
					regra.path("origem").asString(), representacao, Instant.parse(regra.path("criada_em").asString())));
		}
		return List.copyOf(regras);
	}

	List<UUID> buscarPrimeiroUsuarioAtivo() {
		return this.jdbc.queryForList("""
				SELECT id FROM usuarios WHERE ativo = true ORDER BY criado_em, id LIMIT 1
				""", UUID.class);
	}

	@Nullable Integer contarUsuarioAtivo(UUID usuarioId) {
		return this.jdbc.queryForObject("SELECT count(*) FROM usuarios WHERE id = ? AND ativo = true", Integer.class,
				usuarioId);
	}

	UUID inserirSubmissao(UUID usuarioId, String origem, JsonNode conteudo, Timestamp timestamp) {
		return Objects.requireNonNull(this.jdbc.queryForObject("""
				INSERT INTO submissoes (usuario_id, tipo, conteudo, criado_em)
				VALUES (?, ?, ?::jsonb, ?) RETURNING id
				""", UUID.class, usuarioId, origem, this.jsonPadrao.writeValueAsString(conteudo), timestamp));
	}

	UUID inserirJob(String status, UUID usuarioId, UUID submissaoId, List<String> competencias,
			@Nullable BigDecimal orcamento, Timestamp timestamp) {
		return Objects.requireNonNull(this.jdbc.queryForObject("""
				INSERT INTO jobs (status, usuario_id, submissao_id, competencias, orcamento, criado_em)
				VALUES (?, ?, ?, ?, ?, ?) RETURNING id
				""", UUID.class, status, usuarioId, submissaoId, new SqlArrayValue("text", competencias.toArray()),
				orcamento, timestamp));
	}

	UUID inserirRegraInicial(UUID jobId, RepresentacaoRegraDto representacao, String hash, Timestamp timestamp) {
		return Objects.requireNonNull(this.jdbc.queryForObject("""
				INSERT INTO regras (job_id, versao, origem, nucleo, especificacoes, hash, criada_em)
				VALUES (?, 1, 'confirmacao_usuario', ?::jsonb, '[]'::jsonb, ?, ?) RETURNING id
				""", UUID.class, jobId, this.jsonPadrao.writeValueAsString(representacao.nucleo()), hash, timestamp));
	}

	String buscarStatusComTrava(UUID jobId) {
		return Objects.requireNonNull(
				this.jdbc.queryForObject("SELECT status FROM jobs WHERE id = ? FOR UPDATE", String.class, jobId));
	}

	void atualizarStatusFinalizado(UUID jobId, String status, Timestamp agora) {
		this.jdbc.update("UPDATE jobs SET status = ?, finalizado_em = ? WHERE id = ?", status, agora, jobId);
	}

	void atualizarStatusIniciado(UUID jobId, String status, Timestamp agora) {
		this.jdbc.update("UPDATE jobs SET status = ?, iniciado_em = COALESCE(iniciado_em, ?) WHERE id = ?", status,
				agora, jobId);
	}

	void atualizarStatus(UUID jobId, String status) {
		this.jdbc.update("UPDATE jobs SET status = ? WHERE id = ?", status, jobId);
	}

	UUID inserirTransicao(UUID jobId, @Nullable String origem, String destino, Timestamp agora, String ator,
			@Nullable String motivo) {
		return Objects.requireNonNull(this.jdbc.queryForObject("""
				INSERT INTO job_transicoes (job_id, status_anterior, status_novo, ocorrido_em, ator, motivo)
				VALUES (?, ?, ?, ?, ?, ?)
				RETURNING id
				""", UUID.class, jobId, origem, destino, agora, ator, motivo));
	}

	List<VersaoRegra> buscarRegraPorHash(UUID jobId, String hash) {
		return this.jdbc.query("""
				SELECT id, versao, origem, criada_em FROM regras WHERE job_id = ? AND hash = ?
				""",
				(rs, linha) -> new VersaoRegra(Objects.requireNonNull(rs.getObject("id", UUID.class)),
						rs.getInt("versao"), Objects.requireNonNull(rs.getString("origem")),
						Objects.requireNonNull(rs.getTimestamp("criada_em")).toInstant()),
				jobId, hash);
	}

	/**
	 * {@code parametrosJson} é o artefato bruto da versão de origem, carregado como veio
	 * - {@code null} quando ela não tinha parâmetros, nunca reserializado a partir do
	 * {@link ParametrosDaSimulacao} que produziu {@code hash}. {@code tentativa} só
	 * existe na versão de uma sugestão de taxa nova que a informou.
	 */
	UUID inserirVersaoRegra(UUID jobId, int novaVersao, String origem, @Nullable UUID origemId,
			RepresentacaoRegraDto representacao, @Nullable String parametrosJson, String hash,
			@Nullable Integer tentativa, Timestamp timestamp) {
		return Objects.requireNonNull(this.jdbc.queryForObject("""
				INSERT INTO regras (job_id, versao, origem, regra_origem_id, nucleo, especificacoes, parametros, hash,
				    tentativa, criada_em)
				VALUES (?, ?, ?, ?, ?::jsonb, ?::jsonb, ?::jsonb, ?, ?, ?) RETURNING id
				""", UUID.class, jobId, novaVersao, origem, origemId,
				this.json.writeValueAsString(representacao.nucleo()),
				this.json.writeValueAsString(representacao.especificacoes()), parametrosJson, hash, tentativa,
				timestamp));
	}

	@Nullable Integer buscarMaiorVersao(UUID jobId) {
		return this.jdbc.queryForObject("SELECT COALESCE(MAX(versao), 0) FROM regras WHERE job_id = ?", Integer.class,
				jobId);
	}

	UUID inserirVersaoCorrecao(UUID jobId, int versao, UUID origemId, JsonNode representacao,
			@Nullable String parametros, String hash, Timestamp agora) {
		return Objects.requireNonNull(this.jdbc.queryForObject("""
				INSERT INTO regras (job_id, versao, origem, regra_origem_id, representacao, nucleo,
				    especificacoes, parametros, hash, criada_em)
				VALUES (?, ?, 'correcao', ?, ?::jsonb, ?::jsonb, ?::jsonb, ?::jsonb, ?, ?) RETURNING id
				""", UUID.class, jobId, versao, origemId, representacao.toString(),
				representacao.path("nucleo").toString(), representacao.path("especificacoes").toString(), parametros,
				hash, agora));
	}

	JsonNode buscarRepresentacaoCompleta(UUID regraId) {
		return this.json.readTree(Objects.requireNonNull(this.jdbc.queryForObject(
				"""
						SELECT COALESCE(representacao, jsonb_build_object('nucleo', nucleo, 'especificacoes', especificacoes))::text
						FROM regras WHERE id = ?
						""",
				String.class, regraId)));
	}

	void substituirParametros(UUID jobId, ParametrosDaSimulacao parametros) {
		List<String> competencias = parametros.periodoCanonico();
		if (competencias == null)
			competencias = CompetenciasPublicadas.TODAS;
		this.jdbc.update("UPDATE jobs SET orcamento = ?, meta_venda = ?, competencias = ? WHERE id = ?",
				parametros.orcamento(), parametros.meta_venda(), new SqlArrayValue("text", competencias.toArray()),
				jobId);
	}

	DadosDoJob buscarDadosParaConfirmacao(UUID jobId) {
		return Objects.requireNonNull(this.jdbc.queryForObject("""
				SELECT CASE WHEN j.job_origem_id IS NOT NULL THEN 'reprocessamento' ELSE s.tipo END AS origem,
				       j.orcamento, j.criado_em, j.submissao_id, j.job_origem_id
				FROM jobs j LEFT JOIN submissoes s ON s.id = j.submissao_id
				WHERE j.id = ?
				""",
				(rs, linha) -> new DadosDoJob(Objects.requireNonNull(rs.getString("origem")),
						rs.getBigDecimal("orcamento"), Objects.requireNonNull(rs.getTimestamp("criado_em")).toInstant(),
						rs.getObject("submissao_id", UUID.class), rs.getObject("job_origem_id", UUID.class)),
				jobId));
	}

	List<VersaoAnterior> buscarUltimaVersao(UUID jobId) {
		return this.jdbc.query("""
				SELECT id, versao, hash, nucleo, especificacoes, parametros::text AS parametros
				FROM regras WHERE job_id = ? ORDER BY versao DESC LIMIT 1
				""", (rs, linha) -> new VersaoAnterior(Objects.requireNonNull(rs.getObject("id", UUID.class)),
				rs.getInt("versao"), Objects.requireNonNull(rs.getString("hash")),
				this.json.readValue(Objects.requireNonNull(rs.getString("nucleo")), NucleoRegraDto.class),
				this.json.readTree(Objects.requireNonNull(rs.getString("especificacoes"))).valueStream().toList(),
				rs.getString("parametros")), jobId);
	}

	void atualizarOrcamento(UUID jobId, BigDecimal novo) {
		this.jdbc.update("UPDATE jobs SET orcamento = ? WHERE id = ?", novo, jobId);
	}

	void atualizarNome(UUID jobId, String nome) {
		this.jdbc.update("UPDATE jobs SET nome = ? WHERE id = ?", nome, jobId);
	}

	void atualizarCompetencias(UUID jobId, List<String> novas) {
		this.jdbc.update("UPDATE jobs SET competencias = ? WHERE id = ?", new SqlArrayValue("text", novas.toArray()),
				jobId);
	}

	List<String> buscarCompetencias(UUID jobId) {
		return this.jdbc.queryForList("SELECT unnest(competencias) FROM jobs WHERE id = ?", String.class, jobId);
	}

	void inserirTrilhaConfirmacao(UUID eventoId, UUID jobId, Timestamp timestamp, UUID regraId,
			Map<String, Object> conclusao) {
		this.jdbc.update("""
				INSERT INTO trilhas_auditoria (evento_id, job_id, no, concluido_em, regra_id, conclusao)
				VALUES (?, ?, 'confirmacao', ?, ?, ?::jsonb)
				ON CONFLICT (evento_id) DO NOTHING
				""", eventoId, jobId, timestamp, regraId, this.json.writeValueAsString(conclusao));
	}

	List<UUID> buscarIdUltimaRegra(UUID origemId) {
		return this.jdbc.queryForList("""
				SELECT id FROM regras WHERE job_id = ? ORDER BY versao DESC LIMIT 1
				""", UUID.class, origemId);
	}

	UUID inserirJobReprocessado(String status, UUID usuarioId, UUID origemId, List<String> competencias,
			@Nullable BigDecimal orcamento, @Nullable String nome, Timestamp timestamp) {
		return Objects.requireNonNull(this.jdbc.queryForObject("""
				INSERT INTO jobs (status, usuario_id, job_origem_id, competencias, orcamento, nome, criado_em)
				VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING id
				""", UUID.class, status, usuarioId, origemId, new SqlArrayValue("text", competencias.toArray()),
				orcamento, nome, timestamp));
	}

	/**
	 * {@code parametros} é copiado junto com {@code hash}, ambos pelo próprio banco: o
	 * hash da versão de origem foi calculado cobrindo os parâmetros que ela tinha, e
	 * copiar só um dos dois deixaria a versão nova com um hash que não corresponde ao seu
	 * próprio conteúdo.
	 */
	RegraCriadaDto copiarRegra(UUID jobId, UUID regraId, Timestamp timestamp, Instant agora) {
		return Objects.requireNonNull(this.jdbc.queryForObject("""
				INSERT INTO regras (job_id, versao, origem, regra_origem_id, nucleo, especificacoes, parametros, hash,
				    criada_em)
				SELECT ?, 1, 'reprocessamento', id, nucleo, especificacoes, parametros, hash, ?
				FROM regras WHERE id = ?
				RETURNING id, nucleo, especificacoes
				""", (rs, linha) -> new RegraCriadaDto(Objects.requireNonNull(rs.getObject("id", UUID.class)), 1,
				"reprocessamento",
				new RepresentacaoRegraDto(
						this.json.readValue(Objects.requireNonNull(rs.getString("nucleo")), NucleoRegraDto.class),
						this.json.readTree(Objects.requireNonNull(rs.getString("especificacoes")))
							.valueStream()
							.toList()),
				agora), jobId, timestamp, regraId));
	}

	List<JobDeOrigem> buscarJobDeOrigem(UUID jobId) {
		return this.jdbc.query("""
				SELECT status, usuario_id, competencias, orcamento, nome FROM jobs WHERE id = ?
				""",
				(rs, linha) -> new JobDeOrigem(JobStatus.deColuna(Objects.requireNonNull(rs.getString("status"))),
						Objects.requireNonNull(rs.getObject("usuario_id", UUID.class)),
						List.of((String[]) rs.getArray("competencias").getArray()), rs.getBigDecimal("orcamento"),
						rs.getString("nome")),
				jobId);
	}

	void inserirAcao(UUID jobId, String acao, Timestamp executadoEm) {
		this.jdbc.update("""
				INSERT INTO job_acoes (job_id, acao, executado_em) VALUES (?, ?, ?)
				""", jobId, acao, executadoEm);
	}

	void exigirJobExistente(UUID jobId) {
		this.jdbc.queryForObject("SELECT id FROM jobs WHERE id = ?", UUID.class, jobId);
	}

	/**
	 * {@code ON CONFLICT DO NOTHING} sem alvo cobre tanto a reentrega (mesmo
	 * {@code codigo_gerado_id}, índice único {@code uq_simulacoes_codigo_gerado_id})
	 * quanto um {@code resultado_id} já amarrado a outra linha - os dois casos não
	 * escrevem de novo, e a leitura seguinte por {@code codigo_gerado_id} devolve a linha
	 * que existe.
	 */
	UUID registrarSimulacao(UUID jobId, UUID regraId, UUID codigoGeradoId, @Nullable UUID simulacaoId,
			Instant concluidoEm) {
		this.jdbc.update(
				"""
						INSERT INTO simulacoes (id, criado_em, regra_id, job_id, codigo_gerado_id, resultado_id)
						VALUES (COALESCE(?, uuidv7()), ?, ?, ?, ?,
							(SELECT id FROM resultados_simulacao WHERE job_id = ? AND codigo_gerado_id = ? AND proposito = 'simulacao'
								ORDER BY criado_em DESC, id DESC LIMIT 1))
						ON CONFLICT DO NOTHING
						""",
				simulacaoId, Timestamp.from(concluidoEm), regraId, jobId, codigoGeradoId, jobId, codigoGeradoId);
		return Objects.requireNonNull(this.jdbc.queryForObject("SELECT id FROM simulacoes WHERE codigo_gerado_id = ?",
				UUID.class, codigoGeradoId));
	}

	/**
	 * Falso quando a linha já existia: a reentrega do mesmo {@code evento_id} não grava
	 * de novo, e quem chama não anuncia de novo o que ela registrou.
	 */
	boolean inserirTrilhaNo(UUID eventoId, UUID jobId, @Nullable UUID simulacaoId, EtapaDoGrafo no,
			NoConcluidoDto evento) {
		return this.jdbc.update(
				"""
						INSERT INTO trilhas_auditoria
							(evento_id, job_id, simulacao_id, no, concluido_em, regra_id, conclusao, prompt_id, codigo_gerado_id, explicacao_id)
						VALUES (?, ?, ?, ?, ?, ?, ?::jsonb, ?, ?, ?)
						ON CONFLICT (evento_id) DO NOTHING
						""",
				eventoId, jobId, simulacaoId, no.paraEvento(),
				Timestamp.from(Objects.requireNonNull(evento.concluido_em())), evento.regra_id(),
				Objects.requireNonNull(evento.conclusao()).toString(), evento.prompt_id(), evento.codigo_gerado_id(),
				evento.explicacao_id()) == 1;
	}

	void bloquearJob(UUID jobId) {
		this.jdbc.queryForList("SELECT id FROM jobs WHERE id = ? FOR UPDATE", jobId);
	}

	/**
	 * A origem da versão que produziu o resultado, quando ela ainda é a versão atual do
	 * job; vazio quando o resultado não é do job ou já existe versão mais nova. É o que
	 * distingue a alternativa de uma sugestão da regra que o usuário pediu.
	 */
	List<String> origemDaVersaoAtualDoResultado(UUID jobId, UUID resultadoId) {
		return this.jdbc.queryForList("""
				SELECT r.origem FROM resultados_simulacao rs
				JOIN codigos_gerados c ON c.id = rs.codigo_gerado_id AND c.job_id = rs.job_id
				JOIN regras r ON r.id = c.regra_id AND r.job_id = rs.job_id
				WHERE rs.id = ? AND rs.job_id = ? AND rs.proposito = 'simulacao'
				  AND NOT EXISTS (SELECT 1 FROM regras nova WHERE nova.job_id = r.job_id
				      AND nova.versao > r.versao)
				""", String.class, resultadoId, jobId);
	}

	/**
	 * O resultado inviável da versão atual do job quando ela é uma alternativa de
	 * sugestão: vazio fora disso. Só o resultado da simulação conta, nunca uma execução
	 * candidata da busca da meta, e o mais recente vem primeiro.
	 */
	List<UUID> buscarResultadoInviavelDaAlternativaAtual(UUID jobId) {
		return this.jdbc.queryForList("""
				SELECT rs.id FROM regras r
				JOIN codigos_gerados c ON c.regra_id = r.id AND c.job_id = r.job_id
				JOIN resultados_simulacao rs ON rs.codigo_gerado_id = c.id AND rs.job_id = r.job_id
				WHERE r.job_id = ? AND r.origem = 'sugestao_adaptacao'
				  AND NOT EXISTS (SELECT 1 FROM regras nova WHERE nova.job_id = r.job_id
				      AND nova.versao > r.versao)
				  AND rs.status = 'sucesso' AND rs.veredito = 'inviavel' AND rs.proposito = 'simulacao'
				ORDER BY rs.criado_em DESC, rs.id DESC
				""", UUID.class, jobId);
	}

	List<UUID> vincularResultado(UUID jobId, UUID resultadoId) {
		return this.jdbc.query("""
				UPDATE simulacoes s SET resultado_id = r.id
				FROM resultados_simulacao r
				WHERE r.id = ? AND r.job_id = ? AND s.job_id = r.job_id
				  AND s.codigo_gerado_id = r.codigo_gerado_id AND s.resultado_id IS NULL AND r.proposito = 'simulacao'
				RETURNING s.id
				""", (linha, numero) -> linha.getObject("id", UUID.class), resultadoId, jobId);
	}

	List<ContextoDoJob> buscarContextoComTrava(UUID jobId) {
		return this.jdbc.query("""
				SELECT j.status, j.competencias, j.orcamento, j.meta_venda, j.submissao_id,
				       CASE WHEN j.job_origem_id IS NOT NULL THEN 'reprocessamento' ELSE s.tipo END AS origem
				FROM jobs j LEFT JOIN submissoes s ON s.id = j.submissao_id
				WHERE j.id = ? FOR UPDATE OF j
				""",
				(rs, numero) -> new ContextoDoJob(jobId, JobStatus.deColuna(rs.getString("status")),
						rs.getString("origem"), List.of((String[]) rs.getArray("competencias").getArray()),
						rs.getBigDecimal("orcamento"), rs.getBigDecimal("meta_venda"),
						rs.getObject("submissao_id", UUID.class)),
				jobId);
	}

	List<ExtracaoDaRegra> buscarExtracao(UUID extracaoId) {
		return this.jdbc.query("""
				SELECT job_id, submissao_id, representacao::text AS representacao, parametros::text AS parametros
				FROM extracoes_regras WHERE id = ?
				""",
				(rs, numero) -> new ExtracaoDaRegra(Objects.requireNonNull(rs.getObject("job_id", UUID.class)),
						Objects.requireNonNull(rs.getObject("submissao_id", UUID.class)),
						Objects.requireNonNull(rs.getString("representacao")),
						Objects.requireNonNull(rs.getString("parametros"))),
				extracaoId);
	}

	/**
	 * A versão raiz e os parâmetros com que ela nasceu, copiados de
	 * {@code extracoes_regras} pelo próprio banco: a api não reescreve o artefato do
	 * codegen. {@code parametros} é {@code NOT NULL} na origem, com default {@code '{}'},
	 * então a versão da extração nunca nasce com a coluna nula.
	 */
	UUID inserirVersaoDaExtracao(UUID jobId, int novaVersao, UUID extracaoId, String hash, Timestamp timestamp) {
		return Objects.requireNonNull(this.jdbc.queryForObject("""
				INSERT INTO regras
					(job_id, versao, origem, regra_origem_id, nucleo, especificacoes, parametros, hash, criada_em)
				SELECT ?, ?, ?, NULL, e.representacao -> 'nucleo', e.representacao -> 'especificacoes',
				       e.parametros, ?, ?
				FROM extracoes_regras e WHERE e.id = ?
				RETURNING id
				""", UUID.class, jobId, novaVersao, VersoesDaRegra.ORIGEM_EXTRACAO, hash, timestamp, extracaoId));
	}

	void atualizarMetaVenda(UUID jobId, BigDecimal nova) {
		this.jdbc.update("UPDATE jobs SET meta_venda = ? WHERE id = ?", nova, jobId);
	}

	boolean registrarMetaSugerida(MetaVendaSugeridaDto evento) {
		return this.jdbc.update(
				"""
						INSERT INTO sugestoes_meta_venda (job_id, regra_id, resultado_id, motivo_sem_solucao)
						SELECT r.job_id, r.id, ?, ? FROM regras r
						JOIN jobs j ON j.id = r.job_id
						WHERE r.job_id = ? AND r.id = ? AND j.status IN ('gerando_regra', 'simulando', 'aguardando_decisao_usuario')
						  AND NOT EXISTS (SELECT 1 FROM regras nova WHERE nova.job_id = r.job_id AND nova.versao > r.versao)
						  AND ( ?::uuid IS NULL OR EXISTS (
						      SELECT 1 FROM resultados_simulacao rs JOIN codigos_gerados c ON c.id = rs.codigo_gerado_id
						      WHERE rs.id = ? AND rs.job_id = r.job_id AND c.job_id = r.job_id AND c.regra_id = r.id
						        AND rs.proposito = 'busca_meta' AND rs.status = 'sucesso' AND rs.meta_venda = ?
						        AND rs.meta_venda > COALESCE(j.meta_venda, (rs.totais ->> 'vendas_historicas')::numeric)
						        AND rs.veredito = 'viavel'
						        AND (rs.totais ->> 'orcamento')::numeric = j.orcamento
						        AND (rs.totais ->> 'simulado')::numeric <= (rs.totais ->> 'orcamento')::numeric
						  ))
						ON CONFLICT (job_id, regra_id) DO NOTHING
						""",
				evento.resultado_id(), evento.sem_solucao() == null ? null : evento.sem_solucao().motivo(),
				evento.job_id(), evento.regra_id(), evento.resultado_id(), evento.resultado_id(),
				evento.meta_venda()) == 1;
	}

	/**
	 * A busca da meta maior está em curso quando a decisão sobre a versão atual a abriu,
	 * pelo {@code encaminhamento} que ela grava na trilha, e ainda não terminou. Termina
	 * com a meta sugerida registrada ou com a decisão que o codegen grava ao fechá-la,
	 * uma linha posterior da mesma versão; a segunda cobre a meta que a api descarta e
	 * não registra. Só vale com o job aguardando a decisão do usuário: fora disso, ou ele
	 * ainda não chegou ao resultado, ou já saiu dele.
	 */
	boolean buscaMetaEmCurso(UUID jobId) {
		return Boolean.TRUE.equals(this.jdbc.queryForObject("""
				SELECT EXISTS (
				    SELECT 1
				    FROM trilhas_auditoria t
				    JOIN jobs j ON j.id = t.job_id
				    JOIN regras r ON r.id = t.regra_id
				    WHERE t.job_id = ? AND t.no = ? AND t.conclusao ->> 'encaminhamento' = ?
				      AND j.status = 'aguardando_decisao_usuario'
				      AND NOT EXISTS (SELECT 1 FROM regras nova WHERE nova.job_id = r.job_id AND nova.versao > r.versao)
				      AND NOT EXISTS (
				          SELECT 1 FROM sugestoes_meta_venda m WHERE m.job_id = t.job_id AND m.regra_id = t.regra_id
				      )
				      AND NOT EXISTS (
				          SELECT 1 FROM trilhas_auditoria fim
				          WHERE fim.job_id = t.job_id AND fim.regra_id = t.regra_id AND fim.no = t.no
				            AND fim.id <> t.id AND fim.concluido_em >= t.concluido_em
				      )
				)
				""", Boolean.class, jobId, EtapaDoGrafo.DECISAO.paraEvento(), ENCAMINHAMENTO_BUSCA_META));
	}

	@Nullable MetaSugeridaDto buscarMetaSugerida(UUID jobId) {
		List<MetaSugeridaDto> sugestoes = this.jdbc.query("""
				SELECT rs.meta_venda, (rs.totais ->> 'simulado')::numeric AS total_simulado,
				    (rs.totais ->> 'orcamento')::numeric AS orcamento, m.motivo_sem_solucao
				FROM sugestoes_meta_venda m
				JOIN regras r ON r.id = m.regra_id
				LEFT JOIN resultados_simulacao rs ON rs.id = m.resultado_id
				WHERE m.job_id = ? AND m.aceita_em IS NULL
				  AND NOT EXISTS (SELECT 1 FROM regras nova WHERE nova.job_id = r.job_id AND nova.versao > r.versao)
				""",
				(rs, numero) -> new MetaSugeridaDto(rs.getBigDecimal("meta_venda"), rs.getBigDecimal("total_simulado"),
						rs.getBigDecimal("orcamento"), rs.getString("motivo_sem_solucao") == null ? null
								: new SemSolucaoDto(rs.getString("motivo_sem_solucao"))),
				jobId);
		return sugestoes.isEmpty() ? null : sugestoes.getFirst();
	}

	boolean aceitarMetaSugerida(UUID jobId) {
		int atualizadas = this.jdbc.update("""
				UPDATE simulacoes s SET resultado_id = m.resultado_id
				FROM sugestoes_meta_venda m, resultados_simulacao rs, regras r
				WHERE m.job_id = ? AND m.aceita_em IS NULL AND m.resultado_id = rs.id
				  AND r.id = m.regra_id AND s.job_id = m.job_id AND s.regra_id = m.regra_id
				  AND s.codigo_gerado_id = rs.codigo_gerado_id AND s.resultado_id IS NOT NULL
				  AND rs.proposito = 'busca_meta' AND rs.status = 'sucesso'
				  AND s.id = (SELECT vigente.id FROM simulacoes vigente WHERE vigente.job_id = s.job_id
				      ORDER BY vigente.criado_em DESC, vigente.id DESC LIMIT 1)
				  AND NOT EXISTS (SELECT 1 FROM regras nova WHERE nova.job_id = r.job_id AND nova.versao > r.versao)
				""", jobId);
		if (atualizadas == 0) {
			return false;
		}
		this.jdbc.update("""
				UPDATE sugestoes_meta_venda m SET aceita_em = now()
				WHERE job_id = ? AND aceita_em IS NULL AND resultado_id IS NOT NULL
				  AND EXISTS (SELECT 1 FROM simulacoes s WHERE s.job_id = m.job_id AND s.resultado_id = m.resultado_id)
				""", jobId);
		return true;
	}

	/**
	 * Os parâmetros da versão {@code regraId}, como {@code jsonb::text} - vazio quando a
	 * versão não existe, com um elemento {@code null} quando ela existe e a coluna é
	 * nula. É o que permite ao chamador carregar os mesmos parâmetros para a versão nova
	 * sem reescrevê-los, e calcular o hash com eles sem lançar numa referência que não
	 * exista mais.
	 */
	List<String> buscarParametrosDaVersao(UUID regraId) {
		return this.jdbc.queryForList("SELECT parametros::text FROM regras WHERE id = ?", String.class, regraId);
	}

	List<String> buscarParametrosDaVersao(UUID jobId, UUID regraId) {
		return this.jdbc.queryForList("SELECT parametros::text FROM regras WHERE job_id = ? AND id = ?", String.class,
				jobId, regraId);
	}

	/**
	 * A proposta parte da versão atual do job - a regra original ou a alternativa
	 * anterior - e do resultado inviável dela, muda só o percentual, para menos, e não
	 * repete uma versão do job. A reentrega encontra a versão que a primeira entrega
	 * criou e é recusada aqui. A api não conta tentativas: o limite é do codegen.
	 */
	@Nullable Boolean sugestaoElegivel(UUID jobId, UUID regraOrigemId, UUID resultadoId, String hash, BigDecimal percentual,
			RepresentacaoRegraDto representacao) {
		return this.jdbc.queryForObject("""
				SELECT EXISTS (
				    SELECT 1 FROM regras r
				    JOIN codigos_gerados c ON c.regra_id = r.id AND c.job_id = r.job_id
				    JOIN resultados_simulacao rs ON rs.codigo_gerado_id = c.id AND rs.job_id = r.job_id
				    WHERE r.id = ? AND r.job_id = ? AND rs.id = ?
				      AND rs.status = 'sucesso' AND rs.veredito = 'inviavel' AND rs.proposito = 'simulacao'
				      AND NOT EXISTS (SELECT 1 FROM regras outra WHERE outra.job_id = r.job_id
				          AND (outra.versao > r.versao OR outra.hash = ?))
				      AND (r.nucleo->>'percentual')::numeric > ?
				      AND r.nucleo - 'percentual' = ?::jsonb - 'percentual'
				      AND r.especificacoes = ?::jsonb
				)
				""", Boolean.class, regraOrigemId, jobId, resultadoId, hash, percentual,
				this.jsonPadrao.writeValueAsString(representacao.nucleo()),
				this.jsonPadrao.writeValueAsString(representacao.especificacoes()));
	}

	List<UUID> buscarSimulacaoPorResultado(UUID jobId, UUID resultadoId) {
		return this.jdbc.query("SELECT id FROM simulacoes WHERE job_id = ? AND resultado_id = ?",
				(rs, numero) -> rs.getObject("id", UUID.class), jobId, resultadoId);
	}

	record DadosConsulta(UUID id, String status, String origem, List<String> competencias,
			@Nullable BigDecimal orcamento, @Nullable BigDecimal metaVenda, Instant criadoEm,
			@Nullable Instant iniciadoEm, @Nullable Instant finalizadoEm, @Nullable UUID submissaoId,
			@Nullable UUID jobOrigemId, @Nullable String motivoDaTrilha, String regrasJson, @Nullable String nome) {
	}

	record DadosDoJob(String origem, @Nullable BigDecimal orcamento, Instant criadoEm, @Nullable UUID submissaoId,
			@Nullable UUID jobOrigemId) {
	}

	record VersaoAnterior(UUID id, int versao, String hash, NucleoRegraDto nucleo, List<JsonNode> especificacoes,
			@Nullable String parametros) {
	}

	record JobDeOrigem(JobStatus status, UUID usuarioId, List<String> competencias, @Nullable BigDecimal orcamento,
			@Nullable String nome) {
	}

	/**
	 * O que o {@code regra-submetida} de um ciclo novo repete do job. Lido sob trava da
	 * linha do job, para que a decisão de reabrir o ciclo e o status em que ela se baseia
	 * não corram com outra transição.
	 */
	record ContextoDoJob(UUID jobId, JobStatus status, String origem, List<String> competencias,
			@Nullable BigDecimal orcamento, @Nullable BigDecimal metaVenda, @Nullable UUID submissaoId) {

		RegraSubmetidaDto regraSubmetida(UUID regraId) {
			return new RegraSubmetidaDto(this.jobId, this.origem, this.competencias, this.orcamento, this.metaVenda,
					this.submissaoId, regraId);
		}

		/**
		 * O contexto como o job fica depois de receber os parâmetros extraídos: o que a
		 * extração trouxe substitui, e o que ela não trouxe permanece. É o que o
		 * {@code regra-submetida} republicado precisa levar, porque ele repete os valores
		 * do job, não os do evento anterior.
		 */
		ContextoDoJob com(ParametrosDaSimulacao parametros) {
			List<String> periodo = parametros.periodoCanonico();
			BigDecimal orcamentoDito = parametros.orcamento();
			BigDecimal metaDita = parametros.meta_venda();
			return new ContextoDoJob(this.jobId, this.status, this.origem,
					(periodo != null) ? periodo : this.competencias,
					(orcamentoDito != null) ? orcamentoDito : this.orcamento,
					(metaDita != null) ? metaDita : this.metaVenda, this.submissaoId);
		}

	}

	record ExtracaoDaRegra(UUID jobId, UUID submissaoId, String representacao, String parametros) {
	}

}
