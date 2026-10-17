package synapse.api.job;

import java.util.UUID;

import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;

import synapse.api.core.logging.CorrelationContext;
import synapse.api.core.metrics.AppMetrics;
import synapse.api.core.sse.EmissoresSse;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;

class ExecucoesCandidatasTests {

	@Test
	void candidataNaoConcluiSimulacaoNemAnunciaResultado() {
		var servico = mock(JobEventosService.class);
		var emissores = mock(EmissoresSse.class);
		var registro = new SimpleMeterRegistry();
		var consumidor = new SimulacaoConcluidaConsumidor(servico, emissores, new CorrelationContext(),
				new AppMetrics(registro));
		String corpo = """
				{"job_id":"%s","resultado_id":"%s","status":"sucesso","veredito":"viavel",
				 "proposito":"busca_meta","meta_venda":1000}
				""".formatted(UUID.randomUUID(), UUID.randomUUID());
		consumidor.receber(new JsonMapper().readValue(corpo, SimulacaoConcluidaDto.class));
		verifyNoInteractions(servico, emissores);
		assertThat(registro.find("simulacao.concluida.consumo").meters()).isEmpty();
		assertThat(registro.get("simulacao.candidata.consumo").counter().count()).isEqualTo(1);
	}

	@Test
	void totaisPreservamVendasHistoricasGravadasPeloWorker() {
		var json = new JsonMapper();
		var totais = json.readValue("""
				{"baseline":10,"simulado":20,"diferenca_abs":10,"diferenca_pct":100,"vendas_historicas":1234}
				""", TotaisSimulacaoDto.class);
		assertThat(json.readTree(json.writeValueAsString(totais)).path("vendas_historicas").asInt()).isEqualTo(1234);
	}

}
