package synapse.api.core.persistence;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.Arrays;
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
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.params.provider.ValueSource;
import org.testcontainers.DockerClientFactory;
import org.testcontainers.postgresql.PostgreSQLContainer;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatExceptionOfType;

/**
 * O changelog roda contra um Postgres de verdade, na mesma major que o compose: o
 * {@code uuidv7()} e o índice parcial não existem num banco em memória.
 */
@EnabledIf("dockerIsAvailable")
class MigrationTests {

	private static final String CHANGELOG = "db/changelog/changelog.yaml";

	private static final List<String> TABELAS = List.of("usuarios", "submissoes", "jobs", "job_transicoes", "job_acoes",
			"regras", "prompts", "respostas_modelo", "codigos_gerados", "resultados_simulacao", "explicacoes",
			"simulacoes", "trilhas_auditoria", "outbox_events", "jobs_grafo_encerrados", "extracoes_regras",
			"rodadas_correcao");

	private static final int CHANGESETS = 24;

	private static final int CHANGESETS_ANTES_DOS_PARAMETROS = 23;

	private static final int CHANGESETS_ANTES_DAS_RODADAS = 22;

	private static final int CHANGESETS_ANTES_DAS_LINHAS = 21;

	private static final int CHANGESETS_ANTES_DO_NOME = 19;

	/** Os changesets até o 015, o banco como estava antes da coluna de diagnóstico. */
	private static final int CHANGESETS_ANTES_DO_DIAGNOSTICO = 16;

	private static final String JOB_ID = "11111111-1111-4111-8111-111111111111";

	private static final String CODIGO_ID = "33333333-3333-4333-8333-333333333333";

	private static final UUID SUBMISSAO_ID = UUID.fromString("44444444-4444-4444-8444-444444444444");

	private static final UUID REGRA_ID = UUID.fromString("55555555-5555-4555-8555-555555555555");

