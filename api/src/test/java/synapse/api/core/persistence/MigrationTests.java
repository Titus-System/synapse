package synapse.api.core.persistence;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import liquibase.Contexts;
import liquibase.LabelExpression;
import liquibase.Liquibase;
import liquibase.database.Database;
import liquibase.database.DatabaseFactory;
import liquibase.database.jvm.JdbcConnection;
import liquibase.resource.ClassLoaderResourceAccessor;
import org.jspecify.annotations.Nullable;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIf;
import org.testcontainers.DockerClientFactory;
import org.testcontainers.postgresql.PostgreSQLContainer;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * O changelog roda contra um Postgres de verdade, na mesma major que o compose: o
 * {@code uuidv7()} e o índice parcial não existem num banco em memória.
 */
@EnabledIf("dockerIsAvailable")
class MigrationTests {

	private static final String CHANGELOG = "db/changelog/changelog.yaml";

	private static final List<String> TABELAS = List.of("usuarios", "submissoes", "jobs", "job_transicoes", "job_acoes",
			"regras", "prompts", "respostas_modelo", "codigos_gerados", "resultados_simulacao", "explicacoes",
			"simulacoes", "trilhas_auditoria", "outbox_events", "jobs_grafo_encerrados", "extracoes_regras");

	private static final int CHANGESETS = 22;

	private static final int CHANGESETS_ANTES_DO_NOME = 19;

	/** Os changesets até o 015, o banco como estava antes da coluna de diagnóstico. */
	private static final int CHANGESETS_ANTES_DO_DIAGNOSTICO = 16;

	private static final String JOB_ID = "11111111-1111-4111-8111-111111111111";

	private static final String CODIGO_ID = "33333333-3333-4333-8333-333333333333";

	/**
	 * As colunas que o worker grava hoje, sem {@code diagnostico}: é o INSERT de quem
	 * ainda não conhece a coluna.
	 */
	private static final String INSERE_RESULTADO_COMO_O_WORKER = """
			INSERT INTO resultados_simulacao
			    (job_id, codigo_gerado_id, status, totais, veredito, assercoes, decomposicao, criado_em)
			VALUES
			    ('%s', '%s', 'sucesso', '{"baseline": 100.0, "simulado": 90.0}'::jsonb, 'viavel',
			     '[{"nome": "sem_comissao_negativa", "resultado": "ok", "detalhe": null}]'::jsonb,
			     '{"loja": {"13": -10.0}}'::jsonb, now())
			RETURNING id::text
			""".formatted(JOB_ID, CODIGO_ID);

	private static PostgreSQLContainer postgres;

	static boolean dockerIsAvailable() {
		return DockerClientFactory.instance().isDockerAvailable();
	}

	@BeforeAll
	static void subirOPostgres() {
		postgres = new PostgreSQLContainer("postgres:18-alpine");
		postgres.start();
	}

	@AfterAll
	static void derrubarOPostgres() {
		if (postgres != null) {
			postgres.stop();
		}
	}

	/**
	 * O container é um só e o teste de rollback derruba tudo: cada teste parte de um
	 * banco limpo em vez de herdar o estado do anterior.
	 */
	@BeforeEach
	void zerarOBanco() throws Exception {
		try (Connection connection = abrir(); Statement statement = connection.createStatement()) {
			statement.execute("DROP SCHEMA public CASCADE");
			statement.execute("CREATE SCHEMA public");
		}
	}

	@Test
	void aplicaOChangelogECriaAsTabelasDoModelo() throws Exception {
		atualizar();

		assertThat(tabelasExistentes()).containsExactlyInAnyOrderElementsOf(TABELAS);
	}

	@Test
	void criaOsDoisIndicesQueODbmlNaoExpressa() throws Exception {
		atualizar();

		assertThat(definicaoDoIndice("idx_jobs_usuario_id_criado_em")).contains("criado_em DESC");
		assertThat(definicaoDoIndice("idx_outbox_events_criado_em_pendentes")).contains("WHERE (publicado_em IS NULL)");
	}

