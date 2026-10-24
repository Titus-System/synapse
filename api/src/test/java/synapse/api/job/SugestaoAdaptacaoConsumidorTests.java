package synapse.api.job;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.stream.Collectors;
import java.util.stream.Stream;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.MethodSource;
import org.junit.jupiter.params.provider.ValueSource;
import org.slf4j.MDC;
import tools.jackson.databind.json.JsonMapper;

import org.springframework.dao.DataAccessResourceFailureException;

import synapse.api.core.logging.CorrelationContext;
import synapse.api.core.metrics.AppMetrics;
import synapse.api.core.sse.EmissoresSse;
import synapse.api.core.sse.EventoSse;
import synapse.api.job.JobEventosService.DesfechoAplicado;
import synapse.api.job.JobEventosService.SugestaoAplicada;
import synapse.api.job.VersoesDaRegra.VersaoRegra;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatExceptionOfType;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.BDDMockito.given;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;

/**
 * O consumidor nunca lança: entrada incompleta e evento fora de ordem viram descarte, e
 * não requeue infinito.
 */
class SugestaoAdaptacaoConsumidorTests {

	private static final UUID JOB_ID = UUID.fromString("33333333-3333-4333-8333-333333333333");

	private static final UUID REGRA_ORIGEM_ID = UUID.fromString("44444444-4444-4444-8444-444444444444");

	private static final UUID RESULTADO_ID = UUID.fromString("55555555-5555-4555-8555-555555555555");

	private final JobEventosService servico = mock(JobEventosService.class);

	private final EmissoresSse emissores = mock(EmissoresSse.class);

	private final SimpleMeterRegistry registro = new SimpleMeterRegistry();

	private final SugestaoAdaptacaoConsumidor consumidor = new SugestaoAdaptacaoConsumidor(this.servico, this.emissores,
			new CorrelationContext(), new AppMetrics(this.registro));

	@Test
	void aplicaAPropostaEAnunciaAVoltaParaGerandoRegra() {
		VersaoRegra versao = new VersaoRegra(UUID.randomUUID(), 2, "sugestao_adaptacao", java.time.Instant.EPOCH);
		given(this.servico.aplicarSugestaoAdaptacao(eq(JOB_ID), eq(REGRA_ORIGEM_ID), eq(RESULTADO_ID), any(), eq(1)))
			.willReturn(new SugestaoAplicada(JobStatus.SIMULACAO_INVIAVEL, versao, null));

		this.consumidor.receber(evento(representacao(), 1));

		verify(this.servico).aplicarSugestaoAdaptacao(eq(JOB_ID), eq(REGRA_ORIGEM_ID), eq(RESULTADO_ID), any(), eq(1));
		verify(this.emissores).emitir(eq(JOB_ID), any());
		assertThat(contagens()).isEqualTo(Map.of("1/aplicada", 1.0));
	}

	/**
	 * A alternativa que não coube não é mostrada: a próxima tentativa sai de
	 * {@code simulando} sem {@code resultado} nem {@code estado} inviável no caminho.
	 */
	@Test
	void propostaQueParteDeUmaAlternativaNaoAnunciaOResultadoDela() {
		VersaoRegra versao = new VersaoRegra(UUID.randomUUID(), 3, "sugestao_adaptacao", java.time.Instant.EPOCH);
		given(this.servico.aplicarSugestaoAdaptacao(any(), any(), any(), any(), any()))
			.willReturn(new SugestaoAplicada(JobStatus.SIMULANDO, versao, DesfechoAplicado.intermediario(true)));
		List<EventoSse> eventos = emitidos();

		this.consumidor.receber(evento(representacao(), 2));

		assertThat(eventos).containsExactly(
				EventoSse.de("estado",
						EventoEstadoDto.transicao(JOB_ID, JobStatus.GERANDO_REGRA, JobStatus.SIMULANDO, null)),
				EventoSse.de("estado",
						EventoEstadoDto.transicao(JOB_ID, JobStatus.SIMULANDO, JobStatus.GERANDO_REGRA, null)));
		assertThat(contagens()).isEqualTo(Map.of("2/aplicada", 1.0));
	}

