package synapse.api.core.persistence;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.UUID;

import liquibase.Contexts;
import liquibase.Liquibase;
import liquibase.database.Database;
import liquibase.database.DatabaseFactory;
import liquibase.database.jvm.JdbcConnection;
import liquibase.resource.ClassLoaderResourceAccessor;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIf;
import org.testcontainers.DockerClientFactory;
import org.testcontainers.postgresql.PostgreSQLContainer;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatExceptionOfType;

/**
 * O isolamento entre serviços é aplicado pelo banco, e é isto que prova: uma escrita
 * indevida falha por permissão, não porque alguém lembrou de não fazê-la.
 *
 * Afirma o SQLState {@code 42501} e não a mensagem — é o que distingue "o banco recusou
 * por privilégio" de "a query quebrou por outro motivo", e faz o teste falhar se um dia a
 * recusa vier de outro lugar.
 */
@EnabledIf("dockerIsAvailable")
class PermissoesDeBancoTests {

	private static final String CHANGELOG = "db/changelog/changelog.yaml";

	/** {@code insufficient_privilege}. */
	private static final String PERMISSAO_NEGADA = "42501";

	private static final String SENHA = "senha-de-teste";

	private static PostgreSQLContainer postgres;

	static boolean dockerIsAvailable() {
		return DockerClientFactory.instance().isDockerAvailable();
	}

	/**
	 * O changelog roda uma vez e o cenário é semeado pelo dono. Nenhum teste escreve pelo
	 * dono depois disso: o que se afirma é sempre o que o usuário do serviço alcança.
	 */
	@BeforeAll
	static void prepararOBanco() throws Exception {
		postgres = new PostgreSQLContainer("postgres:18-alpine");
		postgres.start();

		try (Connection connection = comoDono(); Liquibase liquibase = liquibase(connection)) {
			liquibase.update(new Contexts());
		}

		try (Connection connection = comoDono(); Statement statement = connection.createStatement()) {
			// O changeset cria o papel sem senha, porque senha não entra em arquivo
			// versionado. Em produção quem a define é o initdb do compose; aqui, o teste.
			for (String usuario : new String[] { UsuariosDeBanco.API, UsuariosDeBanco.CODEGEN,
					UsuariosDeBanco.WORKER }) {
				statement.execute("ALTER ROLE " + usuario + " WITH PASSWORD '" + SENHA + "'");
			}
			semear(statement);
		}
	}

	@AfterAll
	static void derrubarOPostgres() {
		if (postgres != null) {
			postgres.stop();
		}
	}

	// --- A negativa: estado e decisão de negócio são inalcançáveis -----------------

	@Test
	void oCodegenNaoEscreveEmJobs() {
		assertThat(sqlStateAoFalhar(UsuariosDeBanco.CODEGEN, INSERE_JOB)).isEqualTo(PERMISSAO_NEGADA);
	}

	@Test
	void oWorkerNaoEscreveEmJobs() {
		assertThat(sqlStateAoFalhar(UsuariosDeBanco.WORKER, INSERE_JOB)).isEqualTo(PERMISSAO_NEGADA);
	}

	@Test
	void nenhumDosDoisLeJobs() {
		assertThat(sqlStateAoFalhar(UsuariosDeBanco.CODEGEN, "SELECT id FROM jobs")).isEqualTo(PERMISSAO_NEGADA);
		assertThat(sqlStateAoFalhar(UsuariosDeBanco.WORKER, "SELECT id FROM jobs")).isEqualTo(PERMISSAO_NEGADA);
	}

	@Test
	void nenhumDosDoisAlcancaTrilhaTransicoesOuOutbox() {
		for (String usuario : new String[] { UsuariosDeBanco.CODEGEN, UsuariosDeBanco.WORKER }) {
			assertThat(sqlStateAoFalhar(usuario, "SELECT id FROM trilhas_auditoria")).isEqualTo(PERMISSAO_NEGADA);
			assertThat(sqlStateAoFalhar(usuario, "SELECT id FROM job_transicoes")).isEqualTo(PERMISSAO_NEGADA);
			assertThat(sqlStateAoFalhar(usuario, "SELECT id FROM job_acoes")).isEqualTo(PERMISSAO_NEGADA);
			assertThat(sqlStateAoFalhar(usuario, "SELECT id FROM outbox_events")).isEqualTo(PERMISSAO_NEGADA);
		}
	}

