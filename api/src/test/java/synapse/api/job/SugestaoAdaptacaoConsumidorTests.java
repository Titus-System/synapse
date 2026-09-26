package synapse.api.job;

import java.math.BigDecimal;
import java.util.List;
import java.util.UUID;
import java.util.stream.Stream;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.MethodSource;
import tools.jackson.databind.json.JsonMapper;

import synapse.api.core.logging.CorrelationContext;
import synapse.api.core.sse.EmissoresSse;
import synapse.api.job.SugestaoAdaptacaoService.SugestaoAplicada;
import synapse.api.job.VersoesDaRegra.VersaoRegra;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.BDDMockito.given;
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

	private final SugestaoAdaptacaoService servico = mock(SugestaoAdaptacaoService.class);

	private final EmissoresSse emissores = mock(EmissoresSse.class);

	private final SugestaoAdaptacaoConsumidor consumidor = new SugestaoAdaptacaoConsumidor(this.servico, this.emissores,
			new CorrelationContext());

	@Test
	void aplicaAPropostaEAnunciaAVoltaParaGerandoRegra() {
		VersaoRegra versao = new VersaoRegra(UUID.randomUUID(), 2, "sugestao_adaptacao", java.time.Instant.EPOCH);
		given(this.servico.aplicar(eq(JOB_ID), eq(REGRA_ORIGEM_ID), any()))
			.willReturn(new SugestaoAplicada(JobStatus.SIMULACAO_INVIAVEL, versao));

		this.consumidor.receber(evento(representacao()));

		verify(this.servico).aplicar(eq(JOB_ID), eq(REGRA_ORIGEM_ID), any());
		verify(this.emissores).emitir(eq(JOB_ID), any());
	}

	@ParameterizedTest
	@MethodSource("eventosIncompletos")
	void descartaEventoIncompletoSemChamarOServico(SugestaoAdaptacaoPropostaDto evento) {
		this.consumidor.receber(evento);

		verifyNoInteractions(this.servico);
		verifyNoInteractions(this.emissores);
	}

	static Stream<SugestaoAdaptacaoPropostaDto> eventosIncompletos() {
		return Stream.of(new SugestaoAdaptacaoPropostaDto(null, REGRA_ORIGEM_ID, RESULTADO_ID, representacao()),
				new SugestaoAdaptacaoPropostaDto(JOB_ID, null, RESULTADO_ID, representacao()),
				new SugestaoAdaptacaoPropostaDto(JOB_ID, REGRA_ORIGEM_ID, RESULTADO_ID, null),
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

	@Test
	void descartaPropostaParaJobForaDoEstadoEsperadoSemEmitirEstado() {
		given(this.servico.aplicar(any(), any(), any()))
			.willThrow(new TransicaoDeStatusInvalidaException(JobStatus.GERANDO_REGRA, JobStatus.GERANDO_REGRA));

		this.consumidor.receber(evento(representacao()));

		verify(this.emissores, never()).emitir(any(), any());
	}

	private static SugestaoAdaptacaoPropostaDto doJson(String json) {
		return JsonMapper.builder().build().readValue(json, SugestaoAdaptacaoPropostaDto.class);
	}

	private static SugestaoAdaptacaoPropostaDto evento(RepresentacaoRegraDto representacao) {
		return new SugestaoAdaptacaoPropostaDto(JOB_ID, REGRA_ORIGEM_ID, RESULTADO_ID, representacao);
	}

	private static RepresentacaoRegraDto representacao() {
		return new RepresentacaoRegraDto(nucleo(), List.of());
	}

	private static NucleoRegraDto nucleo() {
		return new NucleoRegraDto(new VigenciaDto("2025-11", "2025-11"), List.of("13"), List.of("10"), List.of("100"),
				new BigDecimal("0.0246"));
	}

}
