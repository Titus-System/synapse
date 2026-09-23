package synapse.api.job;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import java.util.stream.Stream;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.MethodSource;
import org.junit.jupiter.params.provider.ValueSource;

import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import synapse.api.core.sse.EmissoresSse;
import synapse.api.core.sse.EventoSse;
import synapse.api.core.security.AcessoDoUsuario;
import synapse.api.core.security.UsuarioAtual;
import synapse.api.job.ExecutarAcaoService.AcaoAplicada;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class ExecutarAcaoControllerTests {

	static final UUID JOB_ID = UUID.fromString("33333333-3333-4333-8333-333333333333");

	private final ExecutarAcaoService service = mock(ExecutarAcaoService.class);

	private final EmissoresSse emissores = mock(EmissoresSse.class);

	private final AutorizadorDeJob autorizador = mock(AutorizadorDeJob.class);

	private final UsuarioAtual usuarioAtual = mock(UsuarioAtual.class);

	private MockMvc mvc;

	@BeforeEach
	void preparar() {
		when(this.usuarioAtual.obter()).thenReturn(new AcessoDoUsuario(UUID.randomUUID(), false));
		this.mvc = MockMvcBuilders
			.standaloneSetup(
					new ExecutarAcaoController(this.service, this.emissores, this.autorizador, this.usuarioAtual))
			.setControllerAdvice(new ExecutarAcaoAdvice())
			.build();
	}

	private static JobDetalhadoDto jobComStatus(String status) {
		NucleoRegraDto nucleo = new NucleoRegraDto(null, null, null, null, null);
		RegraCriadaDto regra = new RegraCriadaDto(UUID.randomUUID(), 1, "confirmacao_usuario",
				new RepresentacaoRegraDto(nucleo, List.of()), Instant.parse("2026-09-16T15:00:00Z"));
		return new JobDetalhadoDto(JOB_ID, status, "formulario", List.of("2025-11"), new BigDecimal("485000"),
				Instant.parse("2026-09-16T15:00:00Z"), null, Instant.parse("2026-09-18T10:00:00Z"), UUID.randomUUID(),
				List.of(regra), null);
	}

	@ParameterizedTest
	@MethodSource("acoesEStatusDestino")
	void aplicaAcaoEEncerraOStream(String acao, JobStatus origem, JobStatus destino) throws Exception {
		EventoEstadoDto evento = EventoEstadoDto.transicao(JOB_ID, origem, destino, null);
		when(this.service.aplicar(eq(JOB_ID), eq(AcaoJob.deColuna(acao))))
			.thenReturn(new AcaoAplicada(evento, jobComStatus(destino.paraColuna())));

		this.mvc
			.perform(post("/jobs/{id}/actions", JOB_ID).contentType(MediaType.APPLICATION_JSON)
				.content("{\"acao\":\"%s\"}".formatted(acao)))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.status").value(destino.paraColuna()))
			.andExpect(jsonPath("$.regras.length()").value(1))
			.andExpect(jsonPath("$.regra").doesNotExist());

		verify(this.emissores).emitir(eq(JOB_ID), argThat(EventoSse::ultimo));
	}

	static Stream<org.junit.jupiter.params.provider.Arguments> acoesEStatusDestino() {
		return Stream.of(
				org.junit.jupiter.params.provider.Arguments.of("confirmar_liberar",
						JobStatus.AGUARDANDO_DECISAO_USUARIO, JobStatus.LIBERADO),
				org.junit.jupiter.params.provider.Arguments.of("salvar", JobStatus.AGUARDANDO_DECISAO_USUARIO,
						JobStatus.LIBERADO),
				org.junit.jupiter.params.provider.Arguments.of("cancelar", JobStatus.AGUARDANDO_DECISAO_USUARIO,
						JobStatus.CANCELADO),
				org.junit.jupiter.params.provider.Arguments.of("arquivar", JobStatus.SIMULACAO_INVIAVEL,
						JobStatus.ARQUIVADO));
	}

	@ParameterizedTest
	@ValueSource(strings = { "confirmar_liberar", "salvar" })
	void recusaLiberacaoDeJobInviavelCom409Especifico(String acao) throws Exception {
		when(this.service.aplicar(eq(JOB_ID), eq(AcaoJob.deColuna(acao))))
			.thenThrow(ExecutarAcaoException.simulacaoInviavel());

		this.mvc
			.perform(post("/jobs/{id}/actions", JOB_ID).contentType(MediaType.APPLICATION_JSON)
				.content("{\"acao\":\"%s\"}".formatted(acao)))
			.andExpect(status().isConflict())
			.andExpect(jsonPath("$.codigo").value("simulacao_inviavel"))
			.andExpect(jsonPath("$.mensagem").isNotEmpty());

		verifyNoInteractions(this.emissores);
	}

	@Test
	void recusaAcaoForaDoEstadoCom409NomeandoOEstadoExigido() throws Exception {
		when(this.service.aplicar(eq(JOB_ID), eq(AcaoJob.CANCELAR)))
			.thenThrow(ExecutarAcaoException.estadoInvalido(AcaoJob.CANCELAR, JobStatus.LIBERADO));

		this.mvc
			.perform(post("/jobs/{id}/actions", JOB_ID).contentType(MediaType.APPLICATION_JSON)
				.content("{\"acao\":\"cancelar\"}"))
			.andExpect(status().isConflict())
			.andExpect(jsonPath("$.codigo").value("estado_invalido"))
			.andExpect(jsonPath("$.mensagem")
				.value("A ação cancelar exige o job em aguardando_confirmacao_parametros, aguardando_decisao_usuario, "
						+ "simulacao_inviavel; o job está em liberado."));

		verifyNoInteractions(this.emissores);
	}

	@Test
	void jobInexistenteResponde404() throws Exception {
		when(this.service.aplicar(eq(JOB_ID), any())).thenThrow(new JobNaoEncontradoException(JOB_ID));

		this.mvc
			.perform(post("/jobs/{id}/actions", JOB_ID).contentType(MediaType.APPLICATION_JSON)
				.content("{\"acao\":\"cancelar\"}"))
			.andExpect(status().isNotFound())
			.andExpect(jsonPath("$.codigo").value("job_nao_encontrado"));

		verifyNoInteractions(this.emissores);
	}

	@ParameterizedTest
	@ValueSource(
			strings = { "", "{", "null", "[]", "{}", "{\"acao\":null}", "{\"acao\":5}", "{\"acao\":\"reprocessar\"}" })
	void corpoInvalidoResponde400SemChamarOService(String corpo) throws Exception {
		this.mvc.perform(post("/jobs/{id}/actions", JOB_ID).contentType(MediaType.APPLICATION_JSON).content(corpo))
			.andExpect(status().isBadRequest())
			.andExpect(jsonPath("$.codigo").value("requisicao_invalida"));

		verifyNoInteractions(this.service, this.emissores);
	}

	@Test
	void naoExpoeErroDoJdbc() throws Exception {
		when(this.service.aplicar(eq(JOB_ID), any())).thenThrow(new DataIntegrityViolationException("stack trace"));

		this.mvc
			.perform(post("/jobs/{id}/actions", JOB_ID).contentType(MediaType.APPLICATION_JSON)
				.content("{\"acao\":\"cancelar\"}"))
			.andExpect(status().isInternalServerError())
			.andExpect(content().string(""));
	}

}