	// --- O positivo: sem ele, um papel sem GRANT nenhum passaria em tudo acima -----

	@Test
	void oCodegenGravaOsArtefatosQueProduz() {
		assertThatCode(() -> executar(UsuariosDeBanco.CODEGEN, """
				INSERT INTO prompts (job_id, no, conteudo, modelo, criado_em)
				VALUES ('%s', 'extracao', 'texto', '{}'::jsonb, now())
				""".formatted(JOB_ID))).doesNotThrowAnyException();
	}

	@Test
	void oWorkerGravaOResultado() {
		assertThatCode(() -> executar(UsuariosDeBanco.WORKER, """
				INSERT INTO resultados_simulacao (job_id, codigo_gerado_id, status, assercoes, criado_em)
				VALUES ('%s', '%s', 'sucesso', '[]'::jsonb, now())
				""".formatted(JOB_ID, CODIGO_ID))).doesNotThrowAnyException();
	}

	@Test
	void oCodegenLeATranscricao() {
		assertThatCode(() -> executar(UsuariosDeBanco.CODEGEN, "SELECT transcricao FROM submissoes"))
			.doesNotThrowAnyException();
	}

	@Test
	void oWorkerInsereDetalhamentoEAApiLeSemPermitirAtualizacao() throws Exception {
		String resultadoId;
		try (Connection connection = como(UsuariosDeBanco.WORKER);
				Statement statement = connection.createStatement();
				ResultSet rs = statement.executeQuery("""
						INSERT INTO resultados_simulacao
						    (job_id, codigo_gerado_id, status, assercoes, linhas, criado_em)
						VALUES ('%s', '%s', 'sucesso', '[]'::jsonb,
						        '{"2025-08": {"MATRIC-1": {"cod_loja": "75", "cod_marca": "20",
						        "cod_cargo": "200", "comissao_baseline": 100, "comissao_simulada": 110,
						        "diferenca": 10, "contribuicoes": {"nucleo.percentual": 10}}}}'::jsonb, now())
						RETURNING id::text
						""".formatted(JOB_ID, CODIGO_ID))) {
			assertThat(rs.next()).isTrue();
			resultadoId = rs.getString(1);
		}
		try (Connection connection = como(UsuariosDeBanco.API);
				Statement statement = connection.createStatement();
				ResultSet rs = statement.executeQuery("""
						SELECT linhas #>> '{2025-08,MATRIC-1,diferenca}' FROM resultados_simulacao WHERE id = '%s'
						""".formatted(resultadoId))) {
			assertThat(rs.next()).isTrue();
			assertThat(rs.getString(1)).isEqualTo("10");
		}
		for (String usuario : new String[] { UsuariosDeBanco.WORKER, UsuariosDeBanco.API }) {
			assertThat(sqlStateAoFalhar(usuario, "UPDATE resultados_simulacao SET linhas = '{}'::jsonb"))
				.isEqualTo(PERMISSAO_NEGADA);
		}
	}

	// --- O diagnóstico vem com o resultado e é tão imutável quanto ele -------------

	@Test
	void oWorkerGravaODiagnosticoJuntoDoResultado() {
		assertThatCode(() -> executar(UsuariosDeBanco.WORKER, INSERE_RESULTADO_COM_DIAGNOSTICO))
			.doesNotThrowAnyException();
	}

	@Test
	void aApiEOCodegenLeemODiagnostico() {
		for (String usuario : new String[] { UsuariosDeBanco.API, UsuariosDeBanco.CODEGEN }) {
			assertThatCode(() -> executar(usuario, "SELECT diagnostico FROM resultados_simulacao"))
				.doesNotThrowAnyException();
		}
	}

