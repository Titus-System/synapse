package synapse.api.job;

import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.stream.Stream;

import ch.qos.logback.classic.spi.ILoggingEvent;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.Timer;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.EnumSource;
import org.junit.jupiter.params.provider.MethodSource;
import org.slf4j.MDC;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import org.springframework.dao.DataAccessResourceFailureException;

import synapse.api.core.logging.CorrelationContext;
import synapse.api.core.metrics.AppMetrics;
import synapse.api.job.JobEventosService.DesfechoDaExtracao;
import synapse.api.job.JobEventosService.ExtracaoAplicada;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatExceptionOfType;
import static org.mockito.BDDMockito.given;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;

/**
 * O consumidor de {@code regra-extraida} contra um serviço simulado: o desfecho vira uma
 * única amostra da métrica e um log de resultado no envelope compartilhado, a falha
 * transitória sobe para o broker sem contar como desfecho, e a correlação volta ao que
 * era em todos os caminhos.
 */
class RegraExtraidaConsumidorTests {

	private static final UUID JOB_ID = UUID.fromString("c4d5e6f7-8a9b-4c0d-9e1f-2a3b4c5d6e7f");

	private static final UUID SUBMISSAO_ID = UUID.fromString("d7e8f9a0-1b2c-4d3e-8f40-5a6b7c8d9e0f");

	private static final UUID EXTRACAO_ID = UUID.fromString("2d963df3-e310-5d11-bf21-36918cae4ce4");

	private static final UUID REGRA_ID = UUID.fromString("9c7d3e21-4a6b-4c8d-9e0f-1a2b3c4d5e6f");

	private static final JsonMapper JSON = new JsonMapper();

	private final JobEventosService servico = mock(JobEventosService.class);

	private final SimpleMeterRegistry registry = new SimpleMeterRegistry();

	private final RegraExtraidaConsumidor consumidor = new RegraExtraidaConsumidor(this.servico,
			new CorrelationContext(), new AppMetrics(this.registry));

	@AfterEach
	void limparMdc() {
		MDC.clear();
	}

	@Test
	void extracaoPersistidaContaUmaVezELogaInicioEResultadoComReferencias() throws Exception {
		given(this.servico.aplicarRegraExtraida(JOB_ID, SUBMISSAO_ID, EXTRACAO_ID)).willReturn(new ExtracaoAplicada(
				DesfechoDaExtracao.PERSISTIDA, REGRA_ID, new ParametrosGravados(true, true, true)));
		MDC.put("job_id", "contexto-anterior");

		try (CapturaDeLog captura = new CapturaDeLog(RegraExtraidaConsumidor.class)) {
			this.consumidor.receber(new RegraExtraidaDto(JOB_ID, SUBMISSAO_ID, EXTRACAO_ID));

			assertThat(MDC.get("job_id")).isEqualTo("contexto-anterior");
			List<JsonNode> linhas = linhas(captura);
			assertThat(linhas).extracting((linha) -> linha.path("message").asString())
				.containsExactly("consumo de regra-extraida iniciado",
						"regra-extraida persistida; ciclo do codegen reaberto");
			assertThat(linhas).allSatisfy((linha) -> {
				assertThat(linha.path("job_id").asString()).isEqualTo(JOB_ID.toString());
				assertThat(linha.path("service.name").asString()).isEqualTo("synapse-api");
			});
			assertThat(linhas.getFirst().path("extra").path("extracao_id").asString())
				.isEqualTo(EXTRACAO_ID.toString());
			JsonNode resultado = linhas.getLast();
			assertThat(resultado.path("level").asString()).isEqualTo("INFO");
			assertThat(resultado.path("extra").path("resultado").asString()).isEqualTo("persistida");
			assertThat(resultado.path("extra").path("motivo").asString()).isEqualTo("nenhum");
			assertThat(resultado.path("extra").path("regra_id").asString()).isEqualTo(REGRA_ID.toString());
			assertThat(resultado.path("extra").path("orcamento_extraido").asBoolean()).isTrue();
			assertThat(resultado.path("extra").path("meta_venda_extraida").asBoolean()).isTrue();
			assertThat(resultado.path("extra").path("periodo_extraido").asBoolean()).isTrue();
		}

		assertThat(contagem("persistida", "nenhum")).isEqualTo(1.0);
		assertThat(this.registry.get("regra.extraida.consumo").counters()).hasSize(1);
		assertThat(duracao("persistida").count()).isEqualTo(1);
		assertThat(parametrosGravados("orcamento")).isEqualTo(1.0);
		assertThat(parametrosGravados("meta_venda")).isEqualTo(1.0);
		assertThat(parametrosGravados("competencias")).isEqualTo(1.0);
	}

