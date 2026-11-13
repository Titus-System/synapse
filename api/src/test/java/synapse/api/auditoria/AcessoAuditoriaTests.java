package synapse.api.auditoria;

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
import tools.jackson.databind.json.JsonMapper;

import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;
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
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * A política das rotas de auditoria, com o {@link UsuarioAtual} real sobre um banco
 * simulado: a recusa acontece antes do controller, sem ler dado de job.
 */
class AcessoAuditoriaTests {

	private static final UUID USUARIO = UUID.randomUUID();

	private static final UUID JOB = UUID.randomUUID();

	private final AuditoriaService service = mock(AuditoriaService.class);

	private final JdbcTemplate jdbc = mock(JdbcTemplate.class);

	private MockMvc mvc;

	@BeforeEach
	void preparar() {
		when(this.jdbc.queryForList(contains("FROM usuarios"), eq(UUID.class), eq("subject-a"), eq("login-a")))
			.thenReturn(List.of(USUARIO));
		when(this.jdbc.update(contains("UPDATE usuarios"), any(), any(), any(), eq(USUARIO))).thenReturn(1);
		when(this.service.listar(any())).thenReturn(new PaginaJobsAuditoriaDto(List.of(), 0, 20, 0));
		CorrelationContext correlacao = new CorrelationContext();
		UsuarioAtual usuario = new UsuarioAtual(this.jdbc, mock(AppProperties.class));
		this.mvc = MockMvcBuilders.standaloneSetup(new AuditoriaController(this.service, correlacao))
			.addInterceptors(new AcessoAuditoriaInterceptor(usuario, correlacao))
			.setControllerAdvice(new AuditoriaAdvice())
			.build();
	}

	@AfterEach
	void limparSessao() {
		SecurityContextHolder.clearContext();
		MDC.clear();
	}

	static Stream<Arguments> papeisRecusados() {
		return Stream
			.of(List.of("profissional-rh"), List.of("offline_access", "profissional-rh"), List.<String>of(),
					List.of("offline_access"), List.of("profissional-rh", "auditor"))
			.flatMap(papeis -> Stream.of("listar", "consultar").map(rota -> Arguments.of(rota, papeis)));
	}

	@ParameterizedTest(name = "{0} recusada para {1}")
	@MethodSource("papeisRecusados")
	void papelDiferenteDeAuditorRecebe403SemChegarAoServico(String rota, List<String> papeis) throws Exception {
		autenticar(papeis);
		this.mvc.perform(pedido(rota))
			.andExpect(status().isForbidden())
			.andExpect(content().contentType(MediaType.APPLICATION_JSON))
			.andExpect(jsonPath("$.codigo").value("sem_permissao"))
			.andExpect(jsonPath("$.mensagem").value("Você não tem permissão para esta ação."));
		verifyNoInteractions(this.service);
		if (!papeis.contains("profissional-rh") || papeis.contains("auditor")) {
			verifyNoInteractions(this.jdbc);
		}
	}

	@ParameterizedTest
	@ValueSource(strings = { "listar", "consultar" })
	void auditorPassaSemConferirPosse(String rota) throws Exception {
		autenticar(List.of("default-roles-synapse", "auditor"));
		this.mvc.perform(pedido(rota)).andExpect(status().isOk());
		if (rota.equals("listar")) {
			verify(this.service).listar(new PaginaAuditoria(0, 20));
		}
		else {
			verify(this.service).consultar(JOB);
		}
	}

	@Test
	void recusaPrecedeALeituraDoIdMalformado() throws Exception {
		autenticar(List.of("profissional-rh"));
		this.mvc.perform(get("/auditoria/jobs/{id}", "nao-e-uuid")).andExpect(status().isForbidden());
		autenticar(List.of("auditor"));
		this.mvc.perform(get("/auditoria/jobs/{id}", "nao-e-uuid"))
			.andExpect(status().isBadRequest())
			.andExpect(jsonPath("$.codigo").value("requisicao_invalida"))
			.andExpect(jsonPath("$.mensagem").value("O identificador do job precisa ser um UUID."));
		verifyNoInteractions(this.service);
	}

	@Test
	void jobInexistenteRecebe404() throws Exception {
		autenticar(List.of("auditor"));
		when(this.service.consultar(JOB)).thenThrow(new JobNaoEncontradoNaAuditoriaException());
		this.mvc.perform(pedido("consultar"))
			.andExpect(status().isNotFound())
			.andExpect(jsonPath("$.codigo").value("job_nao_encontrado"))
			.andExpect(jsonPath("$.mensagem").value("Job não encontrado."));
	}