	@Test
	void oWorkerNaoAlteraNemApagaUmResultadoGravado() {
		assertThat(sqlStateAoFalhar(UsuariosDeBanco.WORKER, ALTERA_DIAGNOSTICO)).isEqualTo(PERMISSAO_NEGADA);
		assertThat(sqlStateAoFalhar(UsuariosDeBanco.WORKER, "DELETE FROM resultados_simulacao"))
			.isEqualTo(PERMISSAO_NEGADA);
	}

	@Test
	void nemAApiNemOCodegenGravamODiagnostico() {
		for (String usuario : new String[] { UsuariosDeBanco.API, UsuariosDeBanco.CODEGEN }) {
			assertThat(sqlStateAoFalhar(usuario, INSERE_RESULTADO_COM_DIAGNOSTICO)).isEqualTo(PERMISSAO_NEGADA);
			assertThat(sqlStateAoFalhar(usuario, ALTERA_DIAGNOSTICO)).isEqualTo(PERMISSAO_NEGADA);
		}
	}

	// --- O registro de limpeza é do codegen, e só a limpeza muda nele ---------------

	@Test
	void oCodegenRegistraOEncerramentoEMarcaALimpeza() {
		assertThatCode(() -> {
			executar(UsuariosDeBanco.CODEGEN, """
					INSERT INTO jobs_grafo_encerrados (job_id, evento_id, status, encerrado_em)
					VALUES ('%s', '77777777-7777-4777-8777-777777777777', 'cancelado', now())
					""".formatted(JOB_ID));
			executar(UsuariosDeBanco.CODEGEN, "SELECT job_id, limpo_em FROM jobs_grafo_encerrados");
			executar(UsuariosDeBanco.CODEGEN, """
					UPDATE jobs_grafo_encerrados SET limpo_em = now()
					WHERE job_id = '%s' AND limpo_em IS NULL
					""".formatted(JOB_ID));
		}).doesNotThrowAnyException();
	}

	@Test
	void oCodegenNaoReescreveNemApagaOEncerramentoRegistrado() {
		for (String coluna : new String[] { "status = 'erro'", "encerrado_em = now()",
				"evento_id = '88888888-8888-4888-8888-888888888888'", "job_id = job_id" }) {
			assertThat(sqlStateAoFalhar(UsuariosDeBanco.CODEGEN, "UPDATE jobs_grafo_encerrados SET " + coluna))
				.isEqualTo(PERMISSAO_NEGADA);
		}
		assertThat(sqlStateAoFalhar(UsuariosDeBanco.CODEGEN, "DELETE FROM jobs_grafo_encerrados"))
			.isEqualTo(PERMISSAO_NEGADA);
	}

	@Test
	void nemAApiNemOWorkerEscrevemNoRegistroDeLimpeza() {
		String insere = """
				INSERT INTO jobs_grafo_encerrados (job_id, evento_id, status, encerrado_em)
				VALUES ('%s', '99999999-9999-4999-8999-999999999999', 'erro', now())
				""".formatted(JOB_ID);
		for (String usuario : new String[] { UsuariosDeBanco.API, UsuariosDeBanco.WORKER }) {
			assertThat(sqlStateAoFalhar(usuario, insere)).isEqualTo(PERMISSAO_NEGADA);
			assertThat(sqlStateAoFalhar(usuario, "UPDATE jobs_grafo_encerrados SET limpo_em = now()"))
				.isEqualTo(PERMISSAO_NEGADA);
		}
	}

	// --- O código executado é lido, nunca alterado ---------------------------------

	@Test
	void oWorkerLeOCodigoAExecutar() {
		assertThatCode(() -> executar(UsuariosDeBanco.WORKER, "SELECT fonte FROM codigos_gerados"))
			.doesNotThrowAnyException();
	}

	@Test
	void oWorkerNaoAlteraOCodigoAExecutar() {
		assertThat(sqlStateAoFalhar(UsuariosDeBanco.WORKER, "UPDATE codigos_gerados SET fonte = 'adulterado'"))
			.isEqualTo(PERMISSAO_NEGADA);
	}

	// --- A regra é imutável para quem a escreve ------------------------------------

