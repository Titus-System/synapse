package synapse.api.job;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;

import tools.jackson.databind.JsonNode;

record ParametrosIniciaisJob(BigDecimal orcamento, List<String> competencias) {

	private static final List<String> COMPETENCIAS = List.of("2025-08", "2025-09", "2025-10", "2025-11", "2025-12");

	ParametrosIniciaisJob {
		if (orcamento.signum() < 0) {
			throw new JobsDeSubmissoes.ParametrosInvalidos("O campo orcamento não pode ser negativo.");
		}
		if (competencias.isEmpty() || !COMPETENCIAS.containsAll(competencias)) {
			throw new JobsDeSubmissoes.ParametrosInvalidos(
					"Informe competências entre 2025-08 e 2025-12, em uma lista não vazia.");
		}
		if (new HashSet<>(competencias).size() != competencias.size()) {
			throw new JobsDeSubmissoes.ParametrosInvalidos("O campo competencias não permite meses repetidos.");
		}
		competencias = competencias.stream().sorted().toList();
	}

	static ParametrosIniciaisJob deJson(JsonNode raiz) {
		JsonNode orcamento = raiz.path("orcamento");
		if (!orcamento.isNumber()) {
			throw new JobsDeSubmissoes.ParametrosInvalidos("O campo orcamento é obrigatório e precisa ser um número.");
		}
		List<String> competencias = COMPETENCIAS;
		if (raiz.has("competencias")) {
			JsonNode meses = raiz.path("competencias");
			if (!meses.isArray()) {
				throw new JobsDeSubmissoes.ParametrosInvalidos("O campo competencias precisa ser uma lista de meses.");
			}
			competencias = new ArrayList<>();
			for (JsonNode mes : meses) {
				if (!mes.isString()) {
					throw new JobsDeSubmissoes.ParametrosInvalidos(
							"Cada competência precisa ser um mês entre 2025-08 e 2025-12.");
				}
				competencias.add(mes.asString());
			}
		}
		return new ParametrosIniciaisJob(orcamento.decimalValue(), competencias);
	}
}