	@Test
	void criaExtracaoImutavelComConteudoJsonbEIdentidadePorSubmissao() throws Exception {
		atualizar();

		try (Connection connection = abrir();
				Statement statement = connection.createStatement();
				ResultSet rs = statement.executeQuery("""
						SELECT column_name, data_type, is_nullable FROM information_schema.columns
						WHERE table_name = 'extracoes_regras' ORDER BY ordinal_position
						""")) {
			List<String> colunas = new ArrayList<>();
			while (rs.next()) {
				colunas.add(rs.getString("column_name") + ":" + rs.getString("data_type"));
				assertThat(rs.getString("is_nullable")).isEqualTo("NO");
			}
			assertThat(colunas).containsExactly("id:uuid", "job_id:uuid", "submissao_id:uuid", "resposta_id:uuid",
					"representacao:jsonb", "rebaixamentos:jsonb", "criado_em:timestamp with time zone");
		}
		assertThat(definicaoDoIndice("uq_extracoes_regras_job_id_submissao_id")).contains("UNIQUE",
				"(job_id, submissao_id)");
	}

	@Test
	void subirDeNovoNaoReaplicaOChangeset() throws Exception {
		atualizar();
		int aplicadosNaPrimeira = changesetsAplicados();

		atualizar();

		assertThat(aplicadosNaPrimeira).isEqualTo(CHANGESETS);
		assertThat(changesetsAplicados()).isEqualTo(aplicadosNaPrimeira);
	}

	@Test
	void oRollbackDeclaradoDesfazACriacao() throws Exception {
		atualizar();

		reverter(CHANGESETS);

		assertThat(tabelasExistentes()).isEmpty();
	}

	@Test
	void criaODiagnosticoComoJsonbQueAceitaNulo() throws Exception {
		atualizar();

		try (Connection connection = abrir();
				Statement statement = connection.createStatement();
				ResultSet rs = statement.executeQuery("""
						SELECT data_type, is_nullable FROM information_schema.columns
						WHERE table_name = 'resultados_simulacao' AND column_name = 'diagnostico'
						""")) {
			assertThat(rs.next()).as("coluna diagnostico não existe").isTrue();
			assertThat(rs.getString("data_type")).isEqualTo("jsonb");
			assertThat(rs.getString("is_nullable")).isEqualTo("YES");
		}
	}

	@Test
	void criaLinhasComoJsonbNulavelSemValorPadrao() throws Exception {
		atualizar();

		try (Connection connection = abrir();
				Statement statement = connection.createStatement();
				ResultSet rs = statement.executeQuery("""
						SELECT data_type, is_nullable, column_default FROM information_schema.columns
						WHERE table_schema = 'public' AND table_name = 'resultados_simulacao' AND column_name = 'linhas'
						""")) {
			assertThat(rs.next()).as("coluna linhas não existe").isTrue();
			assertThat(rs.getString("data_type")).isEqualTo("jsonb");
			assertThat(rs.getString("is_nullable")).isEqualTo("YES");
			assertThat(rs.getString("column_default")).isNull();
		}
	}

	@Test
	void preservaResultadosExistentesESemDetalhamentoAoMigrarEReverter() throws Exception {
		atualizar(21);
		String anterior;
		String linhaAntes;
		try (Connection connection = abrir(); Statement statement = connection.createStatement()) {
			semearCodigoGerado(statement);
			anterior = inserirComoOWorker(statement);
			linhaAntes = linhaSemDiagnostico(statement, anterior);
		}

		atualizar();

		try (Connection connection = abrir(); Statement statement = connection.createStatement()) {
			String posterior = inserirComoOWorker(statement);
			assertThat(linhaSemDiagnostico(statement, anterior)).isEqualTo(linhaAntes);
			try (ResultSet rs = statement.executeQuery("SELECT linhas FROM resultados_simulacao")) {
				assertThat(rs.next()).isTrue();
				assertThat(rs.getString("linhas")).isNull();
				assertThat(rs.next()).isTrue();
				assertThat(rs.getString("linhas")).isNull();
				assertThat(rs.next()).isFalse();
			}
			assertThat(linhaSemDiagnostico(statement, posterior)).isNotEmpty();
		}

		reverter(1);

		assertThat(colunasDeResultados()).doesNotContain("linhas").contains("diagnostico", "decomposicao");
		try (Connection connection = abrir(); Statement statement = connection.createStatement()) {
			assertThat(linhaSemDiagnostico(statement, anterior)).isEqualTo(linhaAntes);
		}
	}

