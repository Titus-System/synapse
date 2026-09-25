package synapse.api.job;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;

import org.jspecify.annotations.Nullable;
import tools.jackson.core.JacksonException;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

record ReprocessarJobRequisicao(@Nullable BigDecimal orcamento, @Nullable List<String> competencias) {

	private static final List<String> MESES = List.of("2025-08", "2025-09", "2025-10", "2025-11", "2025-12");

	private static final JsonMapper JSON = JsonMapper.builder()
		.enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS, DeserializationFeature.FAIL_ON_TRAILING_TOKENS)
		.build();

	static ReprocessarJobRequisicao deJson(@Nullable String corpo) {
		if (corpo == null) {
			return new ReprocessarJobRequisicao(null, null);
		}
		JsonNode raiz;
		try {
			raiz = JSON.readTree(corpo);
		}
		catch (JacksonException ex) {
			throw ReprocessarJobException.requisicao("O corpo deve conter um objeto JSON válido.");
		}
		if (raiz == null || !raiz.isObject()) {
			throw ReprocessarJobException.requisicao("O corpo deve conter um objeto JSON válido.");
		}
		return new ReprocessarJobRequisicao(orcamento(raiz.path("orcamento")), competencias(raiz));
	}

	private static @Nullable BigDecimal orcamento(JsonNode orcamento) {
		if (orcamento.isMissingNode() || orcamento.isNull()) {
			return null;
		}
		if (!orcamento.isNumber()) {
			throw ReprocessarJobException.requisicao("O campo orcamento precisa ser um número.");
		}
		return orcamento.decimalValue();
	}

	private static @Nullable List<String> competencias(JsonNode raiz) {
		if (!raiz.has("competencias") || raiz.path("competencias").isNull()) {
			return null;
		}
		JsonNode meses = raiz.path("competencias");
		if (!meses.isArray()) {
			throw ReprocessarJobException.requisicao("O campo competencias precisa ser uma lista de meses.");
		}
		List<String> competencias = new ArrayList<>();
		for (JsonNode mes : meses) {
			if (!mes.isString()) {
				throw ReprocessarJobException
					.requisicao("Cada competência precisa ser um mês entre 2025-08 e 2025-12.");
			}
			competencias.add(mes.asString());
		}
		if (competencias.isEmpty() || !MESES.containsAll(competencias)) {
			throw ReprocessarJobException
				.requisicao("Informe competências entre 2025-08 e 2025-12, em uma lista não vazia.");
		}
		if (new HashSet<>(competencias).size() != competencias.size()) {
			throw ReprocessarJobException.requisicao("O campo competencias não permite meses repetidos.");
		}
		return competencias.stream().sorted().toList();
	}

}
