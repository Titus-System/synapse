package synapse.api.job;

import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.EnumSource;
import org.junit.jupiter.params.provider.ValueSource;
import org.slf4j.MDC;
import tools.jackson.databind.json.JsonMapper;

import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.dao.EmptyResultDataAccessException;
import org.springframework.transaction.TransactionSystemException;

import synapse.api.core.logging.CorrelationContext;
import synapse.api.core.metrics.AppMetrics;
import synapse.api.core.sse.EmissoresSse;
import synapse.api.job.JobEventosService.BuscaMetaAnunciada;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

class NoConcluidoObservabilidadeTests {

	private final SimpleMeterRegistry registry = new SimpleMeterRegistry();

	@AfterEach
	void fecharRegistry() {
		this.registry.close();
	}

	private final JobEventosService servico = mock(JobEventosService.class);

	private final EmissoresSse emissores = mock(EmissoresSse.class);

	private static NoConcluidoDto evento(String no) {
		return new NoConcluidoDto(UUID.randomUUID(), UUID.randomUUID(), no, Instant.now(),
				new JsonMapper().readTree("{\"resumo\":\"conteudo reservado\"}"), null, null, null, null, null, null);
	}

	@ParameterizedTest
	@EnumSource(BuscaMetaAnunciada.class)
	void contabilizaApenasOResultadoConfirmado(BuscaMetaAnunciada resultado) {
		when(this.servico.registrarNoConcluido(any(), any(), any(), any())).thenReturn(resultado);
		new NoConcluidoConsumidor(this.servico, this.emissores, new CorrelationContext(), new AppMetrics(this.registry))
			.receber(evento("decisao"));
		String esperado = resultado == BuscaMetaAnunciada.DUPLICADA ? "duplicado" : "gravado";
		assertThat(this.registry.get("no.concluido.consumo").tag("resultado", esperado).counter().count()).isEqualTo(1);
		assertThat(this.registry.getMeters()).hasSize(1);
	}

	@ParameterizedTest
	@ValueSource(strings = { "confirmacao", "inventado", "desconhecido" })
	void descarteNaoLancaNemAnuncia(String no) {
		if (no.equals("desconhecido")) {
			when(this.servico.registrarNoConcluido(any(), any(), any(), any()))
				.thenThrow(new EmptyResultDataAccessException(1));
		}
		new NoConcluidoConsumidor(this.servico, this.emissores, new CorrelationContext(), new AppMetrics(this.registry))
			.receber(evento(no.equals("desconhecido") ? "decisao" : no));
		assertThat(this.registry.get("no.concluido.consumo").tag("resultado", "descartado").counter().count())
			.isEqualTo(1);
		verifyNoInteractions(this.emissores);
	}

	@ParameterizedTest
	@ValueSource(booleans = { false, true })
	void falhaDeBancoOuCommitPropagaSemConteudoERestauraCorrelacao(boolean commit) throws Exception {
		RuntimeException falha = commit ? new TransactionSystemException("conteudo reservado senha")
				: new DataAccessResourceFailureException("conteudo reservado senha");
		when(this.servico.registrarNoConcluido(any(), any(), any(), any())).thenThrow(falha);
		var evento = evento("decisao");
		MDC.put("job_id", "anterior");
		try (var captura = new CapturaDeLog(NoConcluidoConsumidor.class)) {
			var consumidor = new NoConcluidoConsumidor(this.servico, this.emissores, new CorrelationContext(),
					new AppMetrics(this.registry));
			assertThatThrownBy(() -> consumidor.receber(evento)).isInstanceOf(FalhaPersistenciaTrilhaException.class)
				.hasNoCause()
				.hasMessage("falha de persistência ao consumir no-concluido");
			assertThat(MDC.get("job_id")).isEqualTo("anterior");
			assertThat(this.registry.get("no.concluido.consumo").tag("resultado", "falha").counter().count())
				.isEqualTo(1);
			assertThat(this.registry.getMeters()).hasSize(1);
			assertThat(captura.eventos()).hasSize(1);
			String linha = CapturaDeLog.emJson(captura.eventos().getFirst());
			ContratoDeEvento.validarLog(linha);
			assertThat(linha).doesNotContain("conteudo reservado", "senha", "exception", "conclusao");
			var json = new JsonMapper().readTree(linha);
			assertThat(json.path("job_id").asString()).isEqualTo(Objects.requireNonNull(evento.job_id()).toString());
			assertThat(json.path("extra").path("no").asString()).isEqualTo("decisao");
			assertThat(json.path("extra").path("classe_falha").asString()).isEqualTo(falha.getClass().getSimpleName());
			verifyNoInteractions(this.emissores);
		}
		finally {
			MDC.clear();
		}
	}

}
