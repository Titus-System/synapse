package synapse.api.job;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * Protege o validador que {@code SubmissaoDeRegraFimAFimTests} usa para conferir cada
 * evento do stream. Um validador que aceitasse tudo deixaria aquele teste passar no
 * vácuo, e os dois casos recusados aqui são justamente os que provam que os {@code $ref}
 * foram resolvidos: o externo, para o vocabulário fechado de {@code contracts/domain/}, e
 * o interno, para os enums declarados no próprio openapi.
 * <p>
 * {@code format: uuid} não entra: no JSON Schema 2020-12 ele é anotação, não asserção.
 * Para estes payloads isso não abre lacuna, porque os campos de identificador são
 * {@code UUID} nos DTOs da api - um valor malformado não tem como ser produzido.
 */
class ContratoDoStreamTests {

	private static final String JOB = "3f2b1c40-0d18-4a51-9f2e-6c1d9a77b021";

	@Test
	void aceitaOsTresEventosNaFormaPublicada() {
		assertThatCode(() -> {
			ContratoDeEvento.validarEventoDoStream("etapa",
					"{\"job_id\":\"%s\",\"etapa\":\"delegacao_worker\",\"status\":\"iniciada\"}".formatted(JOB));
			ContratoDeEvento.validarEventoDoStream("estado",
					"{\"job_id\":\"%s\",\"status\":\"simulando\",\"status_anterior\":\"gerando_regra\"}"
						.formatted(JOB));
			ContratoDeEvento.validarEventoDoStream("resultado",
					"{\"job_id\":\"%s\",\"simulacao_id\":\"%s\",\"status\":\"sucesso\",\"veredito\":\"inviavel\"}"
						.formatted(JOB, JOB));
		}).doesNotThrowAnyException();
	}

	@Test
	void recusaEtapaForaDoVocabularioDosNos() {
		assertThatThrownBy(() -> ContratoDeEvento.validarEventoDoStream("etapa",
				"{\"job_id\":\"%s\",\"etapa\":\"inventada\",\"status\":\"iniciada\"}".formatted(JOB)))
			.isInstanceOf(AssertionError.class);
	}

	@Test
	void recusaStatusDeJobForaDoEnum() {
		assertThatThrownBy(() -> ContratoDeEvento.validarEventoDoStream("estado",
				"{\"job_id\":\"%s\",\"status\":\"voando\"}".formatted(JOB)))
			.isInstanceOf(AssertionError.class);
	}

	@Test
	void recusaEventoSemCampoObrigatorio() {
		assertThatThrownBy(() -> ContratoDeEvento.validarEventoDoStream("resultado",
				"{\"job_id\":\"%s\",\"status\":\"sucesso\"}".formatted(JOB)))
			.isInstanceOf(AssertionError.class);
	}

	@Test
	void recusaNomeDeEventoSemSchemaNoContrato() {
		assertThatThrownBy(() -> ContratoDeEvento.validarEventoDoStream("inexistente", "{}"))
			.isInstanceOf(AssertionError.class);
	}

}
