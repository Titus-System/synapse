package synapse.api.auditoria;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.stream.Stream;

import ch.qos.logback.classic.spi.ILoggingEvent;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.MethodSource;
import org.slf4j.MDC;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.http.MediaType;
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
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * A rota do resumo com o interceptor, o {@link UsuarioAtual} e o advice reais sobre um
 * serviço simulado.
 */
class ResumoAuditoriaControllerTests {

	private static final UUID AUDITOR = UUID.fromString("cccccccc-cccc-4ccc-8ccc-cccccccccccc");

	private static final UUID JOB = UUID.fromString("dddddddd-dddd-4ddd-8ddd-dddddddddddd");

	private static final String ROTA = "/auditoria/jobs/{id}/resumo";

	private static final String VALOR_PRIVADO = "598000.123456789";

	private final ResumoAuditoriaService service = mock(ResumoAuditoriaService.class);

	private final JdbcTemplate jdbc = mock(JdbcTemplate.class);

	private MockMvc mvc;

	@BeforeEach
	void preparar() {
		when(this.jdbc.queryForList(contains("FROM usuarios"), eq(UUID.class), eq("subject-teste"), eq("login-teste")))
			.thenReturn(List.of(AUDITOR));
		when(this.jdbc.update(contains("UPDATE usuarios"), any(), any(), any(), eq(AUDITOR))).thenReturn(1);
		when(this.service.consultar(JOB)).thenReturn(resumoCompleto());
		CorrelationContext correlacao = new CorrelationContext();
		this.mvc = MockMvcBuilders.standaloneSetup(new ResumoAuditoriaController(this.service, correlacao))
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

	static Stream<List<String>> papeisRecusados() {
		return Stream.of(List.of("profissional-rh"), List.of("auditor", "profissional-rh"), List.of("offline_access"),
				List.of());
	}

	@ParameterizedTest
	@MethodSource("papeisRecusados")
	void recusaPapelAntesDeLerDadosOuInterpretarOId(List<String> papeis) throws Exception {
		autenticar(papeis);
		this.mvc.perform(get(ROTA, "nao-e-uuid"))
			.andExpect(status().isForbidden())
			.andExpect(jsonPath("$.codigo").value("sem_permissao"));
		this.mvc.perform(get(ROTA, JOB)).andExpect(status().isForbidden());
		verifyNoInteractions(this.service);
	}

	@Test
	void auditorRecebeOResumoDoContratoSemArredondamento() throws Exception {
		autenticar(List.of("default-roles-synapse", "auditor"));
		String corpo = this.mvc.perform(get(ROTA, JOB))
			.andExpect(status().isOk())
			.andExpect(content().contentType(MediaType.APPLICATION_JSON))
			.andReturn()
			.getResponse()
			.getContentAsString();
		ContratoDeEvento.validarRespostaHttp("ResumoDossieAuditoria", corpo);
		verify(this.service).consultar(JOB);
		JsonNode resumo = new JsonMapper().readTree(corpo);
		assertThat(resumo.path("versao_vigente").asInt()).isEqualTo(2);
		assertThat(corpo).contains("{\"elemento_ref\":\"nucleo.percentual\",\"anterior\":0.025,\"novo\":0.030}",
				"{\"elemento_ref\":\"elem.1\",\"novo\":{\"ref\": \"elem.1\", \"construto\": \"generico\"}}",
				"\"anterior\":" + VALOR_PRIVADO, "\"variacao\":42000.864197532");
		JsonNode comparacao = resumo.path("comparacoes").path(0);
		assertThat(comparacao.has("meta_venda")).isFalse();
		assertThat(resumo.path("versoes").path(0).has("regra_origem_id")).isFalse();
	}

	@Test
	void resumoSemSimulacaoVigenteOmiteAVersaoVigente() throws Exception {
		autenticar(List.of("auditor"));
		when(this.service.consultar(JOB))
			.thenReturn(new ResumoDossieAuditoriaDto(new ContagemSimulacoesDto(0, 0, 0), null, List.of(), List.of()));
		String corpo = this.mvc.perform(get(ROTA, JOB))
			.andExpect(status().isOk())
			.andReturn()
			.getResponse()
			.getContentAsString();
		ContratoDeEvento.validarRespostaHttp("ResumoDossieAuditoria", corpo);
		assertThat(new JsonMapper().readTree(corpo).has("versao_vigente")).isFalse();
	}

	@Test
	void conclusaoLogaInfoComJobEUsuarioSemValores() throws Exception {
		autenticar(List.of("auditor"));
		List<ILoggingEvent> eventos;
		try (CapturaDeLog captura = new CapturaDeLog(ResumoAuditoriaController.class)) {
			this.mvc.perform(get(ROTA, JOB)).andExpect(status().isOk());
			eventos = captura.eventos();
		}
		assertThat(eventos).hasSize(1);
		JsonNode linha = validarLog(eventos.getFirst(), "INFO");
		assertThat(linha.path("job_id").asString()).isEqualTo(JOB.toString());
		assertThat(linha.path("message").asString()).isEqualTo("consulta de resumo de auditoria encerrada");
		JsonNode extra = linha.path("extra");
		assertThat(extra.path("operacao").asString()).isEqualTo("consultar_resumo_auditoria");
		assertThat(extra.path("resultado").asString()).isEqualTo("sucesso");
		assertThat(extra.path("duracao_ms").asLong()).isGreaterThanOrEqualTo(0);
		assertThat(MDC.get(CorrelationContext.JOB_ID_KEY)).isNull();
		assertThat(MDC.get(CorrelationContext.USER_ID_KEY)).isNull();
	}

	@Test
	void jobInexistenteRecebe404ELogaWarn() throws Exception {
		autenticar(List.of("auditor"));
		when(this.service.consultar(JOB)).thenThrow(new JobNaoEncontradoNaAuditoriaException());
		List<ILoggingEvent> eventos;
		try (CapturaDeLog captura = new CapturaDeLog(ResumoAuditoriaController.class)) {
			this.mvc.perform(get(ROTA, JOB))
				.andExpect(status().isNotFound())
				.andExpect(jsonPath("$.codigo").value("job_nao_encontrado"))
				.andExpect(jsonPath("$.mensagem").value("Job não encontrado."));
			eventos = captura.eventos();
		}
		assertThat(eventos).hasSize(1);
		JsonNode linha = validarLog(eventos.getFirst(), "WARN");
		assertThat(linha.path("job_id").asString()).isEqualTo(JOB.toString());
		assertThat(linha.path("extra").path("resultado").asString()).isEqualTo("job_nao_encontrado");
		assertThat(MDC.get(CorrelationContext.JOB_ID_KEY)).isNull();
	}

	@Test
	void idMalformadoRecebe400ELogaWarnDaOperacaoSemOValor() throws Exception {
		autenticar(List.of("auditor"));
		List<ILoggingEvent> eventos;
		try (CapturaDeLog captura = new CapturaDeLog(AuditoriaAdvice.class)) {
			this.mvc.perform(get(ROTA, "nao-e-uuid"))
				.andExpect(status().isBadRequest())
				.andExpect(jsonPath("$.codigo").value("requisicao_invalida"))
				.andExpect(jsonPath("$.mensagem").value("O identificador do job precisa ser um UUID."));
			eventos = captura.eventos();
		}
		verifyNoInteractions(this.service);
		assertThat(eventos).hasSize(1);
		JsonNode linha = validarLog(eventos.getFirst(), "WARN");
		assertThat(linha.has("job_id")).isFalse();
		assertThat(linha.path("message").asString()).isEqualTo("consulta de resumo de auditoria encerrada");
		assertThat(linha.path("extra").path("operacao").asString()).isEqualTo("consultar_resumo_auditoria");
		assertThat(linha.path("extra").path("resultado").asString()).isEqualTo("requisicao_invalida");
		assertThat(linha.path("extra").path("parametro").asString()).isEqualTo("id");
		assertThat(CapturaDeLog.emJson(eventos.getFirst())).doesNotContain("nao-e-uuid");
		assertThat(MDC.get(CorrelationContext.USER_ID_KEY)).isNull();
	}

	@Test
	void erroDePersistenciaNaoExpoeDetalhesERestauraContexto() throws Exception {
		autenticar(List.of("auditor"));
		when(this.service.consultar(JOB))
			.thenThrow(new DataAccessResourceFailureException("SELECT totais FROM resultados_simulacao"));
		MDC.put(CorrelationContext.USER_ID_KEY, "contexto-anterior");
		List<ILoggingEvent> eventos;
		try (CapturaDeLog captura = new CapturaDeLog(ResumoAuditoriaController.class)) {
			String corpo = this.mvc.perform(get(ROTA, JOB))
				.andExpect(status().isInternalServerError())
				.andReturn()
				.getResponse()
				.getContentAsString();
			assertThat(corpo).doesNotContain("SELECT", "resultados_simulacao");
			eventos = captura.eventos();
		}
		assertThat(eventos).hasSize(1);
		JsonNode linha = validarLog(eventos.getFirst(), "ERROR");
		assertThat(linha.path("extra").path("resultado").asString()).isEqualTo("falha");
		assertThat(MDC.get(CorrelationContext.USER_ID_KEY)).isEqualTo("contexto-anterior");
		assertThat(MDC.get(CorrelationContext.JOB_ID_KEY)).isNull();
	}

	@Test
	void recusaPorPapelLogaWarnSemDadosDoToken() throws Exception {
		autenticar(List.of("profissional-rh"));
		List<ILoggingEvent> eventos;
		try (CapturaDeLog captura = new CapturaDeLog(AcessoAuditoriaInterceptor.class)) {
			this.mvc.perform(get(ROTA, JOB)).andExpect(status().isForbidden());
			eventos = captura.eventos();
		}
		assertThat(eventos).hasSize(1);
		JsonNode linha = validarLog(eventos.getFirst(), "WARN");
		assertThat(linha.path("message").asString()).isEqualTo("acesso à auditoria recusado");
		assertThat(linha.has("job_id")).isFalse();
		assertThat(CapturaDeLog.emJson(eventos.getFirst())).doesNotContain("profissional-rh");
		assertThat(MDC.get(CorrelationContext.USER_ID_KEY)).isNull();
	}

	private static ResumoDossieAuditoriaDto resumoCompleto() {
		UUID v1 = UUID.randomUUID();
		VersaoResumoAuditoriaDto raiz = new VersaoResumoAuditoriaDto(v1, 1, null, List.of());
		VersaoResumoAuditoriaDto corrigida = new VersaoResumoAuditoriaDto(UUID.randomUUID(), 2, v1,
				List.of(new AlteracaoVersaoDto("nucleo.percentual", "0.025", "0.030"),
						new AlteracaoVersaoDto("elem.1", null, "{\"ref\": \"elem.1\", \"construto\": \"generico\"}")));
		ComparacaoSimulacaoDto comparacao = new ComparacaoSimulacaoDto(UUID.randomUUID(), UUID.randomUUID(),
				VariacaoDto.entre(new BigDecimal("540000"), new BigDecimal("540000")),
				VariacaoDto.entre(new BigDecimal(VALOR_PRIVADO), new BigDecimal("640000.987654321")),
				VariacaoDto.entre(new BigDecimal("58000.123456789"), new BigDecimal("100000.987654321")),
				VariacaoDto.entre(new BigDecimal("0.1074"), new BigDecimal("0.1852")),
				VariacaoDto.entre(new BigDecimal("600000"), new BigDecimal("650000")),
				VariacaoDto.entreOpcionais(null, new BigDecimal("28000000")));
		return new ResumoDossieAuditoriaDto(new ContagemSimulacoesDto(3, 2, 1), 2, List.of(raiz, corrigida),
				List.of(comparacao));
	}

	private static JsonNode validarLog(ILoggingEvent evento, String nivel) throws Exception {
		String serializado = CapturaDeLog.emJson(evento);
		ContratoDeEvento.validarLog(serializado);
		assertThat(serializado).doesNotContain(VALOR_PRIVADO, "nucleo.percentual", "subject-teste", "login-teste",
				"TOKEN-PRIVADO", "SELECT");
		JsonNode linha = new JsonMapper().readTree(serializado);
		assertThat(linha.path("level").asString()).isEqualTo(nivel);
		assertThat(linha.path("user_id").asString()).isEqualTo(AUDITOR.toString());
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