	@Test
	void criaONomeComoTextoNulavelSemValorPadrao() throws Exception {
		atualizar();

		try (Connection connection = abrir();
				Statement statement = connection.createStatement();
				ResultSet rs = statement.executeQuery("""
						SELECT data_type, is_nullable, column_default FROM information_schema.columns
						WHERE table_schema = 'public' AND table_name = 'jobs' AND column_name = 'nome'
						""")) {
			assertThat(rs.next()).as("coluna nome não existe").isTrue();
			assertThat(rs.getString("data_type")).isEqualTo("text");
			assertThat(rs.getString("is_nullable")).isEqualTo("YES");
			assertThat(rs.getString("column_default")).isNull();
		}
	}

	@Test
	void preservaJobsExistentesEInsercoesSemNomeAoMigrarEReverter() throws Exception {
		atualizar(CHANGESETS_ANTES_DO_NOME);
		UUID anterior = UUID.randomUUID();
		UUID posterior = UUID.randomUUID();
		String linhaAntes;
		try (Connection connection = abrir(); Statement statement = connection.createStatement()) {
			semearUsuario(statement);
			semearJobComTrilha(statement, anterior, "gerando_regra");
			linhaAntes = linhaDoJobSemNome(statement, anterior);
		}

		atualizar();

		try (Connection connection = abrir(); Statement statement = connection.createStatement()) {
			semearJobComTrilha(statement, posterior, "gerando_regra");
			assertThat(linhaDoJobSemNome(statement, anterior)).isEqualTo(linhaAntes);
			try (ResultSet rs = statement.executeQuery("SELECT nome FROM jobs")) {
				assertThat(rs.next()).isTrue();
				assertThat(rs.getString("nome")).isNull();
				assertThat(rs.next()).isTrue();
				assertThat(rs.getString("nome")).isNull();
				assertThat(rs.next()).isFalse();
			}
		}

		reverter(CHANGESETS - CHANGESETS_ANTES_DO_NOME);

		assertThat(nulidadeDasColunas("jobs")).doesNotContainKey("nome");
		try (Connection connection = abrir(); Statement statement = connection.createStatement()) {
			assertThat(linhaDoJobSemNome(statement, anterior)).isEqualTo(linhaAntes);
			assertThat(linhaDoJobSemNome(statement, posterior)).isNotEmpty();
		}
	}

	/**
	 * O banco já em uso recebe a coluna sem perder nada: o resultado gravado antes fica
	 * como estava, com o diagnóstico nulo, e o INSERT do worker que ainda não conhece a
	 * coluna continua funcionando depois dela.
	 */
	@Test
	void resultadoGravadoAntesDoDiagnosticoChegaIntactoEComEleNulo() throws Exception {
		atualizar(CHANGESETS_ANTES_DO_DIAGNOSTICO);
		String anterior;
		String linhaAntes;
		try (Connection connection = abrir(); Statement statement = connection.createStatement()) {
			semearCodigoGerado(statement);
			anterior = inserirComoOWorker(statement);
			linhaAntes = linhaSemDiagnostico(statement, anterior);
		}

		atualizar();

		try (Connection connection = abrir(); Statement statement = connection.createStatement()) {
			String posterior = inserirComoOWorker(statement);

			assertThat(linhaSemDiagnostico(statement, anterior)).isEqualTo(linhaAntes);
			assertThat(diagnostico(statement, anterior)).isNull();
			assertThat(diagnostico(statement, posterior)).isNull();
		}
	}

	@Test
	void oRollbackDoDiagnosticoRemoveSoAColuna() throws Exception {
		atualizar(CHANGESETS_ANTES_DO_DIAGNOSTICO + 1);

		reverter(1);

		assertThat(colunasDeResultados()).doesNotContain("diagnostico").contains("decomposicao");
		assertThat(tabelasExistentes()).contains("resultados_simulacao");
	}

	@Test
	void criaORegistroDeEncerramentosComLimpezaNulavelEIndiceDasPendentes() throws Exception {
		atualizar();

		assertThat(nulidadeDasColunas("jobs_grafo_encerrados")).containsEntry("job_id", "NO")
			.containsEntry("evento_id", "NO")
			.containsEntry("status", "NO")
			.containsEntry("encerrado_em", "NO")
			.containsEntry("limpo_em", "YES");
		assertThat(definicaoDoIndice("uq_jobs_grafo_encerrados_job_id")).contains("UNIQUE");
		assertThat(definicaoDoIndice("idx_jobs_grafo_encerrados_pendentes")).contains("WHERE (limpo_em IS NULL)");
	}