	/**
	 * O texto que não disse parâmetro algum: o log diz que nenhum veio, em vez de omitir
	 * a informação, e a métrica por parâmetro não registra nada.
	 */
	@Test
	void extracaoSemParametrosLogaAsTresAusenciasESemContarParametro() throws Exception {
		given(this.servico.aplicarRegraExtraida(JOB_ID, SUBMISSAO_ID, EXTRACAO_ID))
			.willReturn(new ExtracaoAplicada(DesfechoDaExtracao.PERSISTIDA, REGRA_ID, ParametrosGravados.NENHUM));

		try (CapturaDeLog captura = new CapturaDeLog(RegraExtraidaConsumidor.class)) {
			this.consumidor.receber(new RegraExtraidaDto(JOB_ID, SUBMISSAO_ID, EXTRACAO_ID));

			JsonNode resultado = linhas(captura).getLast();
			assertThat(resultado.path("extra").path("orcamento_extraido").asBoolean()).isFalse();
			assertThat(resultado.path("extra").path("meta_venda_extraida").asBoolean()).isFalse();
			assertThat(resultado.path("extra").path("periodo_extraido").asBoolean()).isFalse();
		}

		assertThat(contagem("persistida", "nenhum")).isEqualTo(1.0);
		assertThat(this.registry.find("job.parametros.gravados").counters()).isEmpty();
	}

	/**
	 * Um parâmetro extraído conta uma vez por gravação, e a reentrega não regrava: sem
	 * isto, a métrica diria que dois jobs receberam orçamento onde um recebeu.
	 */
	@Test
	void reentregaNaoContaParametroDeNovo() throws Exception {
		given(this.servico.aplicarRegraExtraida(JOB_ID, SUBMISSAO_ID, EXTRACAO_ID))
			.willReturn(new ExtracaoAplicada(DesfechoDaExtracao.PERSISTIDA, REGRA_ID,
					new ParametrosGravados(true, false, false)))
			.willReturn(new ExtracaoAplicada(DesfechoDaExtracao.REENTREGA, REGRA_ID, ParametrosGravados.NENHUM));

		this.consumidor.receber(new RegraExtraidaDto(JOB_ID, SUBMISSAO_ID, EXTRACAO_ID));
		this.consumidor.receber(new RegraExtraidaDto(JOB_ID, SUBMISSAO_ID, EXTRACAO_ID));

		assertThat(parametrosGravados("orcamento")).isEqualTo(1.0);
		assertThat(this.registry.find("job.parametros.gravados").counters()).hasSize(1);
	}

	@Test
	void reentregaContaComoDuplicadaENuncaComoOutraPersistida() throws Exception {
		given(this.servico.aplicarRegraExtraida(JOB_ID, SUBMISSAO_ID, EXTRACAO_ID))
			.willReturn(new ExtracaoAplicada(DesfechoDaExtracao.PERSISTIDA, REGRA_ID, ParametrosGravados.NENHUM))
			.willReturn(new ExtracaoAplicada(DesfechoDaExtracao.REENTREGA, REGRA_ID, ParametrosGravados.NENHUM));

		try (CapturaDeLog captura = new CapturaDeLog(RegraExtraidaConsumidor.class)) {
			this.consumidor.receber(new RegraExtraidaDto(JOB_ID, SUBMISSAO_ID, EXTRACAO_ID));
			this.consumidor.receber(new RegraExtraidaDto(JOB_ID, SUBMISSAO_ID, EXTRACAO_ID));

			JsonNode ultimo = linhas(captura).getLast();
			assertThat(ultimo.path("level").asString()).isEqualTo("INFO");
			assertThat(ultimo.path("extra").path("resultado").asString()).isEqualTo("duplicada");
			assertThat(ultimo.path("extra").path("motivo").asString()).isEqualTo("reentrega");
			assertThat(ultimo.path("extra").path("regra_id").asString()).isEqualTo(REGRA_ID.toString());
		}

		assertThat(contagem("persistida", "nenhum")).isEqualTo(1.0);
		assertThat(contagem("duplicada", "reentrega")).isEqualTo(1.0);
	}

