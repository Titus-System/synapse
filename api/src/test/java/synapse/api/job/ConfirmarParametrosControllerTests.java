package synapse.api.job;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class ConfirmarParametrosControllerTests {

	private static final UUID JOB = UUID.fromString("3f2b1c40-0d18-4a51-9f2e-6c1d9a77b021");

	static final String CONFIRMAR = """
			{"regra":{"nucleo":{"vigencia":{"inicio":"2025-11","fim":"2025-11"},
			 "loja":["13"],"marca":["10","20"],"cargo":["100","300"],"percentual":0.03},"especificacoes":[]}}
			""";

	private final ConfirmarParametrosService service = mock(ConfirmarParametrosService.class);

	private MockMvc mvc;

	@BeforeEach
	void preparar() {
		this.mvc = MockMvcBuilders.standaloneSetup(new ConfirmarParametrosController(this.service))
			.setControllerAdvice(new ConfirmarParametrosAdvice())
			.build();
	}

	@Test
	void confirmaResponde202ComRegraNaVersaoNova() throws Exception {
		when(this.service.confirmar(any(), any())).thenReturn(new JobCriadoDto(JOB, "gerando_regra", "formulario",
				List.of("2025-11"), new BigDecimal("485000.0"), Instant.parse("2026-09-20T10:00:00Z"),
				UUID.randomUUID(),
				new RegraCriadaDto(UUID.randomUUID(), 2, "confirmacao_usuario",
						new RepresentacaoRegraDto(new NucleoRegraDto(new VigenciaDto("2025-11", "2025-11"),
								List.of("13"), List.of("10", "20"), List.of("100", "300"), new BigDecimal("0.03")),
								List.of()),
						Instant.parse("2026-09-20T10:00:00Z"))));

		this.mvc
			.perform(post("/jobs/" + JOB + "/parameters").contentType(MediaType.APPLICATION_JSON).content(CONFIRMAR))
			.andExpect(status().isAccepted())
			.andExpect(jsonPath("$.status").value("gerando_regra"))
			.andExpect(jsonPath("$.regra.versao").value(2))
			.andExpect(jsonPath("$.regra.representacao.nucleo.percentual").value(0.03));
	}

	@Test
	void corpoInvalidoResponde400() throws Exception {
		this.mvc.perform(post("/jobs/" + JOB + "/parameters").contentType(MediaType.APPLICATION_JSON).content("{"))
			.andExpect(status().isBadRequest())
			.andExpect(jsonPath("$.codigo").value("requisicao_invalida"));
		verifyNoInteractions(this.service);
	}

	@Test
	void nucleoIncompletoResponde422ComCampoLocalizado() throws Exception {
		this.mvc
			.perform(post("/jobs/" + JOB + "/parameters").contentType(MediaType.APPLICATION_JSON)
				.content(CONFIRMAR.replace(",\"percentual\":0.03", "")))
			.andExpect(status().isUnprocessableContent())
			.andExpect(jsonPath("$.codigo").value("nucleo_incompleto"))
			.andExpect(jsonPath("$.elementos[0].ref").value("nucleo.percentual"));
		verifyNoInteractions(this.service);
	}

	@Test
	void jobNaoEncontradoResponde404() throws Exception {
		when(this.service.confirmar(any(), any())).thenThrow(new JobNaoEncontradoException(JOB));
		this.mvc
			.perform(post("/jobs/" + JOB + "/parameters").contentType(MediaType.APPLICATION_JSON).content(CONFIRMAR))
			.andExpect(status().isNotFound())
			.andExpect(jsonPath("$.codigo").value("job_nao_encontrado"));
	}

	@Test
	void estadoInvalidoResponde409() throws Exception {
		when(this.service.confirmar(any(), any()))
			.thenThrow(new TransicaoDeStatusInvalidaException(JobStatus.GERANDO_REGRA, JobStatus.GERANDO_REGRA));
		this.mvc
			.perform(post("/jobs/" + JOB + "/parameters").contentType(MediaType.APPLICATION_JSON).content(CONFIRMAR))
			.andExpect(status().isConflict())
			.andExpect(jsonPath("$.codigo").value("estado_invalido"));
	}

	@Test
	void naoExpoeErroDoJdbc() throws Exception {
		when(this.service.confirmar(any(), any())).thenThrow(new DataIntegrityViolationException("stack trace SQL"));
		this.mvc
			.perform(post("/jobs/" + JOB + "/parameters").contentType(MediaType.APPLICATION_JSON).content(CONFIRMAR))
			.andExpect(status().isInternalServerError())
			.andExpect(content().string(""));
	}

}