	/**
	 * Os jobs que encerraram antes de existir {@code job-encerrado} recebem o evento com
	 * o id e o instante da transição terminal já gravada; quem já tem o evento não ganha
	 * outro, e quem não encerrou não ganha nenhum.
	 */
	@Test
	void encerramentosAnterioresEntramNoOutboxComOIdEOInstanteDaTransicaoTerminal() throws Exception {
		atualizar(CHANGESETS_ANTES_DO_DIAGNOSTICO);
		UUID liberado = UUID.randomUUID();
		UUID jaAnunciado = UUID.randomUUID();
		UUID emAndamento = UUID.randomUUID();
		UUID transicaoTerminal;
		try (Connection connection = abrir(); Statement statement = connection.createStatement()) {
			semearUsuario(statement);
			semearJobComTrilha(statement, liberado, "liberado", "gerando_regra", "simulando",
					"aguardando_decisao_usuario", "liberado");
			semearJobComTrilha(statement, jaAnunciado, "cancelado", "aguardando_confirmacao_parametros", "cancelado");
			statement.execute("""
					INSERT INTO outbox_events (job_id, tipo, payload, criado_em)
					VALUES ('%s', 'job-encerrado', '{"ja": "publicado"}'::jsonb, now())
					""".formatted(jaAnunciado));
			semearJobComTrilha(statement, emAndamento, "simulando", "gerando_regra", "simulando");
			transicaoTerminal = idDaTransicao(statement, liberado, "liberado");
		}

		atualizar();

		try (Connection connection = abrir(); Statement statement = connection.createStatement()) {
			List<String> doLiberado = encerramentosNoOutbox(statement, liberado);
			assertThat(doLiberado).hasSize(1);
			String evento = doLiberado.get(0);
			assertThat(evento).contains("\"evento_id\": \"" + transicaoTerminal + "\"")
				.contains("\"job_id\": \"" + liberado + "\"")
				.contains("\"status\": \"liberado\"")
				.contains("\"encerrado_em\": \"2025-11-28T15:02:44.318204Z\"");
			assertThat(encerramentosNoOutbox(statement, jaAnunciado)).containsExactly("{\"ja\": \"publicado\"}");
			assertThat(encerramentosNoOutbox(statement, emAndamento)).isEmpty();
			try (ResultSet rs = statement
				.executeQuery("SELECT count(*) FROM job_transicoes WHERE job_id = '%s'".formatted(liberado))) {
				rs.next();
				assertThat(rs.getInt(1)).as("o registro não cria transição").isEqualTo(4);
			}
		}
	}

	@Test
	void idOmitidoNasceUuidV7EIdFornecidoEPreservado() throws Exception {
		atualizar();

		try (Connection connection = abrir(); Statement statement = connection.createStatement()) {
			statement.execute("""
					INSERT INTO usuarios (login, senha_hash, nome, papel, criado_em)
					VALUES ('omitido', 'x', 'Omitido', 'auditor', now())
					""");
			statement.execute("""
					INSERT INTO usuarios (id, login, senha_hash, nome, papel, criado_em)
					VALUES ('11111111-1111-4111-8111-111111111111', 'fornecido', 'x', 'Fornecido',
					        'auditor', now())
					""");

			try (ResultSet rs = statement.executeQuery("""
					SELECT login, id::text AS id, uuid_extract_version(id) AS versao
					FROM usuarios ORDER BY login
					""")) {
				assertThat(rs.next()).isTrue();
				assertThat(rs.getString("login")).isEqualTo("fornecido");
				assertThat(rs.getString("id")).isEqualTo("11111111-1111-4111-8111-111111111111");
				assertThat(rs.getInt("versao")).isEqualTo(4);

				assertThat(rs.next()).isTrue();
				assertThat(rs.getString("login")).isEqualTo("omitido");
				assertThat(rs.getInt("versao")).isEqualTo(7);
			}
		}
	}

	// Liquibase.close() fecha a conexão JDBC por baixo, então cada operação abre a sua
	// em vez de compartilhar uma com as afirmações.
	private static void atualizar() throws Exception {
		try (Connection connection = abrir(); Liquibase liquibase = liquibase(connection)) {
			liquibase.update(new Contexts());
		}
	}

	private static void atualizar(int changesets) throws Exception {
		try (Connection connection = abrir(); Liquibase liquibase = liquibase(connection)) {
			liquibase.update(changesets, new Contexts(), new LabelExpression());
		}
	}

