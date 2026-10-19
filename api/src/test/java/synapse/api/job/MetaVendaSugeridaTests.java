package synapse.api.job;

import java.math.BigDecimal;
import java.util.UUID;

import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.slf4j.MDC;
import tools.jackson.databind.json.JsonMapper;

import org.springframework.dao.DataAccessResourceFailureException;

import synapse.api.core.logging.CorrelationContext;
import synapse.api.core.metrics.AppMetrics;
import synapse.api.core.sse.EmissoresSse;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

class MetaVendaSugeridaTests {

	@ParameterizedTest
	@ValueSource(strings = { "{}", "{\"meta_venda\":2000}", "{\"meta_venda\":-1,\"resultado_id\":\"%s\"}",
			"{\"sem_solucao\":{\"motivo\":\"desconhecido\"}}",
			"{\"meta_venda\":2000,\"resultado_id\":\"%s\",\"sem_solucao\":{\"motivo\":\"falha_execucao\"}}" })
	void payloadInvalidoNaoVaiAoBancoNemAoSse(String campos) {
		var servico = mock(JobEventosService.class);
		var emissores = mock(EmissoresSse.class);
		var registro = new SimpleMeterRegistry();
		var consumidor = new MetaVendaSugeridaConsumidor(servico, emissores, new CorrelationContext(),
				new AppMetrics(registro));
		String body = campos.formatted(UUID.randomUUID());
		if (!campos.equals("{}")) {
			body = "{\"job_id\":\"%s\",\"regra_id\":\"%s\",%s}".formatted(UUID.randomUUID(), UUID.randomUUID(),
					body.substring(1, body.length() - 1));
		}
		consumidor.receber(new JsonMapper().readValue(body, MetaVendaSugeridaDto.class));
		verifyNoInteractions(servico, emissores);
		assertThat(registro.get("meta.venda.sugerida.consumo").tag("resultado", "invalida").counter().count())
			.isEqualTo(1);
		assertThat(MDC.get(CorrelationContext.JOB_ID_KEY)).isNull();
	}

	@Test
	void aceitaAsDuasFormasDoContrato() throws Exception {
		var json = new JsonMapper();
		String comMeta = """
				{"job_id":"%s","regra_id":"%s","resultado_id":"%s","meta_venda":2000}
				""".formatted(UUID.randomUUID(), UUID.randomUUID(), UUID.randomUUID());
		String semMeta = """
				{"job_id":"%s","regra_id":"%s","sem_solucao":{"motivo":"intervalo_esgotado"}}
				""".formatted(UUID.randomUUID(), UUID.randomUUID());
		for (String corpo : new String[] { comMeta, semMeta }) {
			ContratoDeEvento.validar("meta-venda-sugerida", corpo);
			assertThat(json.readValue(corpo, MetaVendaSugeridaDto.class).valida()).isTrue();
		}
	}

	@Test
	void falhaDePersistenciaContaTentativaSemAnunciarSugestaoNemExporDetalhe() throws Exception {
		var servico = mock(JobEventosService.class);
		var emissores = mock(EmissoresSse.class);
		var registro = new SimpleMeterRegistry();
		var consumidor = new MetaVendaSugeridaConsumidor(servico, emissores, new CorrelationContext(),
				new AppMetrics(registro));
		UUID jobId = UUID.randomUUID();
		var evento = new MetaVendaSugeridaDto(jobId, UUID.randomUUID(), UUID.randomUUID(), new BigDecimal("2000"),
				null);
		var falha = new DataAccessResourceFailureException("detalhe-interno-proibido");
		when(servico.registrarMetaSugerida(evento)).thenThrow(falha);
		try (CapturaDeLog captura = new CapturaDeLog(MetaVendaSugeridaConsumidor.class)) {
			assertThatThrownBy(() -> consumidor.receber(evento)).isSameAs(falha);
			assertThat(captura.eventos()).hasSize(1);
			String linha = CapturaDeLog.emJson(captura.eventos().getFirst());
			ContratoDeEvento.validarLog(linha);
			var log = new JsonMapper().readTree(linha);
			assertThat(log.path("job_id").asString()).isEqualTo(jobId.toString());
			assertThat(log.path("level").asString()).isEqualTo("WARN");
			assertThat(linha).doesNotContain("detalhe-interno-proibido", "\"exception\"", "\"meta_venda\"");
		}
		verifyNoInteractions(emissores);
		assertThat(registro.get("meta.venda.sugerida.consumo").tag("resultado", "falha").counter().count())
			.isEqualTo(1);
		assertThat(registro.find("meta.venda.sugerida.consumo").tag("resultado", "registrada").counter()).isNull();
		assertThat(MDC.get(CorrelationContext.JOB_ID_KEY)).isNull();
	}

}