	@Test
	void oCodegenInsereVersaoDeRegraMasNaoAAltera() {
		assertThatCode(() -> executar(UsuariosDeBanco.CODEGEN, """
				INSERT INTO regras (job_id, versao, origem, nucleo, especificacoes, hash, criada_em)
				VALUES ('%s', 2, 'extracao', '{}'::jsonb, '{}'::jsonb, repeat('b', 64), now())
				""".formatted(JOB_ID))).doesNotThrowAnyException();

		assertThat(sqlStateAoFalhar(UsuariosDeBanco.CODEGEN, "UPDATE regras SET versao = 99"))
			.isEqualTo(PERMISSAO_NEGADA);
		assertThat(sqlStateAoFalhar(UsuariosDeBanco.CODEGEN, "DELETE FROM regras")).isEqualTo(PERMISSAO_NEGADA);
	}

	@Test
	void nemMesmoAApiAlteraUmaRegraJaGravada() {
		assertThat(sqlStateAoFalhar(UsuariosDeBanco.API, "UPDATE regras SET versao = 99")).isEqualTo(PERMISSAO_NEGADA);
		assertThat(sqlStateAoFalhar(UsuariosDeBanco.API, "DELETE FROM regras")).isEqualTo(PERMISSAO_NEGADA);
	}

	@Test
	void aApiNaoEscreveNaTabelaDeArtefatoDeOutroServico() {
		assertThat(sqlStateAoFalhar(UsuariosDeBanco.API, "UPDATE codigos_gerados SET fonte = 'x'"))
			.isEqualTo(PERMISSAO_NEGADA);
		assertThat(sqlStateAoFalhar(UsuariosDeBanco.API, "UPDATE resultados_simulacao SET veredito = 'x'"))
			.isEqualTo(PERMISSAO_NEGADA);
	}

	// --- Apoio ---------------------------------------------------------------------

	@Test
	void oCodegenGravaExtracaoEAApiLePelaReferencia() {
		assertThatCode(() -> {
			executar(UsuariosDeBanco.CODEGEN, INSERE_EXTRACAO);
			executar(UsuariosDeBanco.API, "SELECT representacao, rebaixamentos, parametros FROM extracoes_regras");
		}).doesNotThrowAnyException();
	}

	/**
	 * Os parâmetros da simulação: o codegen grava os seus na extração e na versão que
	 * nasce dela, a api os lê e grava no job os do próprio job. Nenhum dos dois alcança o
	 * que não é seu, e nenhuma coluna nova precisou de GRANT próprio.
	 */
	@Test
	void osParametrosDaSimulacaoSeguemAPermissaoDaTabelaQueOsGuarda() {
		assertThatCode(() -> {
			executar(UsuariosDeBanco.CODEGEN, """
					INSERT INTO regras (job_id, versao, origem, nucleo, especificacoes, parametros, hash, criada_em)
					VALUES ('%s', 3, 'extracao', '{}'::jsonb, '[]'::jsonb,
					        '{"meta_venda": 12000000.0}'::jsonb, repeat('c', 64), now())
					""".formatted(JOB_ID));
			executar(UsuariosDeBanco.API, "SELECT parametros FROM regras");
			executar(UsuariosDeBanco.API,
					"UPDATE jobs SET orcamento = NULL, meta_venda = 12000000.0 WHERE id = '%s'".formatted(JOB_ID));
		}).doesNotThrowAnyException();

		assertThat(sqlStateAoFalhar(UsuariosDeBanco.CODEGEN, "UPDATE jobs SET meta_venda = 1"))
			.isEqualTo(PERMISSAO_NEGADA);
		assertThat(sqlStateAoFalhar(UsuariosDeBanco.WORKER, "SELECT parametros FROM extracoes_regras"))
			.isEqualTo(PERMISSAO_NEGADA);
		assertThat(sqlStateAoFalhar(UsuariosDeBanco.API, "UPDATE regras SET parametros = '{}'::jsonb"))
			.isEqualTo(PERMISSAO_NEGADA);
	}