	private static void reverter(int changesets) throws Exception {
		try (Connection connection = abrir(); Liquibase liquibase = liquibase(connection)) {
			liquibase.rollback(changesets, new Contexts(), new LabelExpression());
		}
	}

	private static Liquibase liquibase(Connection connection) throws Exception {
		Database database = DatabaseFactory.getInstance()
			.findCorrectDatabaseImplementation(new JdbcConnection(connection));
		Liquibase liquibase = new Liquibase(CHANGELOG, new ClassLoaderResourceAccessor(), database);
		UsuariosDeBanco.parametrosEm(liquibase);
		return liquibase;
	}

	private static Connection abrir() throws Exception {
		return DriverManager.getConnection(postgres.getJdbcUrl(), postgres.getUsername(), postgres.getPassword());
	}

	private static List<String> tabelasExistentes() throws Exception {
		List<String> tabelas = new ArrayList<>();
		try (Connection connection = abrir();
				Statement statement = connection.createStatement();
				ResultSet rs = statement.executeQuery("""
						SELECT table_name FROM information_schema.tables
						WHERE table_schema = 'public' AND table_name NOT LIKE 'databasechangelog%'
						""")) {
			while (rs.next()) {
				tabelas.add(rs.getString("table_name"));
			}
		}
		return tabelas;
	}

	private static String definicaoDoIndice(String indice) throws Exception {
		try (Connection connection = abrir();
				Statement statement = connection.createStatement();
				ResultSet rs = statement
					.executeQuery("SELECT indexdef FROM pg_indexes WHERE indexname = '" + indice + "'")) {
			assertThat(rs.next()).as("índice %s não existe", indice).isTrue();
			return rs.getString("indexdef");
		}
	}

	private static Map<String, String> nulidadeDasColunas(String tabela) throws Exception {
		Map<String, String> nulidade = new HashMap<>();
		try (Connection connection = abrir();
				Statement statement = connection.createStatement();
				ResultSet rs = statement.executeQuery("""
						SELECT column_name, is_nullable FROM information_schema.columns
						WHERE table_schema = 'public' AND table_name = '%s'
						""".formatted(tabela))) {
			while (rs.next()) {
				nulidade.put(rs.getString("column_name"), rs.getString("is_nullable"));
			}
		}
		return nulidade;
	}

	private static void semearUsuario(Statement statement) throws Exception {
		statement.execute("""
				INSERT INTO usuarios (id, login, senha_hash, nome, papel, criado_em)
				VALUES ('22222222-2222-4222-8222-222222222222', 'rh', 'x', 'RH', 'profissional_rh', now())
				""");
	}

	private static String linhaDoJobSemNome(Statement statement, UUID id) throws Exception {
		try (ResultSet rs = statement.executeQuery("""
				SELECT (to_jsonb(jobs) - 'nome')::text FROM jobs WHERE id = '%s'
				""".formatted(id))) {
			assertThat(rs.next()).as("job %s não existe", id).isTrue();
			return rs.getString(1);
		}
	}

	/**
	 * Um job no status final da trilha, com uma transição por status, um segundo depois
	 * da outra; a última termina no instante fixo que o evento tem de repetir.
	 */
	private static void semearJobComTrilha(Statement statement, UUID jobId, String statusAtual, String... trilha)
			throws Exception {
		statement.execute("""
				INSERT INTO jobs (id, status, usuario_id, competencias, orcamento, criado_em)
				VALUES ('%s', '%s', '22222222-2222-4222-8222-222222222222', '{2025-08}', 1000, now())
				""".formatted(jobId, statusAtual));
		String anterior = null;
		for (int i = 0; i < trilha.length; i++) {
			String instante = "2025-11-28 15:02:44.318204+00";
			statement.execute("""
					INSERT INTO job_transicoes (job_id, status_anterior, status_novo, ocorrido_em, ator)
					VALUES ('%s', %s, '%s', timestamptz '%s' - interval '%d seconds', 'sistema')
					""".formatted(jobId, (anterior != null) ? "'" + anterior + "'" : "NULL", trilha[i], instante,
					trilha.length - 1 - i));
			anterior = trilha[i];
		}
	}

	private static UUID idDaTransicao(Statement statement, UUID jobId, String status) throws Exception {
		try (ResultSet rs = statement.executeQuery(
				"SELECT id FROM job_transicoes WHERE job_id = '%s' AND status_novo = '%s'".formatted(jobId, status))) {
			assertThat(rs.next()).isTrue();
			return rs.getObject("id", UUID.class);
		}
	}