	@Test
	void propostaQueParteDaRegraOriginalAnunciaODesfechoInviavelAntesDaVolta() {
		VersaoRegra versao = new VersaoRegra(UUID.randomUUID(), 2, "sugestao_adaptacao", java.time.Instant.EPOCH);
		UUID simulacaoId = UUID.randomUUID();
		given(this.servico.aplicarSugestaoAdaptacao(any(), any(), any(), any(), any()))
			.willReturn(new SugestaoAplicada(JobStatus.SIMULACAO_INVIAVEL, versao,
					new DesfechoAplicado(JobStatus.SIMULANDO, simulacaoId, false, false, false)));
		List<EventoSse> eventos = emitidos();

		this.consumidor.receber(evento(representacao(), 1));

		assertThat(eventos).containsExactly(
				EventoSse.de("resultado", new EventoResultadoDto(JOB_ID, simulacaoId, "sucesso", "inviavel")),
				EventoSse.de("estado",
						EventoEstadoDto.transicao(JOB_ID, JobStatus.SIMULANDO, JobStatus.SIMULACAO_INVIAVEL,
								DesfechoDaSimulacao.INVIAVEL.razaoLocalizada())),
				EventoSse.de("estado", EventoEstadoDto.transicao(JOB_ID, JobStatus.SIMULACAO_INVIAVEL,
						JobStatus.GERANDO_REGRA, null)));
	}

	@Test
	void registraAAplicacaoComAVersaoEATentativaSemNadaDaRegra() throws Exception {
		VersaoRegra versao = new VersaoRegra(UUID.randomUUID(), 3, "sugestao_adaptacao", java.time.Instant.EPOCH);
		given(this.servico.aplicarSugestaoAdaptacao(any(), any(), any(), any(), any()))
			.willReturn(new SugestaoAplicada(JobStatus.SIMULANDO, versao, DesfechoAplicado.intermediario(false)));

		try (var anterior = new CorrelationContext().abrir("contexto-anterior", null);
				var captura = new CapturaDeLog(SugestaoAdaptacaoConsumidor.class)) {
			this.consumidor.receber(evento(representacao(), 2));
			assertThat(MDC.get("job_id")).isEqualTo("contexto-anterior");
			assertThat(captura.eventos()).hasSize(1);
			String linha = CapturaDeLog.emJson(captura.eventos().getFirst());
			ContratoDeEvento.validarLog(linha);
			var log = new JsonMapper().readTree(linha);
			assertThat(log.path("level").asString()).isEqualTo("INFO");
			assertThat(log.path("job_id").asString()).isEqualTo(JOB_ID.toString());
			assertThat(log.path("message").asString())
				.isEqualTo("sugestao-adaptacao-proposta aplicada; ciclo do codegen reaberto");
			assertThat(log.path("extra").path("regra_id").asString()).isEqualTo(versao.id().toString());
			assertThat(log.path("extra").path("versao").asInt()).isEqualTo(3);
			assertThat(log.path("extra").path("tentativa").asInt()).isEqualTo(2);
			assertThat(linha).doesNotContain("0.0246", "percentual", "nucleo", "representacao");
		}
	}

	@ParameterizedTest
	@MethodSource("eventosIncompletos")
	void descartaEventoIncompletoSemChamarOServico(SugestaoAdaptacaoPropostaDto evento) {
		this.consumidor.receber(evento);

		verifyNoInteractions(this.servico);
		verifyNoInteractions(this.emissores);
		assertThat(contagens()).isEqualTo(Map.of("ausente/invalida", 1.0));
	}

	@ParameterizedTest
	@ValueSource(ints = { 0, 4 })
	void descarteInvalidoPreservaCorrelacaoELimpaOContexto(int tentativa) throws Exception {
		try (var anterior = new CorrelationContext().abrir("contexto-anterior", null);
				var captura = new CapturaDeLog(SugestaoAdaptacaoConsumidor.class)) {
			this.consumidor.receber(evento(representacao(), tentativa));
			assertThat(MDC.get("job_id")).isEqualTo("contexto-anterior");
			String linha = CapturaDeLog.emJson(captura.eventos().getFirst());
			ContratoDeEvento.validarLog(linha);
			assertThat(new JsonMapper().readTree(linha).path("job_id").asString()).isEqualTo(JOB_ID.toString());
			assertThat(linha).doesNotContain("percentual", "0.0246");
		}
	}

	static Stream<SugestaoAdaptacaoPropostaDto> eventosIncompletos() {
		return Stream.of(new SugestaoAdaptacaoPropostaDto(null, REGRA_ORIGEM_ID, RESULTADO_ID, representacao(), null),
				new SugestaoAdaptacaoPropostaDto(JOB_ID, null, RESULTADO_ID, representacao(), null),
				new SugestaoAdaptacaoPropostaDto(JOB_ID, REGRA_ORIGEM_ID, null, representacao(), null),
				new SugestaoAdaptacaoPropostaDto(JOB_ID, REGRA_ORIGEM_ID, RESULTADO_ID, null, null),
				// Pelo JSON, porque é como o campo ausente chega de verdade: o tipo do
				// record não admite o nulo que a desserialização produz.
				doJson("""
						{"job_id":"%s","regra_origem_id":"%s","resultado_id":"%s",
						 "representacao":{"especificacoes":[]}}
						""".formatted(JOB_ID, REGRA_ORIGEM_ID, RESULTADO_ID)), doJson("""
						{"job_id":"%s","regra_origem_id":"%s","resultado_id":"%s",
						 "representacao":{"nucleo":{"percentual":0.0246}}}
						""".formatted(JOB_ID, REGRA_ORIGEM_ID, RESULTADO_ID)));
	}

