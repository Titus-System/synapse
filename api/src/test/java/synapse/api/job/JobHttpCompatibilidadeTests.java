package synapse.api.job;

import java.util.UUID;
import java.util.stream.Stream;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.EnumSource;
import org.junit.jupiter.params.provider.MethodSource;
import org.junit.jupiter.params.provider.ValueSource;
import org.slf4j.MDC;

import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import synapse.api.core.logging.CorrelationContext;
import synapse.api.core.security.AcessoDoUsuario;
import synapse.api.core.security.PapelDoUsuario;
import synapse.api.core.sse.EmissoresSse;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class JobHttpCompatibilidadeTests {

	private static final UUID JOB = UUID.randomUUID();

	private final JobService service = mock(JobService.class);

	private final EmissoresSse emissores = mock(EmissoresSse.class);

	private MockMvc mvc;

	@BeforeEach
	void preparar() {
		this.mvc = MockMvcBuilders
			.standaloneSetup(new JobController(this.service, this.emissores, new CorrelationContext()))
			.setControllerAdvice(new JobAdvice(), new AutorizacaoDeJobAdvice())
			.build();
	}

	@ParameterizedTest
	@EnumSource(OperacaoJob.class)
	void falhaDePersistenciaMantemTratamentoPorOperacao(OperacaoJob operacao) throws Exception {
		var falha = new DataIntegrityViolationException("detalhe interno de persistência");
		falhar(operacao, falha);
		if (operacao == OperacaoJob.CONSULTAR) {
			assertThatThrownBy(() -> this.mvc.perform(pedido(operacao))).hasCause(falha);
		}
		else {
			this.mvc.perform(pedido(operacao))
				.andExpect(status().isInternalServerError())
				.andExpect(content().string(""))
				.andExpect(header().doesNotExist("Content-Type"));
		}
	}

	@ParameterizedTest
	@EnumSource(OperacaoJob.class)
	void jobInexistenteMantemTratamentoPorOperacao(OperacaoJob operacao) throws Exception {
		var falha = new JobNaoEncontradoException(JOB);
		falhar(operacao, falha);
		if (operacao == OperacaoJob.CRIAR || operacao == OperacaoJob.LISTAR) {
			assertThatThrownBy(() -> this.mvc.perform(pedido(operacao))).hasCause(falha);
		}
		else {
			this.mvc.perform(pedido(operacao))
				.andExpect(status().isNotFound())
				.andExpect(content().contentType(MediaType.APPLICATION_JSON))
				.andExpect(content().json("""
						{"codigo":"job_nao_encontrado","mensagem":"Job não encontrado."}
						"""));
		}
	}

	@ParameterizedTest
	@EnumSource(OperacaoJob.class)
	void transicaoInvalidaSoEConvertidaNaConfirmacao(OperacaoJob operacao) throws Exception {
		var falha = new TransicaoDeStatusInvalidaException(JobStatus.LIBERADO, JobStatus.GERANDO_REGRA);
		falhar(operacao, falha);
		if (operacao == OperacaoJob.CONFIRMAR_PARAMETROS) {
			this.mvc.perform(pedido(operacao))
				.andExpect(status().isConflict())
				.andExpect(jsonPath("$.codigo").value("estado_invalido"))
				.andExpect(jsonPath("$.mensagem").value("Este job não está aguardando confirmação de parâmetros."))
				.andExpect(jsonPath("$.elementos").doesNotExist());
		}
		else {
			assertThatThrownBy(() -> this.mvc.perform(pedido(operacao))).hasCause(falha);
		}
		verifyNoInteractions(this.emissores);
	}

	@ParameterizedTest
	@MethodSource("errosDeOutraOperacao")
	void consultaNaoAbsorveExcecoesDasOutrasOperacoes(RuntimeException falha) {
		falhar(OperacaoJob.CONSULTAR, falha);
		assertThatThrownBy(() -> this.mvc.perform(pedido(OperacaoJob.CONSULTAR))).hasCause(falha);
	}

	static Stream<Arguments> errosDeOutraOperacao() {
		return Stream.of(Arguments.of(CriarJobException.requisicao("criar")),
				Arguments.of(ConfirmarParametrosException.estadoInvalido()),
				Arguments.of(ExecutarAcaoException.requisicao("executar")),
				Arguments.of(ReprocessarJobException.estadoInvalido()), Arguments.of(ListarJobsException.pagina()));
	}

	@ParameterizedTest
	@EnumSource(value = OperacaoJob.class, names = { "CRIAR", "CONFIRMAR_PARAMETROS", "EXECUTAR_ACAO" })
	void corpoObrigatorioAusentePreservaErroJson(OperacaoJob operacao) throws Exception {
		this.mvc.perform(pedido(operacao).content(""))
			.andExpect(status().isBadRequest())
			.andExpect(content().contentType(MediaType.APPLICATION_JSON))
			.andExpect(jsonPath("$.codigo").value("requisicao_invalida"))
			.andExpect(jsonPath("$.mensagem").value("O corpo deve conter um objeto JSON válido."))
			.andExpect(jsonPath("$.elementos").doesNotExist());
		semInteracoes();
	}

	@ParameterizedTest
	@ValueSource(strings = { "", "/events", "/parameters", "/actions", "/reprocessar" })
	void identificadorInvalidoNaoViraErroDePaginacao(String sufixo) throws Exception {
		var requisicao = sufixo.isEmpty() || sufixo.equals("/events") ? get("/jobs/invalido" + sufixo)
				: post("/jobs/invalido" + sufixo).contentType(MediaType.APPLICATION_JSON).content("{}");
		this.mvc.perform(requisicao).andExpect(status().isBadRequest()).andExpect(content().string(""));
		semInteracoes();
	}

	@ParameterizedTest
	@EnumSource(OperacaoJob.class)
	void acceptIncompativelMantem406(OperacaoJob operacao) throws Exception {
		this.mvc.perform(pedido(operacao).accept(MediaType.APPLICATION_XML)).andExpect(status().isNotAcceptable());
		semInteracoes();
	}

	@ParameterizedTest
	@EnumSource(value = OperacaoJob.class, names = { "CRIAR", "CONFIRMAR_PARAMETROS", "EXECUTAR_ACAO" })
	void tipoDeCorpoIncompativelMantem415(OperacaoJob operacao) throws Exception {
		this.mvc.perform(pedido(operacao).contentType(MediaType.TEXT_PLAIN))
			.andExpect(status().isUnsupportedMediaType());
		semInteracoes();
	}

	@ParameterizedTest
	@ValueSource(strings = { "application/json", "text/plain" })
	void reprocessamentoPreservaAusenciaDeRestricaoDeContentType(String tipo) throws Exception {
		when(this.service.reprocessar(any(), any())).thenThrow(ReprocessarJobException.estadoInvalido());
		this.mvc.perform(pedido(OperacaoJob.REPROCESSAR).contentType(tipo).content("{}"))
			.andExpect(status().isConflict())
			.andExpect(jsonPath("$.codigo").value("estado_invalido"));
		verify(this.service).reprocessar(any(), any());
	}

	@ParameterizedTest
	@ValueSource(booleans = { false, true })
	void acompanhamentoRestauraCorrelacaoEmSucessoEFalha(boolean falha) throws Exception {
		String anterior = MDC.get("job_id");
		MDC.put("job_id", "contexto-anterior");
		try {
			when(this.service.acompanhar(JOB)).thenAnswer(invocacao -> {
				assertThat(MDC.get("job_id")).isEqualTo(JOB.toString());
				if (falha) {
					throw new JobNaoEncontradoException(JOB);
				}
				return new SseEmitter();
			});
			this.mvc.perform(pedido(OperacaoJob.ACOMPANHAR)).andExpect(status().is(falha ? 404 : 200));
			assertThat(MDC.get("job_id")).isEqualTo("contexto-anterior");
		}
		finally {
			if (anterior == null) {
				MDC.remove("job_id");
			}
			else {
				MDC.put("job_id", anterior);
			}
		}
	}

	private void falhar(OperacaoJob operacao, RuntimeException falha) {
		switch (operacao) {
			case CRIAR -> when(this.service.criar(any(), any())).thenThrow(falha);
			case LISTAR -> when(this.service.listar(any(), any())).thenThrow(falha);
			case CONSULTAR -> when(this.service.buscar(any())).thenThrow(falha);
			case ACOMPANHAR -> when(this.service.acompanhar(any())).thenThrow(falha);
			case CONFIRMAR_PARAMETROS -> when(this.service.confirmar(any(), any())).thenThrow(falha);
			case EXECUTAR_ACAO -> when(this.service.executarAcao(any(), any())).thenThrow(falha);
			case REPROCESSAR -> when(this.service.reprocessar(any(), any())).thenThrow(falha);
		}
	}

	private void semInteracoes() {
		verifyNoInteractions(this.service, this.emissores);
	}

	private static MockHttpServletRequestBuilder pedido(OperacaoJob operacao) {
		var requisicao = switch (operacao) {
			case CRIAR ->
				post("/jobs").contentType(MediaType.APPLICATION_JSON).content(CriarJobControllerTests.FORMULARIO);
			case LISTAR -> get("/jobs");
			case CONSULTAR -> get("/jobs/{id}", JOB);
			case ACOMPANHAR -> get("/jobs/{id}/events", JOB).accept(MediaType.TEXT_EVENT_STREAM);
			case CONFIRMAR_PARAMETROS -> post("/jobs/{id}/parameters", JOB).contentType(MediaType.APPLICATION_JSON)
				.content(ConfirmarParametrosControllerTests.CONFIRMAR);
			case EXECUTAR_ACAO -> post("/jobs/{id}/actions", JOB).contentType(MediaType.APPLICATION_JSON)
				.content("{\"acao\":\"cancelar\"}");
			case REPROCESSAR -> post("/jobs/{id}/reprocessar", JOB);
		};
		return requisicao.requestAttr(AutorizacaoJobsInterceptor.ACESSO,
				new AcessoDoUsuario(UUID.randomUUID(), PapelDoUsuario.PROFISSIONAL_RH));
	}

}