	@ParameterizedTest
	@EnumSource(value = DesfechoDaExtracao.class, mode = EnumSource.Mode.EXCLUDE,
			names = { "PERSISTIDA", "REENTREGA", "EVENTO_INVALIDO" })
	void descarteDoServicoSaiEmWarnComMotivoESemRegra(DesfechoDaExtracao desfecho) throws Exception {
		given(this.servico.aplicarRegraExtraida(JOB_ID, SUBMISSAO_ID, EXTRACAO_ID))
			.willReturn(ExtracaoAplicada.descartada(desfecho));

		try (CapturaDeLog captura = new CapturaDeLog(RegraExtraidaConsumidor.class)) {
			this.consumidor.receber(new RegraExtraidaDto(JOB_ID, SUBMISSAO_ID, EXTRACAO_ID));

			JsonNode resultado = linhas(captura).getLast();
			assertThat(resultado.path("level").asString()).isEqualTo("WARN");
			assertThat(resultado.path("message").asString())
				.isEqualTo("regra-extraida descartada; job sem nova versão");
			assertThat(resultado.path("extra").path("resultado").asString()).isEqualTo("descartada");
			assertThat(resultado.path("extra").path("motivo").asString()).isEqualTo(desfecho.motivo());
			assertThat(resultado.path("extra").has("regra_id")).isFalse();
		}

		assertThat(contagem("descartada", desfecho.motivo())).isEqualTo(1.0);
		assertThat(duracao("descartada").count()).isEqualTo(1);
	}

	@ParameterizedTest
	@MethodSource("eventosIncompletos")
	void eventoSemReferenciaObrigatoriaEDescartadoSemChamarOServico(RegraExtraidaDto evento) throws Exception {
		try (CapturaDeLog captura = new CapturaDeLog(RegraExtraidaConsumidor.class)) {
			this.consumidor.receber(evento);

			JsonNode resultado = linhas(captura).getLast();
			assertThat(resultado.path("level").asString()).isEqualTo("WARN");
			assertThat(resultado.path("extra").path("motivo").asString()).isEqualTo("evento_invalido");
		}

		verifyNoInteractions(this.servico);
		assertThat(contagem("descartada", "evento_invalido")).isEqualTo(1.0);
		assertThat(MDC.get("job_id")).isNull();
	}

	static Stream<RegraExtraidaDto> eventosIncompletos() {
		return Stream.of(new RegraExtraidaDto(null, SUBMISSAO_ID, EXTRACAO_ID),
				new RegraExtraidaDto(JOB_ID, null, EXTRACAO_ID), new RegraExtraidaDto(JOB_ID, SUBMISSAO_ID, null),
				// Pelo JSON, porque é como o campo ausente chega de verdade.
				JSON.readValue("""
						{"job_id":"%s","submissao_id":"%s"}
						""".formatted(JOB_ID, SUBMISSAO_ID), RegraExtraidaDto.class));
	}

	@Test
	void falhaDeBancoSobeParaOBrokerSemContarComoDesfechoERestauraACorrelacao() throws Exception {
		given(this.servico.aplicarRegraExtraida(JOB_ID, SUBMISSAO_ID, EXTRACAO_ID))
			.willThrow(new DataAccessResourceFailureException("conexão recusada para jdbc:postgresql://segredo"));
		MDC.put("job_id", "contexto-anterior");

		try (CapturaDeLog captura = new CapturaDeLog(RegraExtraidaConsumidor.class)) {
			assertThatExceptionOfType(DataAccessResourceFailureException.class)
				.isThrownBy(() -> this.consumidor.receber(new RegraExtraidaDto(JOB_ID, SUBMISSAO_ID, EXTRACAO_ID)));

			assertThat(MDC.get("job_id")).isEqualTo("contexto-anterior");
			JsonNode falha = linhas(captura).getLast();
			assertThat(falha.path("level").asString()).isEqualTo("WARN");
			assertThat(falha.path("job_id").asString()).isEqualTo(JOB_ID.toString());
			assertThat(falha.path("extra").path("classe_falha").asString())
				.isEqualTo("DataAccessResourceFailureException");
			assertThat(falha.toString()).doesNotContain("segredo", "jdbc:");
		}

		assertThat(this.registry.find("regra.extraida.consumo").counters()).isEmpty();
		assertThat(duracao("falha").count()).isEqualTo(1);
	}

	private List<JsonNode> linhas(CapturaDeLog captura) throws Exception {
		List<JsonNode> linhas = new ArrayList<>();
		for (ILoggingEvent evento : captura.eventos()) {
			String linha = CapturaDeLog.emJson(evento);
			ContratoDeEvento.validarLog(linha);
			linhas.add(JSON.readTree(linha));
		}
		return linhas;
	}

	private double contagem(String resultado, String motivo) {
		Counter contador = this.registry.find("regra.extraida.consumo")
			.tag("resultado", resultado)
			.tag("motivo", motivo)
			.counter();
		return (contador != null) ? contador.count() : 0;
	}

	private Timer duracao(String resultado) {
		return this.registry.get("regra.extraida.consumo.duracao").tag("resultado", resultado).timer();
	}

	private double parametrosGravados(String parametro) {
		Counter contador = this.registry.find("job.parametros.gravados").tag("parametro", parametro).counter();
		return (contador != null) ? contador.count() : 0;
	}

}
