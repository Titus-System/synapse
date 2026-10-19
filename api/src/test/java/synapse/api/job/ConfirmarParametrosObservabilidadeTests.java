package synapse.api.job;

import java.util.Objects;
import java.util.UUID;

import io.micrometer.core.instrument.MeterRegistry;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.condition.EnabledIf;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.slf4j.MDC;
import org.testcontainers.DockerClientFactory;
import org.testcontainers.postgresql.PostgreSQLContainer;
import org.testcontainers.rabbitmq.RabbitMQContainer;
import tools.jackson.databind.json.JsonMapper;

import org.springframework.boot.WebApplicationType;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.web.client.RestClient;

import synapse.api.ApiApplication;
import synapse.api.core.logging.CorrelationContext;
import synapse.api.core.metrics.AppMetrics;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

@EnabledIf("dockerIsAvailable")
class ConfirmarParametrosObservabilidadeTests {

	private static final String OPERACAO = "confirmacao_parametros";

	private static PostgreSQLContainer postgres;

	private static RabbitMQContainer rabbit;

	private static ConfigurableApplicationContext contexto;

	private static JdbcTemplate dono;

	private static UUID usuario;

	static boolean dockerIsAvailable() {
		return DockerClientFactory.instance().isDockerAvailable();
	}

	@BeforeAll
	static void preparar() {
		postgres = new PostgreSQLContainer("postgres:18-alpine");
		postgres.start();
		rabbit = new RabbitMQContainer("rabbitmq:3.13-management-alpine");
		rabbit.start();
		contexto = new SpringApplicationBuilder(ApiApplication.class).web(WebApplicationType.SERVLET)
			.run("--server.port=0", "--app.postgres.host=" + postgres.getHost(),
					"--app.postgres.port=" + postgres.getMappedPort(5432),
					"--app.postgres.database=" + postgres.getDatabaseName(),
					"--app.postgres.owner.user=" + postgres.getUsername(),
					"--app.postgres.owner.password=" + postgres.getPassword(), "--app.postgres.user=synapse_api",
					"--app.postgres.password=senha-de-teste", "--app.rabbitmq.host=" + rabbit.getHost(),
					"--app.rabbitmq.port=" + rabbit.getAmqpPort(), "--app.rabbitmq.user=" + rabbit.getAdminUsername(),
					"--app.rabbitmq.password=" + rabbit.getAdminPassword(), "--app.outbox.enabled=false",
					"--management.health.rabbit.enabled=false", "--management.health.db.enabled=false");
		dono = new JdbcTemplate(
				new DriverManagerDataSource(postgres.getJdbcUrl(), postgres.getUsername(), postgres.getPassword()));
		dono.execute("ALTER ROLE synapse_api WITH PASSWORD 'senha-de-teste'");
		usuario = Objects.requireNonNull(dono.queryForObject("""
				INSERT INTO usuarios (login, senha_hash, nome, papel, criado_em)
				VALUES ('t217-observabilidade', 'x', 'RH', 'profissional_rh', now()) RETURNING id
				""", UUID.class));
	}

	@AfterAll
	static void encerrar() {
		if (contexto != null) {
			contexto.close();
		}
		if (rabbit != null) {
			rabbit.stop();
		}
		if (postgres != null) {
			postgres.stop();
		}
	}