	static Stream<Arguments> paginacaoInvalida() {
		String pagina = "O parâmetro pagina precisa ser um inteiro maior ou igual a zero.";
		String tamanho = "O parâmetro tamanho precisa ser um inteiro entre 1 e 100.";
		return Stream.of(Arguments.of("pagina", "-1", pagina), Arguments.of("pagina", "um", pagina),
				Arguments.of("tamanho", "0", tamanho), Arguments.of("tamanho", "101", tamanho),
				Arguments.of("tamanho", "vinte", tamanho));
	}

	@ParameterizedTest(name = "{0}={1}")
	@MethodSource("paginacaoInvalida")
	void paginacaoInvalidaRecebe400ComAMensagemDaListagemDeJobs(String parametro, String valor, String mensagem)
			throws Exception {
		autenticar(List.of("auditor"));
		this.mvc.perform(get("/auditoria/jobs").param(parametro, valor))
			.andExpect(status().isBadRequest())
			.andExpect(jsonPath("$.codigo").value("requisicao_invalida"))
			.andExpect(jsonPath("$.mensagem").value(mensagem));
		verifyNoInteractions(this.service);
	}

	@Test
	void recusaPorPapelLogaWarnComOUsuarioLocalESemDadosDoToken() throws Exception {
		autenticar(List.of("profissional-rh"));
		List<ILoggingEvent> eventos;
		try (CapturaDeLog captura = new CapturaDeLog(AcessoAuditoriaInterceptor.class)) {
			this.mvc.perform(pedido("consultar")).andExpect(status().isForbidden());
			eventos = captura.eventos();
		}
		assertThat(eventos).hasSize(1);
		String linha = CapturaDeLog.emJson(eventos.getFirst());
		ContratoDeEvento.validarLog(linha);
		Map<?, ?> json = new JsonMapper().readValue(linha, Map.class);
		assertThat(json.get("level")).isEqualTo("WARN");
		assertThat(json.get("message")).isEqualTo("acesso à auditoria recusado");
		assertThat(json.get("user_id")).isEqualTo(USUARIO.toString());
		assertThat(json.containsKey("job_id")).isFalse();
		assertThat(linha).doesNotContain("subject-a", "login-a", "profissional-rh");
		assertThat(MDC.get(CorrelationContext.USER_ID_KEY)).isNull();
	}

	@Test
	void identidadeRecusadaLogaWarnSemUsuario() throws Exception {
		autenticar(List.of("profissional-rh", "auditor"));
		List<ILoggingEvent> eventos;
		try (CapturaDeLog captura = new CapturaDeLog(AcessoAuditoriaInterceptor.class)) {
			this.mvc.perform(pedido("listar")).andExpect(status().isForbidden());
			eventos = captura.eventos();
		}
		assertThat(eventos).hasSize(1);
		String linha = CapturaDeLog.emJson(eventos.getFirst());
		ContratoDeEvento.validarLog(linha);
		assertThat(linha).contains("\"identidade_recusada\"").doesNotContain("user_id", "subject-a", "login-a");
	}

	@Test
	void falhaInesperadaLogaErroEFechaACorrelacao() throws Exception {
		autenticar(List.of("auditor"));
		when(this.service.consultar(JOB)).thenThrow(new org.springframework.dao.DataAccessResourceFailureException(
				"SELECT conteudo FROM prompts WHERE job_id = ?"));
		List<ILoggingEvent> eventos;
		try (CapturaDeLog captura = new CapturaDeLog(AuditoriaController.class)) {
			this.mvc.perform(pedido("consultar")).andExpect(status().isInternalServerError());
			eventos = captura.eventos();
		}
		assertThat(eventos).hasSize(1);
		String linha = CapturaDeLog.emJson(eventos.getFirst());
		ContratoDeEvento.validarLog(linha);
		assertThat(linha).contains("\"ERROR\"", "\"falha\"", JOB.toString(), USUARIO.toString())
			.doesNotContain("SELECT", "prompts");
		assertThat(MDC.get(CorrelationContext.JOB_ID_KEY)).isNull();
		assertThat(MDC.get(CorrelationContext.USER_ID_KEY)).isNull();
	}

	private static MockHttpServletRequestBuilder pedido(String rota) {
		return rota.equals("listar") ? get("/auditoria/jobs") : get("/auditoria/jobs/{id}", JOB);
	}

	private static void autenticar(List<String> papeis) {
		Jwt token = Jwt.withTokenValue("teste")
			.header("alg", "RS256")
			.subject("subject-a")
			.claim("preferred_username", "login-a")
			.claim("realm_access", Map.of("roles", papeis))
			.build();
		SecurityContextHolder.getContext().setAuthentication(new JwtAuthenticationToken(token));
	}

}
