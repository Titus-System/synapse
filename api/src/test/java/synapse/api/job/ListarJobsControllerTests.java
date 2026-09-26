package synapse.api.job;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import tools.jackson.databind.json.JsonMapper;

import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import synapse.api.core.security.AcessoDoUsuario;
import synapse.api.core.security.PapelDoUsuario;
import synapse.api.core.security.UsuarioAtual;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class ListarJobsControllerTests {

	private final ListarJobsService service = mock(ListarJobsService.class);

	private final UsuarioAtual usuarioAtual = mock(UsuarioAtual.class);

	private MockMvc mvc;

	@BeforeEach
	void preparar() {
		when(this.usuarioAtual.obter())
			.thenReturn(new AcessoDoUsuario(UUID.randomUUID(), PapelDoUsuario.PROFISSIONAL_RH));
		this.mvc = MockMvcBuilders.standaloneSetup(new ListarJobsController(this.service))
			.addInterceptors(new AutorizacaoJobsInterceptor(this.usuarioAtual,
					new AutorizadorDeJob(mock(org.springframework.jdbc.core.JdbcTemplate.class))))
			.setControllerAdvice(new ListarJobsAdvice())
			.build();
	}

	@Test
	void semParametrosUsaOsPadroesDoContrato() throws Exception {
		when(this.service.listar(any(), any())).thenReturn(new PaginaJobsDto(List.of(), 0, 20, 0));

		this.mvc.perform(get("/jobs")).andExpect(status().isOk());

		verify(this.service).listar(any(), any());
	}

	@Test
	void repassaPaginaETamanhoInformados() throws Exception {
		when(this.service.listar(any(), any())).thenReturn(new PaginaJobsDto(List.of(), 2, 10, 0));

		this.mvc.perform(get("/jobs").param("pagina", "2").param("tamanho", "10")).andExpect(status().isOk());

		verify(this.service).listar(any(), any());
	}

	@Test
	void aPaginaTemExatamenteOsQuatroCamposDoContrato() throws Exception {
		when(this.service.listar(any(), any())).thenReturn(new PaginaJobsDto(List.of(), 0, 20, 3));

		String resposta = this.mvc.perform(get("/jobs"))
			.andExpect(status().isOk())
			.andReturn()
			.getResponse()
			.getContentAsString();
		var pagina = new JsonMapper().readTree(resposta);
		assertThat(pagina.propertyNames()).containsExactlyInAnyOrder("itens", "pagina", "tamanho", "total");
		assertThat(pagina.path("total").asLong()).isEqualTo(3);
	}

	@Test
	void umItemCompletoTemOsOitoCamposDoContrato() throws Exception {
		UUID id = UUID.randomUUID();
		UUID jobOrigemId = UUID.randomUUID();
		JobResumoDto item = new JobResumoDto(id, "liberado", List.of("2025-11"), new BigDecimal("485000.0"), "viavel",
				Instant.parse("2026-09-16T15:00:00Z"), Instant.parse("2026-09-16T15:05:00Z"), jobOrigemId);
		when(this.service.listar(any(), any())).thenReturn(new PaginaJobsDto(List.of(item), 0, 20, 1));

		String resposta = this.mvc.perform(get("/jobs"))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.itens[0].veredito").value("viavel"))
			.andReturn()
			.getResponse()
			.getContentAsString();
		var no = new JsonMapper().readTree(resposta).path("itens").path(0);
		assertThat(no.propertyNames()).containsExactlyInAnyOrder("id", "status", "competencias", "orcamento",
				"veredito", "criado_em", "finalizado_em", "job_origem_id");
		assertThat(UUID.fromString(no.path("id").asString())).isEqualTo(id);
		assertThat(UUID.fromString(no.path("job_origem_id").asString())).isEqualTo(jobOrigemId);
		assertThat(Instant.parse(no.path("criado_em").asString())).isEqualTo(item.criado_em());
		assertThat(no.path("orcamento").decimalValue()).isEqualByComparingTo("485000.0");
		assertThat(no.path("competencias").path(0).asString()).isEqualTo("2025-11");
	}

	@Test
	void umItemMinimoOmiteOsCamposAusentesSemNull() throws Exception {
		JobResumoDto item = new JobResumoDto(UUID.randomUUID(), "aguardando_confirmacao_parametros", List.of("2025-11"),
				new BigDecimal("485000.0"), null, Instant.parse("2026-09-16T15:00:00Z"), null, null);
		when(this.service.listar(any(), any())).thenReturn(new PaginaJobsDto(List.of(item), 0, 20, 1));

		String resposta = this.mvc.perform(get("/jobs"))
			.andExpect(status().isOk())
			.andReturn()
			.getResponse()
			.getContentAsString();
		var no = new JsonMapper().readTree(resposta).path("itens").path(0);
		assertThat(no.propertyNames()).containsExactlyInAnyOrder("id", "status", "competencias", "orcamento",
				"criado_em");
	}

	@ParameterizedTest
	@CsvSource({ "pagina, -1", "tamanho, 0", "tamanho, 101" })
	void parametroForaDoIntervaloResponde400SemChamarOService(String nome, String valor) throws Exception {
		this.mvc.perform(get("/jobs").param(nome, valor))
			.andExpect(status().isBadRequest())
			.andExpect(jsonPath("$.codigo").value("requisicao_invalida"))
			.andExpect(jsonPath("$.mensagem").value(mensagemEsperada(nome)));

		verifyNoInteractions(this.service);
	}

	@ParameterizedTest
	@CsvSource({ "pagina, abc", "tamanho, 1.5" })
	void parametroNaoInteiroResponde400ComOCorpoDeErroPadrao(String nome, String valor) throws Exception {
		String resposta = this.mvc.perform(get("/jobs").param(nome, valor))
			.andExpect(status().isBadRequest())
			.andExpect(jsonPath("$.codigo").value("requisicao_invalida"))
			.andExpect(jsonPath("$.mensagem").value(mensagemEsperada(nome)))
			.andReturn()
			.getResponse()
			.getContentAsString();
		assertThat(new JsonMapper().readTree(resposta).propertyNames()).containsExactlyInAnyOrder("codigo", "mensagem");

		verifyNoInteractions(this.service);
	}

	@Test
	void falhaDePersistenciaResponde500SemCorpo() throws Exception {
		when(this.service.listar(any(), any())).thenThrow(new DataIntegrityViolationException("falha"));

		this.mvc.perform(get("/jobs")).andExpect(status().isInternalServerError());
	}

	private static String mensagemEsperada(String nome) {
		return "pagina".equals(nome) ? "O parâmetro pagina precisa ser um inteiro maior ou igual a zero."
				: "O parâmetro tamanho precisa ser um inteiro entre 1 e 100.";
	}

}
