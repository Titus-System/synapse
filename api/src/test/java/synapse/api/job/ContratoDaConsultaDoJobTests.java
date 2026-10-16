package synapse.api.job;

import java.io.IOException;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * Prende o validador de {@code JobDetalhado} usado nos testes de resposta: ele precisa
 * recusar os defeitos que a consulta tinha, senão os testes que dependem dele passariam
 * por qualquer corpo.
 */
class ContratoDaConsultaDoJobTests {

	private static final String REGRA = """
			{"id":"3f2b1c40-0d18-4a51-9f2e-6c1d9a77b021","versao":1,"origem":"confirmacao_usuario",
			 "representacao":{"nucleo":{"vigencia":{"inicio":"2025-11","fim":"2025-11"},"loja":["13"],
			 "marca":["10"],"cargo":["100"],"percentual":0.02},"especificacoes":[]},
			 "criada_em":"2026-01-01T10:01:00Z"}
			""";

	private static String job(String extras) {
		return """
				{"id":"b81e0f4c-52a9-4f0b-8a3d-7c2e5d10ab93","status":"erro","origem":"formulario",
				 "competencias":["2025-11"],"orcamento":485000,"criado_em":"2026-01-01T10:00:00Z",
				 "regras":[%s]%s}
				""".formatted(REGRA, extras);
	}

	private static String simulacao(String campos) {
		return """
				{"id":"c81e0f4c-52a9-4f0b-8a3d-7c2e5d10ab93","regra_id":"3f2b1c40-0d18-4a51-9f2e-6c1d9a77b021",
				 "criado_em":"2026-01-01T10:02:00Z","flag_baixa_rastreabilidade":false%s}
				""".formatted(campos);
	}

	@Test
	void aceitaJobSemOpcionaisEComSimulacaoDeFalhaSemResultado() throws IOException {
		ContratoDeEvento.validarRespostaHttp("JobDetalhado", job(""));
		ContratoDeEvento.validarRespostaHttp("JobDetalhado",
				job(",\"motivo\":\"Falha na execução do código gerado.\",\"iniciado_em\":\"2026-01-01T10:00:01Z\","
						+ "\"finalizado_em\":\"2026-01-01T10:03:00Z\",\"simulacoes\":["
						+ simulacao(",\"status\":\"erro_codigo\"") + "]"));
	}

	@ParameterizedTest
	@ValueSource(strings = { "JobResumo", "JobDetalhado" })
	void aceitaNomeAusenteNuloOuTextual(String schema) throws IOException {
		ContratoDeEvento.validarRespostaHttp(schema, job(""));
		ContratoDeEvento.validarRespostaHttp(schema, job(",\"nome\":null"));
		ContratoDeEvento.validarRespostaHttp(schema, job(",\"nome\":\"Comissão de novembro\""));
	}

	@ParameterizedTest
	@ValueSource(strings = { "JobResumo", "JobDetalhado" })
	void recusaNomeComTipoInvalido(String schema) {
		assertThatThrownBy(() -> ContratoDeEvento.validarRespostaHttp(schema, job(",\"nome\":42")))
			.isInstanceOf(AssertionError.class)
			.hasMessageContaining("nome");
	}

	@ParameterizedTest
	@ValueSource(
			strings = { ",\"iniciado_em\":null", ",\"finalizado_em\":null", ",\"motivo\":null", ",\"simulacao\":null" })
	void recusaOpcionalAusenteSerializadoComoNull(String extra) {
		assertThatThrownBy(() -> ContratoDeEvento.validarRespostaHttp("JobDetalhado", job(extra)))
			.isInstanceOf(AssertionError.class);
	}

	@ParameterizedTest
	@ValueSource(strings = { ",\"status\":null", ",\"status\":\"sucesso\",\"veredito\":null",
			",\"status\":\"sucesso\",\"resultado\":null" })
	void recusaSimulacaoComStatusNuloOuOpcionalNulo(String campos) {
		String corpo = job(",\"simulacoes\":[" + simulacao(campos) + "]");

		assertThatThrownBy(() -> ContratoDeEvento.validarRespostaHttp("JobDetalhado", corpo))
			.isInstanceOf(AssertionError.class);
	}

	@Test
	void recusaSimulacaoSemStatus() {
		String corpo = job(",\"simulacoes\":[" + simulacao("") + "]");

		assertThatThrownBy(() -> ContratoDeEvento.validarRespostaHttp("JobDetalhado", corpo))
			.isInstanceOf(AssertionError.class)
			.satisfies((erro) -> assertThat(erro.getMessage()).contains("status"));
	}

}