	@ParameterizedTest
	@ValueSource(strings = { "confirmada", "falha", "recusada" })
	void fluxoRealEmiteLogsSanitizadosEMetricasExpostasAposODesfecho(String resultado) throws Exception {
		UUID job = contexto.getBean(JobService.class)
			.criar(CriarJobRequisicao.deJson(CriarJobControllerTests.FORMULARIO), usuario)
			.id();
		dono.update("UPDATE jobs SET status = 'aguardando_confirmacao_parametros' WHERE id = ?", job);
		dono.update("""
				INSERT INTO rodadas_correcao (job_id, regra_analisada_id, conflitos, estado, criada_em, atualizada_em)
				SELECT job_id, id, '[{"elemento_ref":"nucleo.percentual","motivo":"segredo conflito T217"}]'::jsonb,
				'pendente', now(), now() FROM regras WHERE job_id = ?
				""", job);
		boolean falha = "falha".equals(resultado);
		if (falha) {
			dono.execute(
					"CREATE FUNCTION t217_falhar() RETURNS trigger LANGUAGE plpgsql AS 'BEGIN RAISE EXCEPTION ''segredo banco T217''; END'");
			dono.execute(
					"CREATE TRIGGER t217_falha BEFORE UPDATE ON rodadas_correcao FOR EACH ROW EXECUTE FUNCTION t217_falhar()");
		}
		AppMetrics metricas = contexto.getBean(AppMetrics.class);
		double tentativas = metricas.jobRuns(OPERACAO).count();
		double falhas = metricas.jobFailures(OPERACAO).count();
		long duracoes = metricas.jobDuration(OPERACAO).count();
		double tempo = metricas.jobDuration(OPERACAO).totalTime(java.util.concurrent.TimeUnit.NANOSECONDS);
		try (var externo = new CorrelationContext().abrir("job-anterior", "usuario-anterior");
				var logs = new CapturaDeLog(JobController.class);
				var fechamento = new CapturaDeLog("synapse.api.job.BuscarJobService")) {
			JobController controller = contexto.getBean(JobController.class);
			if (falha) {
				assertThatThrownBy(() -> controller.confirmar(job, ConfirmarParametrosControllerTests.CONFIRMAR))
					.isInstanceOf(DataAccessException.class);
			}
			else if ("recusada".equals(resultado)) {
				assertThatThrownBy(() -> controller.confirmar(job, "{}"))
					.isInstanceOf(ConfirmarParametrosException.class);
			}
			else {
				assertThat(
						controller.confirmar(job, ConfirmarParametrosControllerTests.CONFIRMAR).getStatusCode().value())
					.isEqualTo(202);
			}
			assertThat(logs.eventos()).hasSize(2);
			assertThat(logs.eventos().getFirst().getFormattedMessage()).isEqualTo("confirmação de parâmetros iniciada");
			assertThat(logs.eventos().getLast().getFormattedMessage()).isEqualTo("confirmação de parâmetros encerrada");
			JsonMapper json = new JsonMapper();
			assertThat(json.readTree(CapturaDeLog.emJson(logs.eventos().getLast()))
				.path("extra")
				.path("resultado")
				.asString()).isEqualTo(resultado);
			for (var evento : logs.eventos()) {
				String linha = CapturaDeLog.emJson(evento);
				ContratoDeEvento.validarLog(linha);
				assertThat(json.readTree(linha).path("job_id").asString()).isEqualTo(job.toString());
				assertThat(linha).doesNotContain("segredo", "485000", "percentual", "stack", "PSQLException");
			}
			assertThat(fechamento.eventos()).hasSize("confirmada".equals(resultado) ? 1 : 0);
			for (var evento : fechamento.eventos()) {
				String linha = CapturaDeLog.emJson(evento);
				ContratoDeEvento.validarLog(linha);
				assertThat(json.readTree(linha).path("job_id").asString()).isEqualTo(job.toString());
				assertThat(linha).doesNotContain("segredo", "percentual");
			}
			assertThat(MDC.get("job_id")).isEqualTo("job-anterior");
			assertThat(MDC.get("user_id")).isEqualTo("usuario-anterior");
			assertThat(metricas.jobRuns(OPERACAO).count()).isEqualTo(tentativas + 1);
			assertThat(metricas.jobFailures(OPERACAO).count())
				.isEqualTo(falhas + ("confirmada".equals(resultado) ? 0 : 1));
			assertThat(metricas.jobDuration(OPERACAO).count()).isEqualTo(duracoes + 1);
			assertThat(metricas.jobDuration(OPERACAO).totalTime(java.util.concurrent.TimeUnit.NANOSECONDS))
				.isGreaterThan(tempo);
			assertThat(contexto.getBean(MeterRegistry.class).get("job.runs").tag("job_name", OPERACAO).counter())
				.isSameAs(metricas.jobRuns(OPERACAO));
			String scrape = RestClient
				.create("http://localhost:" + contexto.getEnvironment().getProperty("local.server.port"))
				.get()
				.uri("/metrics")
				.retrieve()
				.body(String.class);
			assertThat(scrape)
				.contains("job_runs_total", "job_failures_total", "job_duration_seconds_count",
						"job_name=\"confirmacao_parametros\"")
				.doesNotContain(job.toString(), usuario.toString());
			assertThat(amostra(Objects.requireNonNull(scrape), "job_runs_total")).isEqualTo(tentativas + 1);
			assertThat(amostra(scrape, "job_failures_total"))
				.isEqualTo(falhas + ("confirmada".equals(resultado) ? 0 : 1));
			assertThat(amostra(scrape, "job_duration_seconds_count")).isEqualTo((double) duracoes + 1);
		}
		finally {
			if (falha) {
				dono.execute("DROP TRIGGER t217_falha ON rodadas_correcao");
				dono.execute("DROP FUNCTION t217_falhar()");
			}
		}
		assertThat(MDC.get("job_id")).isNull();
	}

	private static double amostra(String scrape, String nome) {
		String linha = scrape.lines()
			.filter(valor -> valor.startsWith(nome + "{") && valor.contains("job_name=\"confirmacao_parametros\""))
			.findFirst()
			.orElseThrow();
		return Double.parseDouble(linha.substring(linha.lastIndexOf(' ') + 1));
	}

}