	@Test
	void nenhumServicoReescreveOuApagaExtracaoEAApiNaoInsere() {
		for (String usuario : new String[] { UsuariosDeBanco.API, UsuariosDeBanco.CODEGEN }) {
			assertThat(sqlStateAoFalhar(usuario, "UPDATE extracoes_regras SET representacao = '{}'::jsonb"))
				.isEqualTo(PERMISSAO_NEGADA);
			assertThat(sqlStateAoFalhar(usuario, "DELETE FROM extracoes_regras")).isEqualTo(PERMISSAO_NEGADA);
		}
		assertThat(sqlStateAoFalhar(UsuariosDeBanco.API, INSERE_EXTRACAO)).isEqualTo(PERMISSAO_NEGADA);
	}

	@Test
	void oWorkerNaoAlcancaExtracoes() {
		assertThat(sqlStateAoFalhar(UsuariosDeBanco.WORKER, "SELECT id FROM extracoes_regras"))
			.isEqualTo(PERMISSAO_NEGADA);
		assertThat(sqlStateAoFalhar(UsuariosDeBanco.WORKER, INSERE_EXTRACAO)).isEqualTo(PERMISSAO_NEGADA);
	}

	@Test
	void aApiInsereLeEAtualizaRodada() throws Exception {
		try (Connection connection = como(UsuariosDeBanco.API); Statement statement = connection.createStatement()) {
			connection.setAutoCommit(false);
			try {
				UUID id;
				try (ResultSet rs = statement.executeQuery(INSERE_RODADA + " RETURNING id")) {
					assertThat(rs.next()).isTrue();
					id = rs.getObject(1, UUID.class);
				}
				assertThat(statement.executeUpdate("""
						UPDATE rodadas_correcao SET estado = 'corrigida',
						    submissao_correcao_id = '44444444-4444-4444-8444-444444444444',
						    regra_resultante_id = '55555555-5555-4555-8555-555555555555',
						    atualizada_em = timestamptz '2026-10-06 12:00:00+00'
						WHERE id = '%s'
						""".formatted(id))).isEqualTo(1);
				try (ResultSet rs = statement
					.executeQuery("SELECT * FROM rodadas_correcao WHERE id = '%s'".formatted(id))) {
					assertThat(rs.next()).isTrue();
					assertThat(rs.getString("estado")).isEqualTo("corrigida");
					assertThat(rs.getString("submissao_correcao_id")).isEqualTo("44444444-4444-4444-8444-444444444444");
					assertThat(rs.getString("regra_resultante_id")).isEqualTo("55555555-5555-4555-8555-555555555555");
					assertThat(rs.getTimestamp("atualizada_em").toInstant())
						.isEqualTo(java.time.Instant.parse("2026-10-06T12:00:00Z"));
				}
			}
			finally {
				connection.rollback();
			}
		}
	}

	@Test
	void aApiNaoApagaRodadas() {
		assertThat(sqlStateAoFalhar(UsuariosDeBanco.API, "DELETE FROM rodadas_correcao")).isEqualTo(PERMISSAO_NEGADA);
	}

	@Test
	void oCodegenLeRodadas() throws Exception {
		try (Connection connection = como(UsuariosDeBanco.CODEGEN);
				Statement statement = connection.createStatement();
				ResultSet rs = statement.executeQuery("SELECT * FROM rodadas_correcao")) {
			assertThat(rs.next()).isTrue();
			assertThat(rs.getString("job_id")).isEqualTo(JOB_ID);
			assertThat(rs.getString("regra_analisada_id")).isEqualTo("55555555-5555-4555-8555-555555555555");
			assertThat(rs.getString("estado")).isEqualTo("abandonada");
			assertThat(rs.next()).isFalse();
		}
	}

	@Test
	void oCodegenNaoEscreveRodadas() {
		assertThat(sqlStateAoFalhar(UsuariosDeBanco.CODEGEN, INSERE_RODADA)).isEqualTo(PERMISSAO_NEGADA);
		assertThat(sqlStateAoFalhar(UsuariosDeBanco.CODEGEN, "UPDATE rodadas_correcao SET estado = 'corrigida'"))
			.isEqualTo(PERMISSAO_NEGADA);
		assertThat(sqlStateAoFalhar(UsuariosDeBanco.CODEGEN, "DELETE FROM rodadas_correcao"))
			.isEqualTo(PERMISSAO_NEGADA);
	}

