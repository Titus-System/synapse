package synapse.api.job;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

import ch.qos.logback.classic.spi.ILoggingEvent;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.EnumSource;
import org.mockito.InOrder;
import org.slf4j.MDC;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import synapse.api.core.logging.CorrelationContext;
import synapse.api.core.sse.EmissoresSse;
import synapse.api.core.sse.EventoSse;
import synapse.api.job.JobEventosService.BuscaMetaAnunciada;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/**
 * O começo e o fim da busca da meta maior anunciados no SSE (T-283). Quem decide se a
 * busca está em curso é o serviço, sobre o que gravou; o consumidor só anuncia depois do
 * commit.
 */
class BuscaMetaAnunciadaTests {

	private static final JsonMapper JSON = new JsonMapper();

	private static NoConcluidoDto decisao(UUID jobId) throws Exception {
		String corpo = """
				{"evento_id":"%s","job_id":"%s","no":"decisao","concluido_em":"2026-10-18T21:36:27Z",
				 "conclusao":{"resumo":"Fluxo encaminhado para a busca de uma meta maior.",
				              "encaminhamento":"busca_meta"},
				 "regra_id":"%s"}
				""".formatted(UUID.randomUUID(), jobId, UUID.randomUUID());
		ContratoDeEvento.validar("no-concluido", corpo);
		return JSON.readValue(corpo, NoConcluidoDto.class);
	}

	@ParameterizedTest
	@EnumSource(value = BuscaMetaAnunciada.class, names = { "INICIADA", "ENCERRADA" })
	void oComecoEOFimDaBuscaSaoAnunciadosDepoisDeGravados(BuscaMetaAnunciada busca) throws Exception {
		var servico = mock(JobEventosService.class);
		var emissores = mock(EmissoresSse.class);
		var consumidor = new NoConcluidoConsumidor(servico, emissores, new CorrelationContext());
		UUID jobId = UUID.randomUUID();
		NoConcluidoDto evento = decisao(jobId);
		when(servico.registrarNoConcluido(eq(jobId), any(), eq(EtapaDoGrafo.DECISAO), eq(evento))).thenReturn(busca);

		try (CapturaDeLog captura = new CapturaDeLog(NoConcluidoConsumidor.class)) {
			consumidor.receber(evento);

			ILoggingEvent anuncio = captura.eventos()
				.stream()
				.filter((linha) -> "busca da meta maior anunciada".equals(linha.getMessage()))
				.findFirst()
				.orElseThrow();
			String linha = CapturaDeLog.emJson(anuncio);
			ContratoDeEvento.validarLog(linha);
			JsonNode log = JSON.readTree(linha);
			assertThat(log.path("level").asString()).isEqualTo("INFO");
			assertThat(log.path("job_id").asString()).isEqualTo(jobId.toString());
			assertThat(log.path("extra").path("status").asString()).isEqualTo(busca.status());
		}

		String esperado = busca == BuscaMetaAnunciada.INICIADA ? "buscando_meta" : "busca_meta_encerrada";
		EventoEtapaDto etapa = new EventoEtapaDto(jobId, "sugestao_adaptacao", esperado);
		InOrder ordem = inOrder(servico, emissores);
		ordem.verify(servico).registrarNoConcluido(eq(jobId), any(), eq(EtapaDoGrafo.DECISAO), eq(evento));
		ordem.verify(emissores).emitir(jobId, EventoSse.de("etapa", etapa));
		ContratoDeEvento.validarRespostaHttp("EventoEtapa", JSON.writeValueAsString(etapa));
		assertThat(MDC.get(CorrelationContext.JOB_ID_KEY)).isNull();
	}

	@Test
	void oJobComABuscaEmCursoSaiNoContratoEOSemBuscaNaoTrazOCampo() throws Exception {
		for (Boolean emCurso : new Boolean[] { Boolean.TRUE, null }) {
			var job = new JobDetalhadoDto(UUID.randomUUID(), "aguardando_decisao_usuario", "texto", List.of("2025-11"),
					new BigDecimal("600000"), new BigDecimal("26000000"), Instant.parse("2025-11-24T16:00:00Z"), null,
					null, UUID.randomUUID(), null, null, List.of(), null, List.of(), null, null, emCurso);

			String corpo = JSON.writeValueAsString(job);

			ContratoDeEvento.validarRespostaHttp("JobDetalhado", corpo);
			if (emCurso == null) {
				assertThat(JSON.readTree(corpo).has("busca_meta_em_curso")).isFalse();
			}
			else {
				assertThat(JSON.readTree(corpo).path("busca_meta_em_curso").asBoolean()).isTrue();
			}
		}
	}

	@Test
	void semBuscaAbertaNadaVaiAoSse() throws Exception {
		var servico = mock(JobEventosService.class);
		var emissores = mock(EmissoresSse.class);
		var consumidor = new NoConcluidoConsumidor(servico, emissores, new CorrelationContext());
		UUID jobId = UUID.randomUUID();
		NoConcluidoDto evento = decisao(jobId);
		when(servico.registrarNoConcluido(eq(jobId), any(), eq(EtapaDoGrafo.DECISAO), eq(evento)))
			.thenReturn(BuscaMetaAnunciada.NENHUMA);

		try (CapturaDeLog captura = new CapturaDeLog(NoConcluidoConsumidor.class)) {
			consumidor.receber(evento);

			assertThat(captura.eventos()).extracting(ILoggingEvent::getMessage)
				.doesNotContain("busca da meta maior anunciada");
		}
		verifyNoInteractions(emissores);
	}

}
