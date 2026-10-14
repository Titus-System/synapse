package synapse.api.job;

import java.util.UUID;

import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.EnumSource;
import org.slf4j.MDC;
import tools.jackson.databind.json.JsonMapper;

import org.springframework.dao.DataAccessResourceFailureException;

import synapse.api.core.logging.CorrelationContext;
import synapse.api.core.metrics.AppMetrics;
import synapse.api.core.sse.EmissoresSse;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.BDDMockito.given;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;

class EtapaAlteradaObservabilidadeTests {

	private final UUID job = UUID.randomUUID();

	private final UUID regra = UUID.randomUUID();

	private final JobEventosService servico = mock(JobEventosService.class);

	private final EmissoresSse emissores = mock(EmissoresSse.class);

	private final SimpleMeterRegistry registry = new SimpleMeterRegistry();

	private final EtapaAlteradaConsumidor consumidor = new EtapaAlteradaConsumidor(this.servico, this.emissores,
			new CorrelationContext(), new AppMetrics(this.registry));

	@AfterEach
	void limpar() {
		MDC.clear();
		this.registry.close();
	}

	@ParameterizedTest
	@EnumSource(value = DesfechoCorrecao.class, mode = EnumSource.Mode.EXCLUDE, names = "COMUM")
	void resultadoRestauraContextoEContabilizaSemConteudo(DesfechoCorrecao desfecho) throws Exception {
		given(this.servico.aplicarEtapaAlterada(this.job, EtapaDoGrafo.CONFIRMACAO, "aguardando_correcao", this.regra,
				null))
			.willReturn(new EtapaAplicada(desfecho, null, this.regra, UUID.randomUUID(), 2));
		MDC.put("job_id", "anterior");
		MDC.put("user_id", "usuario-anterior");
		try (CapturaDeLog captura = new CapturaDeLog(EtapaAlteradaConsumidor.class)) {
			this.consumidor.receber(new EtapaAlteradaDto(this.job, "confirmacao", "aguardando_correcao",
					"texto reservado", this.regra, null));
			assertThat(MDC.get("job_id")).isEqualTo("anterior");
			assertThat(MDC.get("user_id")).isEqualTo("usuario-anterior");
			assertThat(captura.eventos()).hasSize(1);
			String linha = CapturaDeLog.emJson(captura.eventos().getFirst());
			ContratoDeEvento.validarLog(linha);
			assertThat(linha).doesNotContain("texto reservado");
			var json = new JsonMapper().readTree(linha);
			assertThat(json.path("job_id").asString()).isEqualTo(this.job.toString());
			assertThat(json.path("extra").path("resultado").asString()).isEqualTo(desfecho.resultado());
			assertThat(json.path("extra").path("motivo_descarte").asString()).isEqualTo(desfecho.motivo());
			assertThat(json.path("extra").path("numero_conflitos").asInt()).isEqualTo(2);
		}
		assertThat(
				this.registry.get("etapa.alterada.correcao").tag("resultado", desfecho.resultado()).counter().count())
			.isEqualTo(1);
		assertThat(this.registry.get("etapa.alterada.consumo.duracao")
			.tag("resultado", desfecho.resultado())
			.timer()
			.count()).isEqualTo(1);
	}

	@Test
	void falhaTransitoriaPropagaSemContarSucessoERestauraMdc() throws Exception {
		given(this.servico.aplicarEtapaAlterada(this.job, EtapaDoGrafo.CONFIRMACAO, "aguardando_correcao", this.regra,
				null))
			.willThrow(new DataAccessResourceFailureException("payload reservado credencial"));
		MDC.put("job_id", "anterior");
		try (CapturaDeLog captura = new CapturaDeLog(EtapaAlteradaConsumidor.class)) {
			assertThatThrownBy(() -> this.consumidor
				.receber(new EtapaAlteradaDto(this.job, "confirmacao", "aguardando_correcao", null, this.regra, null)))
				.isInstanceOf(DataAccessResourceFailureException.class);
			assertThat(MDC.get("job_id")).isEqualTo("anterior");
			assertThat(captura.eventos()).hasSize(1);
			String linha = CapturaDeLog.emJson(captura.eventos().getFirst());
			ContratoDeEvento.validarLog(linha);
			assertThat(linha).doesNotContain("payload reservado", "credencial", "exception")
				.contains(this.job.toString());
		}
		assertThat(this.registry.find("etapa.alterada.correcao").counters()).isEmpty();
		assertThat(this.registry.get("etapa.alterada.consumo.duracao").tag("resultado", "falha").timer().count())
			.isEqualTo(1);
		verifyNoInteractions(this.emissores);
	}

	@Test
	void eventoComumNaoContaComoCorrecao() {
		given(this.servico.aplicarEtapaAlterada(this.job, EtapaDoGrafo.EXTRACAO_PARAMETROS, "erro", null, null))
			.willReturn(EtapaAplicada.comum(null));
		this.consumidor.receber(new EtapaAlteradaDto(this.job, "extracao_parametros", "erro", null, null, null));
		assertThat(this.registry.find("etapa.alterada.correcao").counters()).isEmpty();
		assertThat(MDC.get("job_id")).isNull();
	}

	@Test
	void entradaInvalidaLimpaMdcSemConsultarServico() {
		this.consumidor.receber(new EtapaAlteradaDto(this.job, "etapa desconhecida reservada", "aguardando_correcao",
				null, this.regra, null));
		assertThat(MDC.get("job_id")).isNull();
		verifyNoInteractions(this.servico, this.emissores);
		assertThat(this.registry.get("etapa.alterada.correcao").tag("resultado", "descartada").counter().count())
			.isEqualTo(1);
	}

}
