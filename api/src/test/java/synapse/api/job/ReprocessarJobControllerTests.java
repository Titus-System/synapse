package synapse.api.job;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import tools.jackson.databind.json.JsonMapper;

import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class ReprocessarJobControllerTests {

	private static final UUID ORIGEM = UUID.randomUUID();

	private static final UUID NOVO = UUID.randomUUID();

	private final ReprocessarJobService service = mock(ReprocessarJobService.class);

	private MockMvc mvc;

	@BeforeEach
	void preparar() {
		this.mvc = MockMvcBuilders.standaloneSetup(new ReprocessarJobController(this.service))
			.setControllerAdvice(new ReprocessarJobAdvice())
			.build();
	}

	@ParameterizedTest
	@ValueSource(strings = { "", "{}", "{\"orcamento\":null,\"competencias\":null}" })
	void corpoOpcionalCriaJobComProcedenciaERegra(String corpo) throws Exception {
		when(this.service.reprocessar(eq(ORIGEM), any())).thenReturn(novoJob());
		var pedido = post("/jobs/{id}/reprocessar", ORIGEM);
		if (!corpo.isEmpty()) {
			pedido.contentType(MediaType.APPLICATION_JSON).content(corpo);
		}
		String resposta = this.mvc.perform(pedido)
			.andExpect(status().isCreated())
			.andExpect(header().string("Location", "/api/jobs/" + NOVO))
			.andExpect(jsonPath("$.id").value(NOVO.toString()))
			.andExpect(jsonPath("$.status").value("aguardando_confirmacao_parametros"))
			.andExpect(jsonPath("$.origem").value("reprocessamento"))
			.andExpect(jsonPath("$.job_origem_id").value(ORIGEM.toString()))
			.andExpect(jsonPath("$.regra.versao").value(1))
			.andReturn()
			.getResponse()
			.getContentAsString();
		assertThat(new JsonMapper().readTree(resposta).propertyNames()).containsExactlyInAnyOrder("id", "status",
				"origem", "competencias", "orcamento", "criado_em", "job_origem_id", "regra");
		verify(this.service).reprocessar(eq(ORIGEM), argThat(r -> r.orcamento() == null && r.competencias() == null));
	}

	@Test
	void overridesPreservamPrecisaoEOrdenamCompetencias() throws Exception {
		when(this.service.reprocessar(eq(ORIGEM), any())).thenReturn(novoJob());
		this.mvc.perform(post("/jobs/{id}/reprocessar", ORIGEM).contentType(MediaType.APPLICATION_JSON).content("""
				{"orcamento":-0.1234567890123456789,"competencias":["2025-12","2025-07","2025-09"]}
				""")).andExpect(status().isCreated());
		verify(this.service).reprocessar(eq(ORIGEM),
				argThat(r -> r.orcamento() != null
						&& new BigDecimal("-0.1234567890123456789").compareTo(r.orcamento()) == 0
						&& List.of("2025-07", "2025-09", "2025-12").equals(r.competencias())));
	}

	@ParameterizedTest
	@ValueSource(strings = { "{", "null", "[]", "42", "{} {}", "{\"orcamento\":\"10\"}", "{\"competencias\":[]}",
			"{\"competencias\":\"2025-11\"}", "{\"competencias\":[null]}", "{\"competencias\":[202511]}",
			"{\"competencias\":[\"2025-06\"]}", "{\"competencias\":[\"2026-01\"]}", "{\"competencias\":[\"2025-7\"]}",
			"{\"competencias\":[\"2025-11\",\"2025-11\"]}" })
	void entradaInvalidaNaoChamaServico(String corpo) throws Exception {
		this.mvc.perform(post("/jobs/{id}/reprocessar", ORIGEM).contentType(MediaType.APPLICATION_JSON).content(corpo))
			.andExpect(status().isBadRequest())
			.andExpect(jsonPath("$.codigo").value("requisicao_invalida"));
		verifyNoInteractions(this.service);
	}

	@Test
	void inexistenteRetorna404() throws Exception {
		when(this.service.reprocessar(eq(ORIGEM), any())).thenThrow(new JobNaoEncontradoException(ORIGEM));
		this.mvc.perform(post("/jobs/{id}/reprocessar", ORIGEM))
			.andExpect(status().isNotFound())
			.andExpect(jsonPath("$.codigo").value("job_nao_encontrado"));
	}

	@Test
	void estadoInvalidoRetorna409Especifico() throws Exception {
		when(this.service.reprocessar(eq(ORIGEM), any())).thenThrow(ReprocessarJobException.estadoInvalido());
		this.mvc.perform(post("/jobs/{id}/reprocessar", ORIGEM))
			.andExpect(status().isConflict())
			.andExpect(jsonPath("$.codigo").value("estado_invalido"))
			.andExpect(jsonPath("$.mensagem").value("Somente um job arquivado pode ser reprocessado."));
	}

	@Test
	void naoExpoeErroDoJdbc() throws Exception {
		when(this.service.reprocessar(eq(ORIGEM), any())).thenThrow(new DataIntegrityViolationException("detalhe SQL"));
		this.mvc.perform(post("/jobs/{id}/reprocessar", ORIGEM))
			.andExpect(status().isInternalServerError())
			.andExpect(content().string(""));
	}

	private static JobCriadoDto novoJob() {
		var representacao = CriarJobRequisicao.deJson(CriarJobControllerTests.FORMULARIO).representacao();
		Instant agora = Instant.parse("2026-09-23T10:00:00Z");
		return new JobCriadoDto(NOVO, "aguardando_confirmacao_parametros", "reprocessamento", List.of("2025-11"),
				new BigDecimal("485000"), agora, null, ORIGEM,
				new RegraCriadaDto(UUID.randomUUID(), 1, "reprocessamento", representacao, agora));
	}

}
