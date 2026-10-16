package synapse.api.job;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

import java.nio.charset.StandardCharsets;

import tools.jackson.databind.json.JsonMapper;

import synapse.api.core.security.AcessoDoUsuario;
import synapse.api.core.security.PapelDoUsuario;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.mockito.ArgumentCaptor;

import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import synapse.api.core.logging.CorrelationContext;
import synapse.api.core.sse.EmissoresSse;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class RenomearJobControllerTests {

	private static final UUID JOB = UUID.fromString("3f2b1c40-0d18-4a51-9f2e-6c1d9a77b021");

	private static final JsonMapper JSON = JsonMapper.builder().build();

	private final JobService service = mock(JobService.class);

	private MockMvc mvc;

	@BeforeEach
	void preparar() {
		this.mvc = MockMvcBuilders
			.standaloneSetup(new JobController(this.service, mock(EmissoresSse.class), new CorrelationContext(),
					mock(synapse.api.core.metrics.AppMetrics.class)))
			.setControllerAdvice(new JobAdvice())
			.build();
	}

	@Test
	void nomeValidoResponde200ComJobDetalhado() throws Exception {
		when(this.service.renomear(any(), any())).thenReturn(jobDetalhado());

		this.mvc.perform(renomear("{\"nome\":\"Bônus de vendas\"}"))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.id").value(JOB.toString()))
			.andExpect(jsonPath("$.status").value("arquivado"));
	}

	@Test
	void gravaONomeSemOsEspacosDasPontas() throws Exception {
		when(this.service.renomear(any(), any())).thenReturn(jobDetalhado());

		this.mvc.perform(renomear("{\"nome\":\"  Meu   nome \\n\"}")).andExpect(status().isOk());

		var captor = ArgumentCaptor.forClass(RenomearJobRequisicao.class);
		verify(this.service).renomear(eq(JOB), captor.capture());
		assertThat(captor.getValue().nome()).isEqualTo("Meu   nome");
	}

	@Test
	void aceitaCemPontosDeCodigoMesmoComEmoji() throws Exception {
		when(this.service.renomear(any(), any())).thenReturn(jobDetalhado());
		String nome = "😀".repeat(100);

		this.mvc.perform(renomear("{\"nome\":\"" + nome + "\"}")).andExpect(status().isOk());

		var captor = ArgumentCaptor.forClass(RenomearJobRequisicao.class);
		verify(this.service).renomear(eq(JOB), captor.capture());
		assertThat(captor.getValue().nome()).isEqualTo(nome);
	}

	@Test
	void recusaMaisDeCemPontosDeCodigo() throws Exception {
		this.mvc.perform(renomear("{\"nome\":\"" + "a".repeat(101) + "\"}"))
			.andExpect(status().isBadRequest())
			.andExpect(jsonPath("$.codigo").value("requisicao_invalida"));
		verifyNoInteractions(this.service);
	}

	@ParameterizedTest
	@ValueSource(strings = { "{}", "{\"nome\":null}", "{\"nome\":123}", "{\"nome\":{}}", "{\"nome\":\"\"}",
			"{\"nome\":\"   \"}", "[]", "{" })
	void recusaNomeAusenteVazioOuInvalidoSemChamarService(String corpo) throws Exception {
		this.mvc.perform(renomear(corpo))
			.andExpect(status().isBadRequest())
			.andExpect(jsonPath("$.codigo").value("requisicao_invalida"));
		verifyNoInteractions(this.service);
	}

	@Test
	void recusaCorpoVazio() throws Exception {
		this.mvc.perform(renomear(""))
			.andExpect(status().isBadRequest())
			.andExpect(jsonPath("$.codigo").value("requisicao_invalida"));
		verifyNoInteractions(this.service);
	}

	@Test
	void mensagemDeErroNaoRepeteONome() throws Exception {
		String nome = "segredo".repeat(30);

		this.mvc.perform(renomear("{\"nome\":\"" + nome + "\"}"))
			.andExpect(status().isBadRequest())
			.andExpect(content().string(org.hamcrest.Matchers.not(org.hamcrest.Matchers.containsString("segredo"))));
	}

	@Test
	void jobNaoEncontradoResponde404() throws Exception {
		when(this.service.renomear(any(), any())).thenThrow(new JobNaoEncontradoException(JOB));

		this.mvc.perform(renomear("{\"nome\":\"Meu nome\"}"))
			.andExpect(status().isNotFound())
			.andExpect(jsonPath("$.codigo").value("job_nao_encontrado"));
	}

	@Test
	void listagemValidaContraOContratoComEmSemNome() throws Exception {
		var comNome = new JobResumoDto(UUID.randomUUID(), "arquivado", List.of("2025-11"), null, null, null,
				Instant.parse("2026-09-20T10:00:00Z"), null, null, "Bônus de vendas");
		var semNome = new JobResumoDto(UUID.randomUUID(), "arquivado", List.of("2025-11"), null, null, null,
				Instant.parse("2026-09-20T10:00:00Z"), null, null, null);
		when(this.service.listar(any(), any())).thenReturn(new PaginaJobsDto(List.of(comNome, semNome), 0, 20, 2));

		String corpo = this.mvc
			.perform(get("/jobs").requestAttr(AutorizacaoJobsInterceptor.ACESSO,
					new AcessoDoUsuario(UUID.randomUUID(), PapelDoUsuario.PROFISSIONAL_RH)))
			.andExpect(status().isOk())
			.andReturn()
			.getResponse()
			.getContentAsString(StandardCharsets.UTF_8);

		ContratoDeEvento.validarRespostaHttp("PaginaJobs", corpo);
		assertThat(JSON.readTree(corpo).path("itens").path(0).path("nome").asString()).isEqualTo("Bônus de vendas");
		assertThat(JSON.readTree(corpo).path("itens").path(1).has("nome")).isFalse();
	}

	private static org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder renomear(String corpo) {
		return put("/jobs/" + JOB + "/nome").contentType(MediaType.APPLICATION_JSON).content(corpo);
	}

	private static JobDetalhadoDto jobDetalhado() {
		return new JobDetalhadoDto(JOB, "arquivado", "formulario", List.of("2025-11"), new BigDecimal("485000.0"), null,
				Instant.parse("2026-09-20T10:00:00Z"), null, null, UUID.randomUUID(), null, null, List.of(), null,
				List.of());
	}

}