	@Test
	void oWorkerNaoAlcancaRodadas() {
		assertThat(sqlStateAoFalhar(UsuariosDeBanco.WORKER, "SELECT * FROM rodadas_correcao"))
			.isEqualTo(PERMISSAO_NEGADA);
		assertThat(sqlStateAoFalhar(UsuariosDeBanco.WORKER, INSERE_RODADA)).isEqualTo(PERMISSAO_NEGADA);
		assertThat(sqlStateAoFalhar(UsuariosDeBanco.WORKER, "UPDATE rodadas_correcao SET estado = 'corrigida'"))
			.isEqualTo(PERMISSAO_NEGADA);
		assertThat(sqlStateAoFalhar(UsuariosDeBanco.WORKER, "DELETE FROM rodadas_correcao"))
			.isEqualTo(PERMISSAO_NEGADA);
	}

	private static final String JOB_ID = "11111111-1111-4111-8111-111111111111";

	private static final String INSERE_TRABALHO = """
			INSERT INTO trabalhos_transcricao (job_id, submissao_id, finalidade, estado, criado_em, atualizado_em)
			VALUES ('11111111-1111-4111-8111-111111111111', '44444444-4444-4444-8444-444444444444',
			        'entrada_inicial', 'pendente', now(), now())
			""";

	@Test
	void apiInsereLeEAtualizaTrabalhoMasNaoApaga() throws Exception {
		try (Connection connection = como(UsuariosDeBanco.API); Statement statement = connection.createStatement()) {
			connection.setAutoCommit(false);
			try {
				statement.execute(INSERE_TRABALHO);
				assertThat(statement
					.executeUpdate("UPDATE trabalhos_transcricao SET estado = 'em_andamento', tentativas = 1"))
					.isEqualTo(1);
				try (ResultSet rs = statement.executeQuery("SELECT estado, tentativas FROM trabalhos_transcricao")) {
					assertThat(rs.next()).isTrue();
					assertThat(rs.getString(1)).isEqualTo("em_andamento");
					assertThat(rs.getInt(2)).isEqualTo(1);
				}
			}
			finally {
				connection.rollback();
			}
		}
		assertThat(sqlStateAoFalhar(UsuariosDeBanco.API, "DELETE FROM trabalhos_transcricao"))
			.isEqualTo(PERMISSAO_NEGADA);
	}

	@Test
	void codegenEWorkerNaoAlcancamTrabalhos() {
		for (String usuario : new String[] { UsuariosDeBanco.CODEGEN, UsuariosDeBanco.WORKER }) {
			for (String sql : new String[] { "SELECT * FROM trabalhos_transcricao", INSERE_TRABALHO,
					"UPDATE trabalhos_transcricao SET estado = 'concluido'", "DELETE FROM trabalhos_transcricao" }) {
				assertThat(sqlStateAoFalhar(usuario, sql)).as("%s: %s", usuario, sql).isEqualTo(PERMISSAO_NEGADA);
			}
		}
	}

	private static final String INSERE_RODADA = """
			INSERT INTO rodadas_correcao (job_id, regra_analisada_id, conflitos, estado, criada_em, atualizada_em)
			VALUES ('%s', '55555555-5555-4555-8555-555555555555',
			    '[{"elementos":["nucleo.percentual"],"motivo":"percentual ausente"}]'::jsonb,
			    'abandonada', now(), now())
			""".formatted(JOB_ID);

	private static final String CODIGO_ID = "33333333-3333-4333-8333-333333333333";

