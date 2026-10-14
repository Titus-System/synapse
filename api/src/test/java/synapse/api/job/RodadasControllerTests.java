package synapse.api.job;

import java.time.Instant;
import java.util.List;
import java.util.UUID;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;

import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import synapse.api.core.security.AcessoDoUsuario;
import synapse.api.core.security.PapelDoUsuario;
import synapse.api.core.security.UsuarioAtual;
import synapse.api.job.JobsDeSubmissoes.Correcao;
import synapse.api.job.JobsDeSubmissoes.Rodada;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class RodadasControllerTests {

	private static final UUID JOB = UUID.randomUUID();

	private static final UUID USUARIO = UUID.randomUUID();

	private final RodadasRepository rodadas = mock(RodadasRepository.class);

	private final JobRepository jobs = mock(JobRepository.class);

	private final UsuarioAtual usuario = mock(UsuarioAtual.class);

	private MockMvc mvc;

	@BeforeEach
	void preparar() {
		when(usuario.obter()).thenReturn(new AcessoDoUsuario(USUARIO, PapelDoUsuario.PROFISSIONAL_RH));
		when(jobs.buscarProprietario(JOB)).thenReturn(List.of(USUARIO));
		mvc = MockMvcBuilders.standaloneSetup(new RodadasController(rodadas))
			.addInterceptors(new AutorizacaoJobsInterceptor(usuario, new AutorizadorDeJob(jobs)))
			.setControllerAdvice(new JobAdvice(), new AutorizacaoDeJobAdvice())
			.build();
	}

	@Test
	void serializaHistoricoENulosObrigatoriosConformeContrato() throws Exception {
		Instant agora = Instant.parse("2026-10-13T20:00:00Z");
		UUID id = UUID.randomUUID();
		UUID regra = UUID.randomUUID();
		var conflitos = new JsonMapper().readTree("[{\"elementos\":[\"nucleo.percentual\"],\"motivo\":\"ausente\"}]");
		when(rodadas.listar(JOB)).thenReturn(List.of(
				new Rodada(id, null, regra, conflitos, new Correcao("texto", "Percentual 2,5%.", agora), regra,
						"corrigida", agora),
				new Rodada(UUID.randomUUID(), id, regra, conflitos, null, null, "pendente", agora.plusSeconds(1))));
		String corpo = mvc.perform(get("/jobs/{id}/rodadas", JOB))
			.andExpect(status().isOk())
			.andReturn()
			.getResponse()
			.getContentAsString();
		var lista = new JsonMapper().readTree(corpo);
		assertThat(lista.isArray()).isTrue();
		assertThat(lista.size()).isEqualTo(2);
		for (var rodada : lista) {
			ContratoDeEvento.validarRespostaHttp("Rodada", rodada.toString());
		}
		assertThat(lista.path(0).path("correcao").path("texto").asString()).isEqualTo("Percentual 2,5%.");
		assertThat(lista.path(1).path("correcao").isNull()).isTrue();
		assertThat(lista.path(1).path("regra_resultante_id").isNull()).isTrue();
	}

	@Test
	void vazioNaoDependeDeSse() throws Exception {
		when(rodadas.listar(JOB)).thenReturn(List.of());
		assertThat(mvc.perform(get("/jobs/{id}/rodadas", JOB))
			.andExpect(status().isOk())
			.andReturn()
			.getResponse()
			.getContentAsString()).isEqualTo("[]");
	}

	@Test
	void negaAuditorMesmoSendoDono() throws Exception {
		when(usuario.obter()).thenReturn(new AcessoDoUsuario(USUARIO, PapelDoUsuario.AUDITOR));
		mvc.perform(get("/jobs/{id}/rodadas", JOB)).andExpect(status().isForbidden());
		verifyNoInteractions(rodadas);
	}

	@Test
	void negaOutroDonoAntesDeLerHistorico() throws Exception {
		when(jobs.buscarProprietario(JOB)).thenReturn(List.of(UUID.randomUUID()));
		mvc.perform(get("/jobs/{id}/rodadas", JOB)).andExpect(status().isForbidden());
		verifyNoInteractions(rodadas);
	}

	@Test
	void inexistenteUsaCodigoDoContrato() throws Exception {
		when(jobs.buscarProprietario(JOB)).thenReturn(List.of());
		String corpo = mvc.perform(get("/jobs/{id}/rodadas", JOB))
			.andExpect(status().isNotFound())
			.andReturn()
			.getResponse()
			.getContentAsString();
		ContratoDeEvento.validarRespostaHttp("Erro", corpo);
		assertThat(new JsonMapper().readTree(corpo).path("codigo").asString()).isEqualTo("job_nao_encontrado");
		verifyNoInteractions(rodadas);
	}

}
