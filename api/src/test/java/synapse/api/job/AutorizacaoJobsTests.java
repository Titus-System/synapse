package synapse.api.job;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.stream.Stream;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;

import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import synapse.api.core.config.AppProperties;
import synapse.api.core.logging.CorrelationContext;
import synapse.api.core.security.UsuarioAtual;
import synapse.api.core.sse.EmissoresSse;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class AutorizacaoJobsTests {

	static final UUID USUARIO = UUID.randomUUID();

	static final UUID JOB = UUID.randomUUID();

	private final JdbcTemplate jdbc = mock(JdbcTemplate.class);

	private final CriarJobService criar = mock(CriarJobService.class);

	private final ListarJobsService listar = mock(ListarJobsService.class);

	private final BuscarJobService buscar = mock(BuscarJobService.class);

	private final AcompanharJobService acompanhar = mock(AcompanharJobService.class);

	private final ConfirmarParametrosService confirmar = mock(ConfirmarParametrosService.class);

	private final ExecutarAcaoService executar = mock(ExecutarAcaoService.class);

	private final ReprocessarJobService reprocessar = mock(ReprocessarJobService.class);

	private final EmissoresSse emissores = mock(EmissoresSse.class);

	private MockMvc mvc;

	@BeforeEach
	void preparar() {
		when(this.jdbc.queryForList(contains("FROM usuarios"), eq(UUID.class), eq("subject-a"), eq("login-a")))
			.thenReturn(List.of(USUARIO));
		when(this.jdbc.update(contains("UPDATE usuarios"), any(), any(), any(), eq(USUARIO))).thenReturn(1);
		when(this.jdbc.queryForList(contains("FROM jobs"), eq(UUID.class), eq(JOB))).thenReturn(List.of(USUARIO));
		UsuarioAtual usuario = new UsuarioAtual(this.jdbc, mock(AppProperties.class));
		this.mvc = MockMvcBuilders
			.standaloneSetup(new CriarJobController(this.criar), new ListarJobsController(this.listar),
					new BuscarJobController(this.buscar),
					new AcompanharJobController(this.acompanhar, new CorrelationContext()),
					new ConfirmarParametrosController(this.confirmar),
					new ExecutarAcaoController(this.executar, this.emissores),
					new ReprocessarJobController(this.reprocessar), new RotaSemPolitica())
			.addInterceptors(new AutorizacaoJobsInterceptor(usuario, new AutorizadorDeJob(this.jdbc)))
			.setControllerAdvice(new AutorizacaoDeJobAdvice(), new BuscarJobAdvice(), new AcompanharJobAdvice(),
					new ConfirmarParametrosAdvice(), new ReprocessarJobAdvice(), new CriarJobAdvice(),
					new ExecutarAcaoAdvice())
			.build();
	}

	@AfterEach
	void limparSessao() {
		SecurityContextHolder.clearContext();
	}

	@Test
	void preflightCorsNaoResolveUsuarioNemAplicaPoliticaDeNegocio() {
		UsuarioAtual usuario = mock(UsuarioAtual.class);
		AutorizadorDeJob autorizador = mock(AutorizadorDeJob.class);
		AutorizacaoJobsInterceptor interceptor = new AutorizacaoJobsInterceptor(usuario, autorizador);
		MockHttpServletRequest pedido = new MockHttpServletRequest("OPTIONS", "/jobs");
		pedido.addHeader("Origin", "https://app.exemplo.com");
		pedido.addHeader("Access-Control-Request-Method", "POST");

		assertThat(interceptor.preHandle(pedido, new MockHttpServletResponse(), new Object())).isTrue();
		verifyNoInteractions(usuario, autorizador);
	}

	@ParameterizedTest
	@MethodSource("requisicoesSemPreflight")
	void somentePreflightRealIgnoraPoliticaDeNegocio(String metodo, boolean origem, boolean metodoCors) {
		UsuarioAtual usuario = mock(UsuarioAtual.class);
		AutorizadorDeJob autorizador = mock(AutorizadorDeJob.class);
		AutorizacaoJobsInterceptor interceptor = new AutorizacaoJobsInterceptor(usuario, autorizador);
		MockHttpServletRequest pedido = new MockHttpServletRequest(metodo, "/jobs");
		if (origem) {
			pedido.addHeader("Origin", "https://app.exemplo.com");
		}
		if (metodoCors) {
			pedido.addHeader("Access-Control-Request-Method", "POST");
		}

		assertThatThrownBy(() -> interceptor.preHandle(pedido, new MockHttpServletResponse(), new Object()))
			.isInstanceOf(SemPermissaoNoJobException.class);
		verifyNoInteractions(usuario, autorizador);
	}

	static Stream<Arguments> requisicoesSemPreflight() {
		return Stream.of(Arguments.of("OPTIONS", false, false), Arguments.of("OPTIONS", true, false),
				Arguments.of("OPTIONS", false, true), Arguments.of("GET", true, true));
	}

	static Stream<Arguments> matriz() {
		return Stream
			.of(List.of("profissional-rh"), List.of("auditor"), List.<String>of(),
					List.of("profissional-rh", "auditor"), List.of("offline_access", "profissional-rh"),
					List.of("default-roles-synapse", "auditor"))
			.flatMap(papeis -> rotas()
				.flatMap(rota -> Stream.of(true, false).map(dono -> Arguments.of(rota, papeis, dono))));
	}

	static Stream<String> rotas() {
		return Stream.of("criar", "listar", "buscar", "events", "parameters", "reprocessar", "confirmar_liberar",
				"cancelar", "salvar", "arquivar");
	}

	@ParameterizedTest(name = "{0} papeis={1} dono={2}")
	@MethodSource("matriz")
	void aplicaMatrizAntesDeExecutarController(String rota, List<String> papeis, boolean dono) throws Exception {
		autenticar(papeis);
		prepararRespostas();
		when(this.jdbc.queryForList(contains("FROM jobs"), eq(UUID.class), eq(JOB)))
			.thenReturn(List.of(dono ? USUARIO : UUID.randomUUID()));
		boolean permitido = papeis.contains("profissional-rh") && !papeis.contains("auditor")
				&& (dono || rota.equals("criar") || rota.equals("listar"));
		if (permitido) {
			this.mvc.perform(pedido(rota))
				.andExpect(status().is(rota.equals("parameters") ? 202
						: rota.equals("criar") || rota.equals("reprocessar") ? 201 : 200));
			verificarServico(rota);
		}
		else {
			this.mvc.perform(pedido(rota))
				.andExpect(status().isForbidden())
				.andExpect(content().contentType(MediaType.APPLICATION_JSON))
				.andExpect(jsonPath("$.codigo").value("sem_permissao"))
				.andExpect(jsonPath("$.mensagem").value("Você não tem permissão para esta ação."));
			verifyNoInteractions(this.criar, this.listar, this.buscar, this.acompanhar, this.confirmar, this.executar,
					this.reprocessar, this.emissores);
			if (papeis.isEmpty() || papeis.containsAll(List.of("profissional-rh", "auditor"))) {
				verifyNoInteractions(this.jdbc);
			}
		}
	}

	@Test
	void rotaSemPoliticaERecusadaMesmoComRhAutenticado() throws Exception {
		autenticar(List.of("profissional-rh"));
		this.mvc.perform(get("/jobs/sem-politica")).andExpect(status().isForbidden());
		verifyNoInteractions(this.jdbc);
	}

	@Test
	void inexistentePreserva404() throws Exception {
		autenticar(List.of("profissional-rh"));
		when(this.jdbc.queryForList(contains("FROM jobs"), eq(UUID.class), eq(JOB))).thenReturn(List.of());
		this.mvc.perform(get("/jobs/{id}", JOB))
			.andExpect(status().isNotFound())
			.andExpect(jsonPath("$.codigo").value("job_nao_encontrado"));
		verifyNoInteractions(this.buscar);
	}

	@Test
	void reconexaoSseConsultaPosseNovamenteAntesDeAbrirEmissor() throws Exception {
		autenticar(List.of("profissional-rh"));
		when(this.acompanhar.acompanhar(JOB)).thenReturn(new SseEmitter());
		this.mvc.perform(pedido("events")).andExpect(status().isOk()).andExpect(request().asyncStarted());
		when(this.jdbc.queryForList(contains("FROM jobs"), eq(UUID.class), eq(JOB)))
			.thenReturn(List.of(UUID.randomUUID()));
		this.mvc.perform(pedido("events").header("Last-Event-ID", "1")).andExpect(status().isForbidden());
		verify(this.acompanhar, times(1)).acompanhar(JOB);
		verify(this.jdbc, times(2)).queryForList(contains("FROM jobs"), eq(UUID.class), eq(JOB));
	}

	@Test
	void identidadeNoBodyQueryOuHeaderNaoEscolheDono() throws Exception {
		autenticar(List.of("profissional-rh"));
		prepararRespostas();
		String outro = UUID.randomUUID().toString();
		this.mvc
			.perform(pedido("criar")
				.content(CriarJobControllerTests.FORMULARIO.replace("\"origem\"",
						"\"usuario_id\":\"" + outro + "\",\"origem\""))
				.param("usuario_id", outro)
				.header("X-Usuario-Id", outro))
			.andExpect(status().isCreated());
		verify(this.criar).criar(any(), eq(USUARIO));
	}

	@ParameterizedTest
	@MethodSource("rotas")
	void negacaoPrecedeInterpretacaoDoCorpo(String rota) throws Exception {
		autenticar(List.of("auditor"));
		this.mvc.perform(pedido(rota).content("{")).andExpect(status().isForbidden());
		verifyNoInteractions(this.criar, this.listar, this.buscar, this.acompanhar, this.confirmar, this.executar,
				this.reprocessar);
	}

	private void prepararRespostas() {
		RegraCriadaDto regra = new RegraCriadaDto(UUID.randomUUID(), 1, "confirmacao_usuario",
				CriarJobRequisicao.deJson(CriarJobControllerTests.FORMULARIO).representacao(), Instant.now());
		JobCriadoDto criado = new JobCriadoDto(JOB, "gerando_regra", "formulario", List.of("2025-11"), BigDecimal.TEN,
				Instant.now(), UUID.randomUUID(), null, regra);
		JobDetalhadoDto detalhe = new JobDetalhadoDto(JOB, "gerando_regra", "formulario", List.of("2025-11"),
				BigDecimal.TEN, Instant.now(), null, null, UUID.randomUUID(), null, List.of(regra), null, List.of());
		when(this.criar.criar(any(), any())).thenReturn(criado);
		when(this.listar.listar(any(), any())).thenReturn(new PaginaJobsDto(List.of(), 0, 20, 0));
		when(this.buscar.buscar(JOB)).thenReturn(detalhe);
		when(this.acompanhar.acompanhar(JOB)).thenReturn(new SseEmitter());
		when(this.confirmar.confirmar(eq(JOB), any())).thenReturn(criado);
		when(this.reprocessar.reprocessar(eq(JOB), any())).thenReturn(criado);
		when(this.executar.aplicar(eq(JOB), any())).thenReturn(new ExecutarAcaoService.AcaoAplicada(
				EventoEstadoDto.transicao(JOB, JobStatus.AGUARDANDO_DECISAO_USUARIO, JobStatus.LIBERADO, null),
				detalhe));
	}

	private void verificarServico(String rota) {
		switch (rota) {
			case "criar" -> verify(this.criar).criar(any(), eq(USUARIO));
			case "listar" -> verify(this.listar).listar(any(), argThat(acesso -> acesso.usuarioId().equals(USUARIO)));
			case "buscar" -> verify(this.buscar).buscar(JOB);
			case "events" -> verify(this.acompanhar).acompanhar(JOB);
			case "parameters" -> verify(this.confirmar).confirmar(eq(JOB), any());
			case "reprocessar" -> verify(this.reprocessar).reprocessar(eq(JOB), any());
			default -> verify(this.executar).aplicar(JOB, AcaoJob.deColuna(rota));
		}
	}

	static MockHttpServletRequestBuilder pedido(String rota) {
		return switch (rota) {
			case "criar" ->
				post("/jobs").contentType(MediaType.APPLICATION_JSON).content(CriarJobControllerTests.FORMULARIO);
			case "listar" -> get("/jobs");
			case "buscar" -> get("/jobs/{id}", JOB);
			case "events" -> get("/jobs/{id}/events", JOB).accept(MediaType.TEXT_EVENT_STREAM);
			case "parameters" -> post("/jobs/{id}/parameters", JOB).contentType(MediaType.APPLICATION_JSON)
				.content(ConfirmarParametrosControllerTests.CONFIRMAR);
			case "reprocessar" -> post("/jobs/{id}/reprocessar", JOB);
			default -> post("/jobs/{id}/actions", JOB).contentType(MediaType.APPLICATION_JSON)
				.content("{\"acao\":\"" + rota + "\"}");
		};
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

	@RestController
	static class RotaSemPolitica {

		@GetMapping("/jobs/sem-politica")
		String semPolitica() {
			throw new AssertionError("Rota sem política foi executada.");
		}

	}

}
