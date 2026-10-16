package synapse.api.job;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

import ch.qos.logback.classic.Level;
import ch.qos.logback.classic.spi.ILoggingEvent;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.slf4j.MDC;

import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import synapse.api.core.logging.CorrelationContext;
import synapse.api.core.metrics.AppMetrics;
import synapse.api.core.sse.EmissoresSse;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class RenomearJobTests {

	private static final UUID JOB = UUID.fromString("3f2b1c40-0d18-4a51-9f2e-6c1d9a77b021");

	private final JobService service = mock(JobService.class);

	private MockMvc mvc;

	@BeforeEach
	void preparar() {
		this.mvc = MockMvcBuilders
			.standaloneSetup(new JobController(this.service, mock(EmissoresSse.class), new CorrelationContext(),
					mock(AppMetrics.class)))
			.setControllerAdvice(new JobAdvice())
			.build();
	}

	@Test
	void renomeacaoAceitaLogaInfoComJobIdESemONome() throws Exception {
		when(this.service.renomear(any(), any())).thenReturn(jobDetalhado());
		try (var captura = new CapturaDeLog(JobController.class)) {
			this.mvc.perform(renomear("{\"nome\":\"Segredo do usuario\"}")).andExpect(status().isOk());

			List<ILoggingEvent> eventos = captura.eventos();
			assertThat(eventos).hasSize(1);
			ILoggingEvent evento = eventos.getFirst();
			assertThat(evento.getLevel()).isEqualTo(Level.INFO);
			assertThat(evento.getFormattedMessage()).isEqualTo("regra renomeada");
			String json = CapturaDeLog.emJson(evento);
			assertThat(json).contains("\"job_id\":\"" + JOB + "\"");
			assertThat(json).doesNotContain("Segredo");
		}
	}

	@ParameterizedTest
	@CsvSource({ "'{}',nome_ausente", "'{\"nome\":123}',nome_ausente", "'{\"nome\":\"   \"}',nome_vazio" })
	void recusaLogaWarnComMotivoJobIdESemONome(String corpo, String motivo) throws Exception {
		try (var captura = new CapturaDeLog(JobController.class)) {
			this.mvc.perform(renomear(corpo)).andExpect(status().isBadRequest());

			List<ILoggingEvent> eventos = captura.eventos();
			assertThat(eventos).hasSize(1);
			ILoggingEvent evento = eventos.getFirst();
			assertThat(evento.getLevel()).isEqualTo(Level.WARN);
			assertThat(evento.getFormattedMessage()).isEqualTo("renomeação recusada: nome inválido");
			String json = CapturaDeLog.emJson(evento);
			assertThat(json).contains("\"job_id\":\"" + JOB + "\"");
			assertThat(json).contains("\"motivo\":\"" + motivo + "\"");
		}
	}

	@Test
	void recusaPorTamanhoLogaNomeMuitoLongoSemOTexto() throws Exception {
		String nome = "segredo".repeat(20);
		try (var captura = new CapturaDeLog(JobController.class)) {
			this.mvc.perform(renomear("{\"nome\":\"" + nome + "\"}")).andExpect(status().isBadRequest());

			assertThat(captura.eventos()).hasSize(1);
			String json = CapturaDeLog.emJson(captura.eventos().getFirst());
			assertThat(json).contains("\"motivo\":\"nome_muito_longo\"");
			assertThat(json).doesNotContain("segredo");
		}
	}

	@Test
	void correlacaoVoltaAoValorAnteriorNoSucessoENaRecusa() throws Exception {
		when(this.service.renomear(any(), any())).thenReturn(jobDetalhado());
		String anterior = MDC.get("job_id");
		MDC.put("job_id", "contexto-anterior");
		try {
			this.mvc.perform(renomear("{\"nome\":\"Ok\"}")).andExpect(status().isOk());
			assertThat(MDC.get("job_id")).isEqualTo("contexto-anterior");

			this.mvc.perform(renomear("{\"nome\":\"  \"}")).andExpect(status().isBadRequest());
			assertThat(MDC.get("job_id")).isEqualTo("contexto-anterior");
		}
		finally {
			if (anterior == null) {
				MDC.remove("job_id");
			}
			else {
				MDC.put("job_id", anterior);
			}
		}
	}

	private static MockHttpServletRequestBuilder renomear(String corpo) {
		return put("/jobs/" + JOB + "/nome").contentType(MediaType.APPLICATION_JSON).content(corpo);
	}

	private static JobDetalhadoDto jobDetalhado() {
		return new JobDetalhadoDto(JOB, "arquivado", "formulario", List.of("2025-11"), new BigDecimal("485000.0"), null,
				Instant.parse("2026-09-20T10:00:00Z"), null, null, UUID.randomUUID(), null, null, List.of(), null,
				List.of());
	}

}