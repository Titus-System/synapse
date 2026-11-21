package synapse.api.job;

import java.time.Instant;
import java.util.UUID;

import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.jspecify.annotations.Nullable;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.EnumSource;
import org.mockito.ArgumentCaptor;
import org.slf4j.MDC;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.dao.EmptyResultDataAccessException;

import synapse.api.core.logging.CorrelationContext;
import synapse.api.core.metrics.AppMetrics;
import synapse.api.core.sse.EmissoresSse;
import synapse.api.core.sse.EventoSse;
import synapse.api.job.JobEventosService.DesfechoDaExplicacao;
import synapse.api.job.JobEventosService.ExplicacaoRegistrada;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/**
 * O consumo do {@code no-concluido} da etapa de explicação pelo consumidor real, com o
 * serviço transacional no lugar de um mock: o que sai depois do commit (evento do stream,
 * contador e log) e o que não sai quando a linha já existia ou a gravação falhou. As
 * consequências no banco estão em {@code ExplicacaoDoResultadoTests}.
 */
class ExplicacaoConsumidorTests {

	private static final String NARRATIVA_RESERVADA = "narrativa reservada do resultado";

	private final SimpleMeterRegistry registry = new SimpleMeterRegistry();

	private final JobEventosService servico = mock(JobEventosService.class);

	private final EmissoresSse emissores = mock(EmissoresSse.class);

	@AfterEach
	void fecharRegistry() {
		this.registry.close();
		MDC.clear();
	}

	private NoConcluidoConsumidor consumidor() {
		return new NoConcluidoConsumidor(this.servico, this.emissores, new CorrelationContext(),
				new AppMetrics(this.registry));
	}

	private static NoConcluidoDto evento(UUID jobId, @Nullable UUID resultadoId, @Nullable UUID explicacaoId) {
		return new NoConcluidoDto(UUID.randomUUID(), jobId, "explicacao", Instant.now(),
				new JsonMapper().readTree("{\"resumo\":\"" + NARRATIVA_RESERVADA + "\"}"), UUID.randomUUID(), null,
				null, null, explicacaoId, resultadoId);
	}

	private double contagem(String nome, String tag, String valor) {
		var contador = this.registry.find(nome).tag(tag, valor).counter();
		return (contador != null) ? contador.count() : 0;
	}

	@ParameterizedTest
	@EnumSource(DesfechoDaExplicacao.class)
	void anunciaDepoisDoCommitSoComReferenciasEDisponibilidade(DesfechoDaExplicacao desfecho) throws Exception {
		UUID jobId = UUID.randomUUID();
		UUID simulacaoId = UUID.randomUUID();
		NoConcluidoDto evento = evento(jobId, UUID.randomUUID(), UUID.randomUUID());
		when(this.servico.registrarExplicacao(any(), any(), any()))
			.thenReturn(new ExplicacaoRegistrada(simulacaoId, desfecho));

		consumidor().receber(evento);

		ArgumentCaptor<EventoSse> anunciado = ArgumentCaptor.forClass(EventoSse.class);
		verify(this.emissores).emitir(eq(jobId), anunciado.capture());
		assertThat(anunciado.getValue().nome()).isEqualTo("explicacao");
		assertThat(anunciado.getValue().ultimo()).isFalse();
		String dados = new JsonMapper().writeValueAsString(anunciado.getValue().dados());
		ContratoDeEvento.validarEventoDoStream("explicacao", dados);
		JsonNode json = new JsonMapper().readTree(dados);
		assertThat(json.propertyNames()).containsExactlyInAnyOrder("job_id", "simulacao_id", "disponivel");
		assertThat(json.path("job_id").asString()).isEqualTo(jobId.toString());
		assertThat(json.path("simulacao_id").asString()).isEqualTo(simulacaoId.toString());
		assertThat(json.path("disponivel").asBoolean()).isEqualTo(desfecho == DesfechoDaExplicacao.CONFERIDA);
		assertThat(dados).doesNotContain(NARRATIVA_RESERVADA);
	}

	@ParameterizedTest
	@EnumSource(DesfechoDaExplicacao.class)
	void contaODesfechoRegistradoEOConsumoGravado(DesfechoDaExplicacao desfecho) {
		when(this.servico.registrarExplicacao(any(), any(), any()))
			.thenReturn(new ExplicacaoRegistrada(UUID.randomUUID(), desfecho));

		consumidor().receber(evento(UUID.randomUUID(), UUID.randomUUID(), UUID.randomUUID()));

		assertThat(contagem("explicacao.registrada", "desfecho", desfecho.rotulo())).isEqualTo(1);
		assertThat(contagem("no.concluido.consumo", "resultado", "gravado")).isEqualTo(1);
		assertThat(this.registry.getMeters()).hasSize(2);
	}