	private static List<String> encerramentosNoOutbox(Statement statement, UUID jobId) throws Exception {
		List<String> payloads = new ArrayList<>();
		try (ResultSet rs = statement
			.executeQuery("SELECT payload::text FROM outbox_events WHERE job_id = '%s' AND tipo = 'job-encerrado'"
				.formatted(jobId))) {
			while (rs.next()) {
				payloads.add(rs.getString(1));
			}
		}
		return payloads;
	}

	private static List<String> colunasDeResultados() throws Exception {
		List<String> colunas = new ArrayList<>();
		try (Connection connection = abrir();
				Statement statement = connection.createStatement();
				ResultSet rs = statement.executeQuery("""
						SELECT column_name FROM information_schema.columns
						WHERE table_schema = 'public' AND table_name = 'resultados_simulacao'
						""")) {
			while (rs.next()) {
				colunas.add(rs.getString("column_name"));
			}
		}
		return colunas;
	}

	/**
	 * A cadeia de chaves estrangeiras que um resultado exige, semeada pelo dono: usuário,
	 * job, regra, prompt e código gerado.
	 */
	private static void semearCodigoGerado(Statement statement) throws Exception {
		statement.execute("""
				INSERT INTO usuarios (id, login, senha_hash, nome, papel, criado_em)
				VALUES ('22222222-2222-4222-8222-222222222222', 'rh', 'x', 'RH', 'profissional_rh', now())
				""");
		statement.execute("""
				INSERT INTO jobs (id, status, usuario_id, competencias, orcamento, criado_em)
				VALUES ('%s', 'simulando', '22222222-2222-4222-8222-222222222222', '{2025-08}', 1000, now())
				""".formatted(JOB_ID));
		statement.execute("""
				INSERT INTO regras (id, job_id, versao, origem, nucleo, especificacoes, hash, criada_em)
				VALUES ('55555555-5555-4555-8555-555555555555', '%s', 1, 'extracao',
				        '{}'::jsonb, '{}'::jsonb, repeat('a', 64), now())
				""".formatted(JOB_ID));
		statement.execute("""
				INSERT INTO prompts (id, job_id, no, conteudo, modelo, criado_em)
				VALUES ('66666666-6666-4666-8666-666666666666', '%s', 'geracao', 'texto', '{}'::jsonb, now())
				""".formatted(JOB_ID));
		statement.execute("""
				INSERT INTO codigos_gerados (id, job_id, regra_id, linguagem, fonte, prompt_id, criado_em)
				VALUES ('%s', '%s', '55555555-5555-4555-8555-555555555555', 'python', 'def apurar(): ...',
				        '66666666-6666-4666-8666-666666666666', now())
				""".formatted(CODIGO_ID, JOB_ID));
	}

	private static String inserirComoOWorker(Statement statement) throws Exception {
		try (ResultSet rs = statement.executeQuery(INSERE_RESULTADO_COMO_O_WORKER)) {
			rs.next();
			return rs.getString(1);
		}
	}

	/** As colunas que existiam antes do diagnóstico, numa forma comparável. */
	private static String linhaSemDiagnostico(Statement statement, String id) throws Exception {
		String consulta = """
				SELECT (id, job_id, codigo_gerado_id, status, totais, veredito, assercoes, decomposicao, criado_em)::text
				FROM resultados_simulacao WHERE id = '%s'
				"""
			.formatted(id);
		try (ResultSet rs = statement.executeQuery(consulta)) {
			assertThat(rs.next()).as("resultado %s não existe", id).isTrue();
			return rs.getString(1);
		}
	}

	private static @Nullable String diagnostico(Statement statement, String id) throws Exception {
		try (ResultSet rs = statement
			.executeQuery("SELECT diagnostico::text FROM resultados_simulacao WHERE id = '" + id + "'")) {
			assertThat(rs.next()).as("resultado %s não existe", id).isTrue();
			return rs.getString(1);
		}
	}

	private static int changesetsAplicados() throws Exception {
		try (Connection connection = abrir();
				Statement statement = connection.createStatement();
				ResultSet rs = statement.executeQuery("SELECT count(*) FROM databasechangelog")) {
			rs.next();
			return rs.getInt(1);
		}
	}

}