	/** Fora da faixa do contrato: a reentrega não o corrigiria. */
	@ParameterizedTest
	@ValueSource(ints = { 0, 4, -1 })
	void descartaTentativaForaDaFaixaSemChamarOServico(int tentativa) {
		this.consumidor.receber(evento(representacao(), tentativa));

		verifyNoInteractions(this.servico);
		verifyNoInteractions(this.emissores);
		assertThat(contagens()).isEqualTo(Map.of("invalida/invalida", 1.0));
	}

	@Test
	void aTentativaChegaDoJsonDoEvento() {
		this.consumidor.receber(doJson("""
				{"job_id":"%s","regra_origem_id":"%s","resultado_id":"%s","tentativa":3,
				 "representacao":{"nucleo":{"percentual":0.0246},"especificacoes":[]}}
				""".formatted(JOB_ID, REGRA_ORIGEM_ID, RESULTADO_ID)));

		verify(this.servico).aplicarSugestaoAdaptacao(eq(JOB_ID), eq(REGRA_ORIGEM_ID), eq(RESULTADO_ID), any(), eq(3));
		assertThat(contagens()).isEqualTo(Map.of("3/descartada", 1.0));
	}

	@Test
	void descartaPropostaParaJobForaDoEstadoEsperadoSemEmitirEstado() {
		given(this.servico.aplicarSugestaoAdaptacao(any(), any(), any(), any(), any()))
			.willThrow(new TransicaoDeStatusInvalidaException(JobStatus.GERANDO_REGRA, JobStatus.GERANDO_REGRA));

		this.consumidor.receber(evento(representacao(), 2));

		verify(this.emissores, never()).emitir(any(), any());
		assertThat(contagens()).isEqualTo(Map.of("2/estado_incompativel", 1.0));
	}

	@Test
	void propostaIgnoradaNaoEmiteEstado() {
		this.consumidor.receber(evento(representacao(), null));
		verifyNoInteractions(this.emissores);
		assertThat(contagens()).isEqualTo(Map.of("ausente/descartada", 1.0));
	}

	/** A falha de banco volta à fila, e a reentrega é quem conta o desfecho. */
	@Test
	void falhaDeBancoVoltaAFilaEContaComoFalha() {
		given(this.servico.aplicarSugestaoAdaptacao(any(), any(), any(), any(), any()))
			.willThrow(new DataAccessResourceFailureException("banco fora"));

		assertThatExceptionOfType(DataAccessResourceFailureException.class)
			.isThrownBy(() -> this.consumidor.receber(evento(representacao(), 1)));

		verifyNoInteractions(this.emissores);
		assertThat(contagens()).isEqualTo(Map.of("1/falha", 1.0));
	}

	private List<EventoSse> emitidos() {
		List<EventoSse> eventos = new ArrayList<>();
		doAnswer(chamada -> eventos.add(chamada.getArgument(1, EventoSse.class))).when(this.emissores)
			.emitir(eq(JOB_ID), any());
		return eventos;
	}

	private Map<String, Double> contagens() {
		return this.registro.find("sugestao.adaptacao.proposta.consumo")
			.counters()
			.stream()
			.collect(Collectors.toMap(
					contador -> contador.getId().getTag("tentativa") + "/" + contador.getId().getTag("resultado"),
					Counter::count));
	}

	private static SugestaoAdaptacaoPropostaDto doJson(String json) {
		return JsonMapper.builder().build().readValue(json, SugestaoAdaptacaoPropostaDto.class);
	}

	private static SugestaoAdaptacaoPropostaDto evento(RepresentacaoRegraDto representacao,
			@org.jspecify.annotations.Nullable Integer tentativa) {
		return new SugestaoAdaptacaoPropostaDto(JOB_ID, REGRA_ORIGEM_ID, RESULTADO_ID, representacao, tentativa);
	}

	private static RepresentacaoRegraDto representacao() {
		return new RepresentacaoRegraDto(nucleo(), List.of());
	}

	private static NucleoRegraDto nucleo() {
		return new NucleoRegraDto(new VigenciaDto("2025-11", "2025-11"), List.of("13"), List.of("10"), List.of("100"),
				new BigDecimal("0.0246"));
	}

}