	@Test
	void aReentregaJaGravadaNaoAnunciaNemContaODesfechoDeNovo() {
		when(this.servico.registrarExplicacao(any(), any(), any())).thenReturn(null);

		consumidor().receber(evento(UUID.randomUUID(), UUID.randomUUID(), UUID.randomUUID()));

		verifyNoInteractions(this.emissores);
		assertThat(contagem("no.concluido.consumo", "resultado", "duplicado")).isEqualTo(1);
		assertThat(this.registry.find("explicacao.registrada").counters()).isEmpty();
	}

	@Test
	void oLogDoDesfechoTrazOJobEODesfechoSemANarrativaNemAConclusao() throws Exception {
		UUID jobId = UUID.randomUUID();
		when(this.servico.registrarExplicacao(any(), any(), any()))
			.thenReturn(new ExplicacaoRegistrada(UUID.randomUUID(), DesfechoDaExplicacao.REPROVADA));
		MDC.put("job_id", "anterior");

		try (var captura = new CapturaDeLog(NoConcluidoConsumidor.class)) {
			consumidor().receber(evento(jobId, UUID.randomUUID(), UUID.randomUUID()));

			assertThat(captura.eventos()).hasSize(1);
			String linha = CapturaDeLog.emJson(captura.eventos().getFirst());
			ContratoDeEvento.validarLog(linha);
			JsonNode json = new JsonMapper().readTree(linha);
			assertThat(json.path("job_id").asString()).isEqualTo(jobId.toString());
			assertThat(json.path("extra").path("desfecho").asString()).isEqualTo("reprovada");
			assertThat(linha).doesNotContain(NARRATIVA_RESERVADA, "conclusao", "texto");
		}
		assertThat(MDC.get("job_id")).isEqualTo("anterior");
	}

	@Test
	void simulacaoDoResultadoInexistenteRegistraAvisoEPropagaParaAMensagemVoltarAFila() throws Exception {
		UUID jobId = UUID.randomUUID();
		UUID resultadoId = UUID.randomUUID();
		when(this.servico.registrarExplicacao(any(), any(), any()))
			.thenThrow(new SimulacaoDaExplicacaoInexistenteException());
		MDC.put("job_id", "anterior");

		try (var captura = new CapturaDeLog(NoConcluidoConsumidor.class)) {
			var consumidor = consumidor();
			var evento = evento(jobId, resultadoId, UUID.randomUUID());
			assertThatThrownBy(() -> consumidor.receber(evento)).isInstanceOf(FalhaPersistenciaTrilhaException.class)
				.hasNoCause();

			assertThat(captura.eventos()).hasSize(1);
			assertThat(captura.eventos().getFirst().getLevel().toString()).isEqualTo("WARN");
			String linha = CapturaDeLog.emJson(captura.eventos().getFirst());
			ContratoDeEvento.validarLog(linha);
			JsonNode json = new JsonMapper().readTree(linha);
			assertThat(json.path("job_id").asString()).isEqualTo(jobId.toString());
			assertThat(json.path("extra").path("resultado_id").asString()).isEqualTo(resultadoId.toString());
			assertThat(linha).doesNotContain(NARRATIVA_RESERVADA, "conclusao");
		}
		assertThat(MDC.get("job_id")).isEqualTo("anterior");
		verifyNoInteractions(this.emissores);
		assertThat(contagem("no.concluido.consumo", "resultado", "falha")).isEqualTo(1);
		assertThat(this.registry.find("explicacao.registrada").counters()).isEmpty();
	}

	@Test
	void falhaDeBancoNaGravacaoPropagaSemAnunciarNemContarODesfecho() {
		when(this.servico.registrarExplicacao(any(), any(), any()))
			.thenThrow(new DataAccessResourceFailureException("conteudo reservado senha"));
		var consumidor = consumidor();
		var evento = evento(UUID.randomUUID(), UUID.randomUUID(), UUID.randomUUID());

		assertThatThrownBy(() -> consumidor.receber(evento)).isInstanceOf(FalhaPersistenciaTrilhaException.class)
			.hasNoCause();

		verifyNoInteractions(this.emissores);
		assertThat(contagem("no.concluido.consumo", "resultado", "falha")).isEqualTo(1);
		assertThat(this.registry.find("explicacao.registrada").counters()).isEmpty();
	}

	@Test
	void eventoDaExplicacaoSemResultadoEDescartadoSemChamarOServico() {
		consumidor().receber(evento(UUID.randomUUID(), null, UUID.randomUUID()));

		verifyNoInteractions(this.servico, this.emissores);
		assertThat(contagem("no.concluido.consumo", "resultado", "descartado")).isEqualTo(1);
	}

	@Test
	void jobDesconhecidoEDescartadoSemAnunciar() {
		when(this.servico.registrarExplicacao(any(), any(), any())).thenThrow(new EmptyResultDataAccessException(1));

		consumidor().receber(evento(UUID.randomUUID(), UUID.randomUUID(), UUID.randomUUID()));

		verifyNoInteractions(this.emissores);
		assertThat(contagem("no.concluido.consumo", "resultado", "descartado")).isEqualTo(1);
		assertThat(this.registry.find("explicacao.registrada").counters()).isEmpty();
	}

}