	/**
	 * Com {@code parametros}, que é coluna acrescentada depois da tabela: a permissão do
	 * codegen é de tabela, e por isso já a alcança sem GRANT próprio.
	 */
	private static final String INSERE_EXTRACAO = """
			INSERT INTO extracoes_regras
			    (job_id, submissao_id, resposta_id, representacao, rebaixamentos, parametros, criado_em)
			VALUES ('%s', '44444444-4444-4444-8444-444444444444', '77777777-7777-4777-8777-777777777777',
			        '{"nucleo": {}, "especificacoes": []}'::jsonb, '[]'::jsonb,
			        '{"orcamento": 500000.0, "competencias": ["2025-09"]}'::jsonb, now())
			""".formatted(JOB_ID);

	private static final String INSERE_RESULTADO_COM_DIAGNOSTICO = """
			INSERT INTO resultados_simulacao (job_id, codigo_gerado_id, status, assercoes, diagnostico, criado_em)
			VALUES ('%s', '%s', 'erro_codigo', '[]'::jsonb, '{"causa": "timeout"}'::jsonb, now())
			""".formatted(JOB_ID, CODIGO_ID);

	private static final String ALTERA_DIAGNOSTICO = "UPDATE resultados_simulacao SET diagnostico = '{\"causa\": \"memoria\"}'::jsonb";

	private static final String INSERE_JOB = """
			INSERT INTO jobs (status, usuario_id, competencias, orcamento, criado_em)
			VALUES ('recebido', '%s', '{2025-08}', 1000, now())
			""".formatted("22222222-2222-4222-8222-222222222222");

	/**
	 * As linhas de apoio de que as afirmações dependem: um job para as chaves
	 * estrangeiras, uma submissão para o codegen ler e um código gerado para o worker ler
	 * e tentar alterar.
	 */
	private static void semear(Statement statement) throws SQLException {
		statement.execute("""
				INSERT INTO usuarios (id, login, senha_hash, nome, papel, criado_em)
				VALUES ('22222222-2222-4222-8222-222222222222', 'rh', 'x', 'RH', 'profissional_rh', now())
				""");
		statement.execute("""
				INSERT INTO submissoes (id, usuario_id, tipo, transcricao, criado_em)
				VALUES ('44444444-4444-4444-8444-444444444444', '22222222-2222-4222-8222-222222222222',
				        'voz', 'pague 5% sobre a meta', now())
				""");
		statement.execute("""
				INSERT INTO jobs (id, status, usuario_id, submissao_id, competencias, orcamento, criado_em)
				VALUES ('%s', 'recebido', '22222222-2222-4222-8222-222222222222',
				        '44444444-4444-4444-8444-444444444444', '{2025-08}', 1000, now())
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
		statement.execute("""
				INSERT INTO respostas_modelo (id, job_id, prompt_id, conteudo, criado_em)
				VALUES ('77777777-7777-4777-8777-777777777777', '%s',
				        '66666666-6666-4666-8666-666666666666', 'resposta', now())
				""".formatted(JOB_ID));
		statement.execute(INSERE_RODADA);
	}

	/** Roda o comando como {@code usuario} e devolve o SQLState da recusa. */
	private static String sqlStateAoFalhar(String usuario, String sql) {
		return assertThatExceptionOfType(SQLException.class).isThrownBy(() -> executar(usuario, sql))
			.actual()
			.getSQLState();
	}

	private static void executar(String usuario, String sql) throws SQLException {
		try (Connection connection = como(usuario); Statement statement = connection.createStatement()) {
			statement.execute(sql);
		}
	}

	private static Connection como(String usuario) throws SQLException {
		return DriverManager.getConnection(postgres.getJdbcUrl(), usuario, SENHA);
	}

	private static Connection comoDono() throws SQLException {
		return DriverManager.getConnection(postgres.getJdbcUrl(), postgres.getUsername(), postgres.getPassword());
	}

	private static Liquibase liquibase(Connection connection) throws Exception {
		Database database = DatabaseFactory.getInstance()
			.findCorrectDatabaseImplementation(new JdbcConnection(connection));
		Liquibase liquibase = new Liquibase(CHANGELOG, new ClassLoaderResourceAccessor(), database);
		UsuariosDeBanco.parametrosEm(liquibase);
		return liquibase;
	}

}