	private static final String CONFLITOS = """
			[{"elementos": ["nucleo.percentual"], "motivo": "percentual ausente"}]
			""";

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
					"representacao:jsonb", "rebaixamentos:jsonb", "criado_em:timestamp with time zone",
					"parametros:jsonb");
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
		atualizar(CHANGESETS_ANTES_DAS_LINHAS);
		String anterior;
		String linhaAntes;
		try (Connection connection = abrir(); Statement statement = connection.createStatement()) {
			semearCodigoGerado(statement);
			anterior = inserirComoOWorker(statement);
			linhaAntes = linhaSemDiagnostico(statement, anterior);
		}

		atualizar(1);

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

	/**
	 * As quatro mudanças dos parâmetros da simulação: o orçamento deixa de ser
	 * obrigatório, porque o job de texto nasce sem ele; a meta de venda nasce nulável
	 * como ele; a extração recebe os parâmetros como coluna obrigatória com default, para
	 * o INSERT de uma versão do codegen anterior a ela continuar válido; e a versão da
	 * regra os recebe nulável, porque só as nascidas de texto os têm.
	 */
	@Test
	void criaOsParametrosDaSimulacaoEDispensaOOrcamentoObrigatorio() throws Exception {
		atualizar();

		assertThat(nulidadeDasColunas("jobs")).containsEntry("orcamento", "YES").containsEntry("meta_venda", "YES");
		assertThat(coluna("jobs", "meta_venda")).containsExactly("numeric", "YES", null);
		assertThat(coluna("regras", "parametros")).containsExactly("jsonb", "YES", null);
		assertThat(coluna("extracoes_regras", "parametros")).containsExactly("jsonb", "NO", "'{}'::jsonb");
	}

	/**
	 * O banco já em uso recebe as colunas sem perder nada: o job e a extração gravados
	 * antes ficam como estavam, a extração ganha os parâmetros vazios, e o INSERT do
	 * codegen que ainda não conhece a coluna continua funcionando depois dela.
	 */
	@Test
	void jobEExtracaoGravadosAntesDosParametrosChegamIntactosEComEleVazio() throws Exception {
		atualizar(CHANGESETS_ANTES_DOS_PARAMETROS);
		UUID job = UUID.randomUUID();
		String linhaAntes;
		try (Connection connection = abrir(); Statement statement = connection.createStatement()) {
			semearUsuario(statement);
			semearJobComTrilha(statement, job, "gerando_regra");
			semearExtracao(statement, job);
			linhaAntes = linhaDoJob(statement, job);
		}

		atualizar();

		try (Connection connection = abrir(); Statement statement = connection.createStatement()) {
			semearExtracao(statement, job);
			assertThat(linhaDoJob(statement, job)).isEqualTo(linhaAntes);
			try (ResultSet rs = statement
				.executeQuery("SELECT meta_venda, orcamento::text FROM jobs WHERE id = '%s'".formatted(job))) {
				assertThat(rs.next()).isTrue();
				assertThat(rs.getString("meta_venda")).isNull();
				assertThat(rs.getString("orcamento")).isEqualTo("1000");
			}
			try (ResultSet rs = statement.executeQuery("SELECT parametros::text FROM extracoes_regras")) {
				assertThat(rs.next()).isTrue();
				assertThat(rs.getString(1)).isEqualTo("{}");
				assertThat(rs.next()).isTrue();
				assertThat(rs.getString(1)).isEqualTo("{}");
				assertThat(rs.next()).isFalse();
			}
		}

		reverter(1);

		assertThat(nulidadeDasColunas("jobs")).containsEntry("orcamento", "NO").doesNotContainKey("meta_venda");
		assertThat(nulidadeDasColunas("extracoes_regras")).doesNotContainKey("parametros");
		assertThat(nulidadeDasColunas("regras")).doesNotContainKey("parametros");
		try (Connection connection = abrir(); Statement statement = connection.createStatement()) {
			assertThat(linhaDoJob(statement, job)).isEqualTo(linhaAntes);
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

	@Test
	void criaRodadasComTiposNulidadeEDefaultCorretosSemChecks() throws Exception {
		atualizar();
		try (Connection connection = abrir(); Statement statement = connection.createStatement()) {
			try (ResultSet rs = statement.executeQuery("""
					SELECT column_name, data_type, is_nullable, column_default
					FROM information_schema.columns
					WHERE table_schema = 'public' AND table_name = 'rodadas_correcao'
					ORDER BY ordinal_position
					""")) {
				List<String> colunas = new ArrayList<>();
				while (rs.next()) {
					colunas.add(rs.getString("column_name") + ":" + rs.getString("data_type") + ":"
							+ rs.getString("is_nullable"));
					if ("id".equals(rs.getString("column_name"))) {
						assertThat(rs.getString("column_default")).isEqualTo("uuidv7()");
					}
					else {
						assertThat(rs.getString("column_default")).isNull();
					}
				}
				assertThat(colunas).containsExactly("id:uuid:NO", "job_id:uuid:NO", "regra_analisada_id:uuid:NO",
						"conflitos:jsonb:NO", "estado:text:NO", "submissao_correcao_id:uuid:YES",
						"regra_resultante_id:uuid:YES", "rodada_anterior_id:uuid:YES",
						"criada_em:timestamp with time zone:NO", "atualizada_em:timestamp with time zone:NO");
			}
			try (ResultSet rs = statement.executeQuery("""
					SELECT contype, pg_get_constraintdef(oid) AS definicao FROM pg_constraint
					WHERE conrelid = 'rodadas_correcao'::regclass AND contype IN ('p', 'c')
					""")) {
				assertThat(rs.next()).isTrue();
				assertThat(rs.getString("contype")).isEqualTo("p");
				assertThat(rs.getString("definicao")).isEqualTo("PRIMARY KEY (id)");
				assertThat(rs.next()).isFalse();
			}
			semearParaRodadas(statement);
			assertThat(inserirRodada(connection, "pendente", null).version()).isEqualTo(7);
		}
	}

	@Test
	void criaAsCincoChavesEstrangeirasDasRodadasSemCascade() throws Exception {
		atualizar();
		try (Connection connection = abrir();
				Statement statement = connection.createStatement();
				ResultSet rs = statement.executeQuery("""
						SELECT conname, pg_get_constraintdef(oid) AS definicao, confdeltype
						FROM pg_constraint WHERE conrelid = 'rodadas_correcao'::regclass AND contype = 'f'
						""")) {
			Map<String, String> fks = new HashMap<>();
			while (rs.next()) {
				fks.put(rs.getString("conname"), rs.getString("definicao"));
				assertThat(rs.getString("confdeltype")).isEqualTo("a");
			}
			assertThat(fks).containsExactlyInAnyOrderEntriesOf(Map.of("fk_rodadas_correcao_job_id",
					"FOREIGN KEY (job_id) REFERENCES jobs(id)", "fk_rodadas_correcao_regra_analisada_id",
					"FOREIGN KEY (regra_analisada_id) REFERENCES regras(id)",
					"fk_rodadas_correcao_submissao_correcao_id",
					"FOREIGN KEY (submissao_correcao_id) REFERENCES submissoes(id)",
					"fk_rodadas_correcao_regra_resultante_id",
					"FOREIGN KEY (regra_resultante_id) REFERENCES regras(id)", "fk_rodadas_correcao_rodada_anterior_id",
					"FOREIGN KEY (rodada_anterior_id) REFERENCES rodadas_correcao(id)"));
		}
	}

	@ParameterizedTest
	@ValueSource(ints = { 1, 2, 3, 4, 5 })
	void recusaReferenciaInexistenteNaInsercaoDaRodada(int referencia) throws Exception {
		atualizar();
		try (Connection connection = abrir(); Statement statement = connection.createStatement()) {
			semearParaRodadas(statement);
			UUID anterior = inserirRodada(connection, "corrigida", null);
			try (PreparedStatement insert = connection.prepareStatement("""
					INSERT INTO rodadas_correcao (job_id, regra_analisada_id, submissao_correcao_id,
					    regra_resultante_id, rodada_anterior_id, conflitos, estado, criada_em, atualizada_em)
					VALUES (?, ?, ?, ?, ?, ?::jsonb, 'corrigida', now(), now())
					""")) {
				insert.setObject(1, UUID.fromString(JOB_ID));
				insert.setObject(2, REGRA_ID);
				insert.setObject(3, SUBMISSAO_ID);
				insert.setObject(4, REGRA_ID);
				insert.setObject(5, anterior);
				insert.setString(6, CONFLITOS);
				insert.setObject(referencia, UUID.randomUUID());
				assertThatExceptionOfType(SQLException.class).isThrownBy(insert::executeUpdate)
					.satisfies(e -> assertThat(e.getSQLState()).isEqualTo("23503"));
			}
		}
	}

	@Test
	void criaSomenteOsDoisIndicesParciaisAlemDaChavePrimaria() throws Exception {
		atualizar();
		assertThat(definicaoDoIndice("uq_rodadas_correcao_rodada_anterior_id")).contains("UNIQUE",
				"(rodada_anterior_id)", "WHERE (rodada_anterior_id IS NOT NULL)");
		assertThat(definicaoDoIndice("uq_rodadas_correcao_job_id_aberta")).contains("UNIQUE", "(job_id)",
				"WHERE (estado = ANY (ARRAY['pendente'::text, 'em_reextracao'::text]))");
		try (Connection connection = abrir();
				Statement statement = connection.createStatement();
				ResultSet rs = statement
					.executeQuery("SELECT count(*) FROM pg_indexes WHERE tablename = 'rodadas_correcao'")) {
			assertThat(rs.next()).isTrue();
			assertThat(rs.getInt(1)).isEqualTo(3);
		}
	}

	@Test
	void permiteCadeiaDeRodadasMasRecusaBifurcacao() throws Exception {
		atualizar();
		try (Connection connection = abrir(); Statement statement = connection.createStatement()) {
			semearParaRodadas(statement);
			UUID a = inserirRodada(connection, "corrigida", null);
			UUID b = inserirRodada(connection, "reextracao_falhou", a);
			inserirRodada(connection, "pendente", b);
			assertThatExceptionOfType(SQLException.class).isThrownBy(() -> inserirRodada(connection, "abandonada", a))
				.satisfies(e -> assertThat(e.getSQLState()).isEqualTo("23505"));
		}
	}

	@ParameterizedTest
	@CsvSource({ "pendente,pendente", "pendente,em_reextracao", "em_reextracao,pendente",
			"em_reextracao,em_reextracao" })
	void recusaDuasRodadasAbertasNoMesmoJob(String primeira, String segunda) throws Exception {
		atualizar();
		try (Connection connection = abrir(); Statement statement = connection.createStatement()) {
			semearParaRodadas(statement);
			inserirRodada(connection, primeira, null);
			assertThatExceptionOfType(SQLException.class).isThrownBy(() -> inserirRodada(connection, segunda, null))
				.satisfies(e -> assertThat(e.getSQLState()).isEqualTo("23505"));
		}
	}

	@ParameterizedTest
	@ValueSource(strings = { "corrigida", "reextracao_falhou", "abandonada" })
	void permiteHistoricoFechadoEUmaRodadaAberta(String estadoFechado) throws Exception {
		atualizar();
		try (Connection connection = abrir(); Statement statement = connection.createStatement()) {
			semearParaRodadas(statement);
			inserirRodada(connection, estadoFechado, null);
			inserirRodada(connection, estadoFechado, null);
			inserirRodada(connection, "pendente", null);
			try (ResultSet rs = statement.executeQuery("SELECT count(*) FROM rodadas_correcao")) {
				assertThat(rs.next()).isTrue();
				assertThat(rs.getInt(1)).isEqualTo(3);
			}
		}
	}

	@Test
	void upgradeDasRodadasPreservaDadosEPermissoesAnteriores() throws Exception {
		atualizar(CHANGESETS_ANTES_DAS_RODADAS);
		assertThat(changesetsAplicados()).isEqualTo(CHANGESETS_ANTES_DAS_RODADAS);
		assertThat(tabelasExistentes()).doesNotContain("rodadas_correcao");
		try (Connection connection = abrir(); Statement statement = connection.createStatement()) {
			semearParaRodadas(statement);
		}
		Map<String, String> dadosAntes = dadosAnterioresAsRodadas();
		List<String> permissoesAntes = permissoesAnterioresAsRodadas();

		atualizar();

		assertThat(changesetsAplicados()).isEqualTo(CHANGESETS);
		assertThat(tabelasExistentes()).containsExactlyInAnyOrderElementsOf(TABELAS);
		assertThat(dadosAnterioresAsRodadas()).isEqualTo(dadosAntes);
		assertThat(permissoesAnterioresAsRodadas()).isEqualTo(permissoesAntes);
		try (Connection connection = abrir();
				Statement statement = connection.createStatement();
				ResultSet rs = statement.executeQuery("SELECT count(*) FROM rodadas_correcao")) {
			assertThat(rs.next()).isTrue();
			assertThat(rs.getInt(1)).as("sem backfill de rodadas").isZero();
		}
	}

	@Test
	void rollbackDasRodadasRemoveSomenteATabelaESeusIndices() throws Exception {
		atualizar();
		assertThat(tabelasExistentes()).contains("rodadas_correcao");
		try (Connection connection = abrir(); Statement statement = connection.createStatement()) {
			semearParaRodadas(statement);
			inserirRodada(connection, "pendente", null);
		}
		Map<String, String> dadosAntes = dadosAnterioresAsRodadas();
		List<String> permissoesAntes = permissoesAnterioresAsRodadas();

		// Dois: o changeset dos parâmetros vem depois do das rodadas e sai junto para
		// chegar a ele.
		reverter(CHANGESETS - CHANGESETS_ANTES_DAS_RODADAS);

		assertThat(changesetsAplicados()).isEqualTo(CHANGESETS_ANTES_DAS_RODADAS);
		assertThat(tabelasExistentes())
			.containsExactlyInAnyOrderElementsOf(TABELAS.stream().filter(t -> !t.equals("rodadas_correcao")).toList());
		assertThat(dadosAnterioresAsRodadas()).isEqualTo(dadosAntes);
		assertThat(permissoesAnterioresAsRodadas()).isEqualTo(permissoesAntes);
		try (Connection connection = abrir();
				Statement statement = connection.createStatement();
				ResultSet rs = statement
					.executeQuery("SELECT indexname FROM pg_indexes WHERE tablename = 'rodadas_correcao'")) {
			assertThat(rs.next()).isFalse();
		}
	}

	private static void semearParaRodadas(Statement statement) throws Exception {
		semearUsuario(statement);
		statement.execute("""
				INSERT INTO submissoes (id, usuario_id, tipo, transcricao, criado_em)
				VALUES ('%s', '22222222-2222-4222-8222-222222222222', 'texto', 'correcao de teste', now())
				""".formatted(SUBMISSAO_ID));
		semearJobComTrilha(statement, UUID.fromString(JOB_ID), "aguardando_confirmacao_parametros");
		statement.execute("""
				INSERT INTO regras (id, job_id, versao, origem, nucleo, especificacoes, hash, criada_em)
				VALUES ('%s', '%s', 1, 'extracao', '{}'::jsonb, '[]'::jsonb, repeat('a', 64), now())
				""".formatted(REGRA_ID, JOB_ID));
	}

	private static UUID inserirRodada(Connection connection, String estado, @Nullable UUID anterior) throws Exception {
		try (PreparedStatement insert = connection.prepareStatement("""
				INSERT INTO rodadas_correcao (job_id, regra_analisada_id, conflitos, estado,
				    rodada_anterior_id, criada_em, atualizada_em)
				VALUES (?, ?, ?::jsonb, ?, ?, now(), now()) RETURNING id
				""")) {
			insert.setObject(1, UUID.fromString(JOB_ID));
			insert.setObject(2, REGRA_ID);
			insert.setString(3, CONFLITOS);
			insert.setString(4, estado);
			insert.setObject(5, anterior);
			try (ResultSet rs = insert.executeQuery()) {
				assertThat(rs.next()).isTrue();
				return rs.getObject(1, UUID.class);
			}
		}
	}

	/**
	 * As linhas de todas as tabelas menos a das rodadas, sem as colunas que o changeset
	 * dos parâmetros acrescenta: é o que permite comparar a mesma linha antes e depois de
	 * um upgrade ou rollback que atravessa os dois changesets.
	 */
	private static Map<String, String> dadosAnterioresAsRodadas() throws Exception {
		Map<String, String> dados = new HashMap<>();
		try (Connection connection = abrir(); Statement statement = connection.createStatement()) {
			for (String tabela : TABELAS) {
				if (!tabela.equals("rodadas_correcao")) {
					try (ResultSet rs = statement
						.executeQuery("SELECT COALESCE(jsonb_agg(to_jsonb(t) - 'meta_venda' - 'parametros' "
								+ "ORDER BY to_jsonb(t)::text), '[]'::jsonb)::text FROM " + tabela + " t")) {
						assertThat(rs.next()).isTrue();
						dados.put(tabela, rs.getString(1));
					}
				}
			}
		}
		return dados;
	}

	private static List<String> permissoesAnterioresAsRodadas() throws Exception {
		List<String> permissoes = new ArrayList<>();
		try (Connection connection = abrir();
				Statement statement = connection.createStatement();
				ResultSet rs = statement.executeQuery("""
						SELECT (table_name, grantee, privilege_type, is_grantable)::text
						FROM information_schema.table_privileges
						WHERE table_schema = 'public' AND table_name <> 'rodadas_correcao' ORDER BY 1
						""")) {
			while (rs.next()) {
				permissoes.add(rs.getString(1));
			}
		}
		return permissoes;
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

	/** O tipo, a nulidade e o default de uma coluna, na ordem. */
	private static List<@Nullable String> coluna(String tabela, String coluna) throws Exception {
		try (Connection connection = abrir();
				Statement statement = connection.createStatement();
				ResultSet rs = statement.executeQuery("""
						SELECT data_type, is_nullable, column_default FROM information_schema.columns
						WHERE table_schema = 'public' AND table_name = '%s' AND column_name = '%s'
						""".formatted(tabela, coluna))) {
			assertThat(rs.next()).as("coluna %s.%s não existe", tabela, coluna).isTrue();
			return Arrays.asList(rs.getString("data_type"), rs.getString("is_nullable"),
					rs.getString("column_default"));
		}
	}

	/**
	 * O job sem a coluna de meta de venda, para comparar a mesma linha antes e depois do
	 * changeset que a acrescenta.
	 */
	private static String linhaDoJob(Statement statement, UUID id) throws Exception {
		try (ResultSet rs = statement.executeQuery("""
				SELECT (to_jsonb(jobs) - 'meta_venda')::text FROM jobs WHERE id = '%s'
				""".formatted(id))) {
			assertThat(rs.next()).as("job %s não existe", id).isTrue();
			return rs.getString(1);
		}
	}

	/**
	 * O que o codegen grava ao extrair, como o INSERT de uma versão que não conhece a
	 * coluna de parâmetros. Cada chamada usa uma submissão nova, porque
	 * {@code uq_extracoes_regras_job_id_submissao_id} admite uma extração por job e
	 * submissão.
	 */
	private static void semearExtracao(Statement statement, UUID jobId) throws Exception {
		UUID submissao = UUID.randomUUID();
		UUID prompt = UUID.randomUUID();
		UUID resposta = UUID.randomUUID();
		statement.execute("""
				INSERT INTO submissoes (id, usuario_id, tipo, transcricao, criado_em)
				VALUES ('%s', '22222222-2222-4222-8222-222222222222', 'texto', 'pague 5%%', now())
				""".formatted(submissao));
		statement.execute("""
				INSERT INTO prompts (id, job_id, no, conteudo, modelo, criado_em)
				VALUES ('%s', '%s', 'extracao_parametros', 'texto', '{}'::jsonb, now())
				""".formatted(prompt, jobId));
		statement.execute("""
				INSERT INTO respostas_modelo (id, job_id, prompt_id, conteudo, criado_em)
				VALUES ('%s', '%s', '%s', 'resposta', now())
				""".formatted(resposta, jobId, prompt));
		statement.execute(
				"""
						INSERT INTO extracoes_regras (job_id, submissao_id, resposta_id, representacao, rebaixamentos, criado_em)
						VALUES ('%s', '%s', '%s', '{"nucleo": {}, "especificacoes": []}'::jsonb, '[]'::jsonb, now())
						"""
					.formatted(jobId, submissao, resposta));
	}

	private static String linhaDoJobSemNome(Statement statement, UUID id) throws Exception {
		try (ResultSet rs = statement.executeQuery("""
				SELECT (to_jsonb(jobs) - 'nome' - 'meta_venda')::text FROM jobs WHERE id = '%s'
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
