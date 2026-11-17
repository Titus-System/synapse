package synapse.api.auditoria;

import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.stream.Stream;

import ch.qos.logback.classic.spi.ILoggingEvent;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;
import org.junit.jupiter.params.provider.ValueSource;
import org.slf4j.MDC;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import synapse.api.core.config.AppProperties;
import synapse.api.core.logging.CorrelationContext;
import synapse.api.core.security.UsuarioAtual;
import synapse.api.job.CapturaDeLog;
import synapse.api.job.ContratoDeEvento;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class EventosAuditoriaControllerTests {

	private static final UUID AUDITOR = UUID.fromString("cccccccc-cccc-4ccc-8ccc-cccccccccccc");

	private static final String REGRA = "TEXTO-LIVRE-PRIVADO %_!";

	private final EventosAuditoriaService service = mock(EventosAuditoriaService.class);

	private final JdbcTemplate jdbc = mock(JdbcTemplate.class);

	private MockMvc mvc;

	@BeforeEach
	void preparar() {
		when(this.jdbc.queryForList(contains("FROM usuarios"), eq(UUID.class), eq("subject-teste"), eq("login-teste")))
			.thenReturn(List.of(AUDITOR));
		when(this.jdbc.update(contains("UPDATE usuarios"), any(), any(), any(), eq(AUDITOR))).thenReturn(1);
		when(this.service.listar(any(), any())).thenReturn(
				new PaginaEventosAuditoriaDto(List.of(), 0, 20, 0, new ContadoresEventosAuditoriaDto(0, 0, 0, 0)));
		when(this.service.consultarFiltros())
			.thenReturn(new FiltrosEventosAuditoriaDto(List.of(), List.of(), List.of(), List.of(), List.of()));
		CorrelationContext correlacao = new CorrelationContext();
		this.mvc = MockMvcBuilders.standaloneSetup(new EventosAuditoriaController(this.service, correlacao))
			.addInterceptors(
					new AcessoAuditoriaInterceptor(new UsuarioAtual(this.jdbc, mock(AppProperties.class)), correlacao))
			.setControllerAdvice(new AuditoriaAdvice(correlacao))
			.build();
	}

	@AfterEach
	void limpar() {
		SecurityContextHolder.clearContext();
		MDC.clear();
	}

	static Stream<Arguments> papeisRecusados() {
		return Stream
			.of(List.of("profissional-rh"), List.of("auditor", "profissional-rh"), List.of("offline_access"),
					List.<String>of())
			.flatMap(papeis -> Stream.of("/auditoria/eventos", "/auditoria/eventos/filtros")
				.map(rota -> Arguments.of(rota, papeis)));
	}

	@ParameterizedTest
	@MethodSource("papeisRecusados")
	void recusaPapelAntesDeLerDadosOuInterpretarParametros(String rota, List<String> papeis) throws Exception {
		autenticar(papeis);
		this.mvc.perform(get(rota).param("pagina", "nao-e-numero").param("regra", REGRA))
			.andExpect(status().isForbidden())
			.andExpect(jsonPath("$.codigo").value("sem_permissao"));
		verifyNoInteractions(this.service);
	}

	@ParameterizedTest
	@ValueSource(strings = { "/auditoria/eventos", "/auditoria/eventos/filtros" })
	void auditorRecebeAsRespostasDoContrato(String rota) throws Exception {
		autenticar(List.of("default-roles-synapse", "auditor"));
		String corpo = this.mvc.perform(get(rota))
			.andExpect(status().isOk())
			.andReturn()
			.getResponse()
			.getContentAsString();
		ContratoDeEvento.validarRespostaHttp(
				rota.endsWith("filtros") ? "FiltrosEventosAuditoria" : "PaginaEventosAuditoria", corpo);
		if (rota.endsWith("filtros")) {
			verify(this.service).consultarFiltros();
		}
		else {
			verify(this.service).listar(new ConsultaEventosAuditoria(null, null, null, null, null, null),
					new PaginaAuditoria(0, 20));
		}
	}

	@Test
	void nomeNuloPermanecePresenteNoJobDoEvento() throws Exception {
		autenticar(List.of("auditor"));
		EventoAuditoriaDto evento = new EventoAuditoriaDto(Instant.parse("2026-11-01T02:30:00Z"), "entrada", "usuario",
				"rh", new JobEventoAuditoriaDto(UUID.randomUUID(), null, "gerando_regra"), UUID.randomUUID(), null,
				null, null, "entrada_inicial", "voz", null, null, null, null, null);
		when(this.service.listar(any(), any())).thenReturn(new PaginaEventosAuditoriaDto(List.of(evento), 0, 20, 1,
				new ContadoresEventosAuditoriaDto(1, 1, 1, 0)));
		String corpo = this.mvc.perform(get("/auditoria/eventos"))
			.andExpect(status().isOk())
			.andReturn()
			.getResponse()
			.getContentAsString();
		ContratoDeEvento.validarRespostaHttp("PaginaEventosAuditoria", corpo);
		JsonNode item = new JsonMapper().readTree(corpo).path("itens").path(0);
		assertThat(item.path("job").has("nome")).isTrue();
		assertThat(item.path("job").path("nome").isNull()).isTrue();
		assertThat(item.has("status")).isFalse();
		assertThat(item.has("loja")).isFalse();
	}

	@Test
	void encaminhaTodosOsFiltrosEPaginacaoSemAlterarCodigos() throws Exception {
		autenticar(List.of("auditor"));
		this.mvc
			.perform(get("/auditoria/eventos").param("usuario", "rh.a")
				.param("mes", "2026-10")
				.param("loja", "0013")
				.param("marca", "10")
				.param("cargo", "100")
				.param("regra", REGRA)
				.param("pagina", "2")
				.param("tamanho", "5"))
			.andExpect(status().isOk());
		verify(this.service).listar(new ConsultaEventosAuditoria("rh.a", "2026-10", "0013", "10", "100", REGRA),
				new PaginaAuditoria(2, 5));
	}

	static Stream<Arguments> parametrosInvalidos() {
		return Stream.of(Arguments.of("pagina", "-1"), Arguments.of("pagina", "uma"),
				Arguments.of("pagina", "2147483648"), Arguments.of("tamanho", "0"), Arguments.of("tamanho", "101"),
				Arguments.of("tamanho", "vinte"), Arguments.of("mes", "2026-1"), Arguments.of("mes", "2026-13"),
				Arguments.of("mes", "2026-00"), Arguments.of("mes", "2026-10-01"), Arguments.of("mes", ""),
				Arguments.of("usuario", ""), Arguments.of("loja", ""), Arguments.of("marca", ""),
				Arguments.of("cargo", ""), Arguments.of("regra", ""), Arguments.of("usuario", "a\0b"),
				Arguments.of("loja", "13\0"), Arguments.of("marca", "10\0"), Arguments.of("cargo", "100\0"),
				Arguments.of("regra", "texto\0livre"));
	}

	@ParameterizedTest
	@MethodSource("parametrosInvalidos")
	void parametroInvalidoRetorna400SemConsultarServico(String parametro, String valor) throws Exception {
		autenticar(List.of("auditor"));
		List<ILoggingEvent> eventos;
		try (CapturaDeLog captura = new CapturaDeLog(EventosAuditoriaController.class)) {
			this.mvc.perform(get("/auditoria/eventos").param(parametro, valor))
				.andExpect(status().isBadRequest())
				.andExpect(jsonPath("$.codigo").value("requisicao_invalida"));
			eventos = captura.eventos();
		}
		verifyNoInteractions(this.service);
		assertThat(eventos).hasSize(1);
		JsonNode linha = validarLog(eventos.getFirst(), "WARN");
		assertThat(linha.path("extra").path("resultado").asString()).isEqualTo("requisicao_invalida");
		assertThat(MDC.get(CorrelationContext.USER_ID_KEY)).isNull();
	}

	@Test
	void conclusaoLogaUsuarioFiltrosPreenchidosEPaginaSemTextoLivre() throws Exception {
		autenticar(List.of("auditor"));
		List<ILoggingEvent> eventos;
		try (CapturaDeLog captura = new CapturaDeLog(EventosAuditoriaController.class)) {
			this.mvc
				.perform(get("/auditoria/eventos").param("usuario", "rh.a")
					.param("mes", "2026-10")
					.param("loja", "13")
					.param("marca", "10")
					.param("cargo", "100")
					.param("regra", REGRA)
					.param("pagina", "2")
					.param("tamanho", "5"))
				.andExpect(status().isOk());
			eventos = captura.eventos();
		}
		assertThat(eventos).hasSize(1);
		JsonNode linha = validarLog(eventos.getFirst(), "INFO");
		assertThat(linha.path("message").asString()).isEqualTo("consulta de eventos de auditoria encerrada");
		JsonNode extra = linha.path("extra");
		assertThat(extra.path("operacao").asString()).isEqualTo("listar_eventos_auditoria");
		assertThat(extra.path("resultado").asString()).isEqualTo("sucesso");
		assertThat(extra.path("filtros_preenchidos").toString()).contains("usuario", "mes", "loja", "marca", "cargo",
				"regra");
		assertThat(extra.path("pagina").asInt()).isEqualTo(2);
		assertThat(extra.path("tamanho").asInt()).isEqualTo(5);
		assertThat(extra.path("total").asLong()).isZero();
		assertThat(extra.path("duracao_ms").asLong()).isGreaterThanOrEqualTo(0);
		assertThat(MDC.get(CorrelationContext.USER_ID_KEY)).isNull();
	}

	@ParameterizedTest
	@ValueSource(strings = { "/auditoria/eventos", "/auditoria/eventos/filtros" })
	void erroDePersistenciaNaoExpoeDetalhesERestauraContexto(String rota) throws Exception {
		autenticar(List.of("auditor"));
		DataAccessResourceFailureException erro = new DataAccessResourceFailureException(
				"SELECT fonte FROM codigos_gerados " + REGRA);
		when(this.service.listar(any(), any())).thenThrow(erro);
		when(this.service.consultarFiltros()).thenThrow(erro);
		MDC.put(CorrelationContext.USER_ID_KEY, "contexto-anterior");
		List<ILoggingEvent> eventos;
		try (CapturaDeLog captura = new CapturaDeLog(EventosAuditoriaController.class)) {
			String corpo = this.mvc.perform(get(rota).param("regra", REGRA))
				.andExpect(status().isInternalServerError())
				.andReturn()
				.getResponse()
				.getContentAsString();
			assertThat(corpo).doesNotContain("SELECT", "codigos_gerados", REGRA);
			eventos = captura.eventos();
		}
		assertThat(eventos).hasSize(1);
		assertThat(validarLog(eventos.getFirst(), "ERROR").path("extra").path("resultado").asString())
			.isEqualTo("falha");
		assertThat(MDC.get(CorrelationContext.USER_ID_KEY)).isEqualTo("contexto-anterior");
		assertThat(MDC.get(CorrelationContext.JOB_ID_KEY)).isNull();
	}

	@ParameterizedTest
	@ValueSource(strings = { "/auditoria/eventos", "/auditoria/eventos/filtros" })
	void recusaPorPapelLogaWarnSemDadosDoToken(String rota) throws Exception {
		autenticar(List.of("profissional-rh"));
		List<ILoggingEvent> eventos;
		try (CapturaDeLog captura = new CapturaDeLog(AcessoAuditoriaInterceptor.class)) {
			this.mvc.perform(get(rota).param("regra", REGRA)).andExpect(status().isForbidden());
			eventos = captura.eventos();
		}
		assertThat(eventos).hasSize(1);
		JsonNode linha = validarLog(eventos.getFirst(), "WARN");
		assertThat(linha.path("message").asString()).isEqualTo("acesso à auditoria recusado");
		assertThat(MDC.get(CorrelationContext.USER_ID_KEY)).isNull();
	}

	@Test
	void conclusaoDasOpcoesLogaUsuarioETotal() throws Exception {
		autenticar(List.of("auditor"));
		when(this.service.consultarFiltros()).thenReturn(new FiltrosEventosAuditoriaDto(List.of("rh"),
				List.of("2026-10"), List.of("13"), List.of("10"), List.of("100")));
		List<ILoggingEvent> eventos;
		try (CapturaDeLog captura = new CapturaDeLog(EventosAuditoriaController.class)) {
			this.mvc.perform(get("/auditoria/eventos/filtros")).andExpect(status().isOk());
			eventos = captura.eventos();
		}
		assertThat(eventos).hasSize(1);
		JsonNode linha = validarLog(eventos.getFirst(), "INFO");
		assertThat(linha.path("message").asString()).isEqualTo("consulta de filtros de auditoria encerrada");
		assertThat(linha.path("extra").path("operacao").asString()).isEqualTo("consultar_filtros_eventos_auditoria");
		assertThat(linha.path("extra").path("resultado").asString()).isEqualTo("sucesso");
		assertThat(linha.path("extra").path("total").asLong()).isEqualTo(5);
		assertThat(MDC.get(CorrelationContext.USER_ID_KEY)).isNull();
	}

	private static JsonNode validarLog(ILoggingEvent evento, String nivel) throws Exception {
		String serializado = CapturaDeLog.emJson(evento);
		ContratoDeEvento.validarLog(serializado);
		assertThat(serializado).doesNotContain(REGRA, "subject-teste", "login-teste", "TOKEN-PRIVADO", "SELECT",
				"codigos_gerados");
		JsonNode linha = new JsonMapper().readTree(serializado);
		assertThat(linha.path("level").asString()).isEqualTo(nivel);
		assertThat(linha.path("user_id").asString()).isEqualTo(AUDITOR.toString());
		assertThat(linha.has("job_id")).isFalse();
		return linha;
	}

	private static void autenticar(List<String> papeis) {
		Jwt token = Jwt.withTokenValue("TOKEN-PRIVADO")
			.header("alg", "RS256")
			.subject("subject-teste")
			.claim("preferred_username", "login-teste")
			.claim("realm_access", Map.of("roles", papeis))
			.build();
		SecurityContextHolder.getContext().setAuthentication(new JwtAuthenticationToken(token));
	}

}
