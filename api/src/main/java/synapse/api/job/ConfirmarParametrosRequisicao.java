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

/**
 * Corpo de {@code POST /jobs/{id}/parameters}: a representação confirmada e, opcionais,
 * um orçamento e competências ajustados na mesma tela. Valida o núcleo com o mesmo rigor
 * da criação do job; a verificação de coerência mais profunda da representação é do
 * codegen (T-052).
 */
record ConfirmarParametrosRequisicao(RepresentacaoRegraDto representacao, @Nullable BigDecimal orcamento,
		@Nullable List<String> competencias) {

	private static final List<String> MESES = List.of("2025-07", "2025-08", "2025-09", "2025-10", "2025-11", "2025-12");

	private static final List<String> CAMPOS_NUCLEO = List.of("vigencia", "loja", "marca", "cargo", "percentual");

	private static final JsonMapper JSON = JsonMapper.builder()
		.enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS, DeserializationFeature.FAIL_ON_TRAILING_TOKENS)
		.disable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
		.build();

	static ConfirmarParametrosRequisicao deJson(String corpo) {
		JsonNode raiz;
		try {
			raiz = JSON.readTree(corpo);
		}
		catch (JacksonException ex) {
			throw ConfirmarParametrosException.requisicao("O corpo deve conter um objeto JSON válido.");
		}
		if (raiz == null || !raiz.isObject()) {
			throw ConfirmarParametrosException.requisicao("O corpo deve conter um objeto JSON válido.");
		}
		JsonNode regra = raiz.path("regra");
		if (!regra.isObject()) {
			throw ConfirmarParametrosException.requisicao("O campo regra é obrigatório e precisa ser um objeto.");
		}
		validarNucleo(regra.path("nucleo"));
		validarEspecificacoes(regra.path("especificacoes"));
		RepresentacaoRegraDto representacao = new RepresentacaoRegraDto(
				JSON.treeToValue(regra.path("nucleo"), NucleoRegraDto.class), List.of());
		return new ConfirmarParametrosRequisicao(representacao, orcamento(raiz.path("orcamento")), competencias(raiz));
	}

	private static void validarNucleo(JsonNode nucleo) {
		if (!nucleo.isObject()) {
			throw ConfirmarParametrosException
				.requisicao("O campo regra.nucleo é obrigatório e precisa ser um objeto.");
		}
		List<ElementoErroDto> ausentes = new ArrayList<>();
		for (String campo : CAMPOS_NUCLEO) {
			if (nucleo.path(campo).isMissingNode() || nucleo.path(campo).isNull()) {
				ausentes.add(new ElementoErroDto("nucleo." + campo, "Campo obrigatório não informado."));
			}
		}
		if (!ausentes.isEmpty()) {
			throw ConfirmarParametrosException.nucleoIncompleto(ausentes);
		}
		JsonNode vigencia = nucleo.path("vigencia");
		for (String limite : List.of("inicio", "fim")) {
			JsonNode mes = vigencia.path(limite);
			if (!mes.isString() || !mes.asString().matches("[0-9]{4}-(0[1-9]|1[0-2])")) {
				throw ConfirmarParametrosException.campoInvalido("vigencia",
						"Informe vigencia." + limite + " no formato AAAA-MM.");
			}
		}
		if (vigencia.path("inicio").asString().compareTo(vigencia.path("fim").asString()) > 0) {
			throw ConfirmarParametrosException.campoInvalido("vigencia",
					"O início da vigência deve ser anterior ou igual ao fim.");
		}
		for (String campo : List.of("loja", "marca", "cargo")) {
			JsonNode codigos = nucleo.path(campo);
			if (!codigos.isArray()) {
				throw ConfirmarParametrosException.campoInvalido(campo, "Informe uma lista de códigos.");
			}
			for (JsonNode codigo : codigos) {
				if (!codigo.isString() || codigo.asString().isEmpty()) {
					throw ConfirmarParametrosException.campoInvalido(campo,
							"Cada código precisa ser uma string não vazia.");
				}
			}
		}
		if (!nucleo.path("percentual").isNumber()) {
			throw ConfirmarParametrosException.campoInvalido("percentual",
					"Informe o percentual como número em fração.");
		}
	}

	private static void validarEspecificacoes(JsonNode especificacoes) {
		if (especificacoes.isMissingNode() || especificacoes.isNull()) {
			return;
		}
		if (!especificacoes.isArray() || !especificacoes.isEmpty()) {
			throw ConfirmarParametrosException
				.requisicao("Na Sprint 1, regra.especificacoes deve ser uma lista vazia.");
		}
	}

	private static @Nullable BigDecimal orcamento(JsonNode orcamento) {
		if (orcamento.isMissingNode() || orcamento.isNull()) {
			return null;
		}
		if (!orcamento.isNumber()) {
			throw ConfirmarParametrosException.requisicao("O campo orcamento precisa ser um número.");
		}
		return orcamento.decimalValue();
	}

	private static @Nullable List<String> competencias(JsonNode raiz) {
		if (!raiz.has("competencias") || raiz.path("competencias").isNull()) {
			return null;
		}
		JsonNode meses = raiz.path("competencias");
		if (!meses.isArray()) {
			throw ConfirmarParametrosException.requisicao("O campo competencias precisa ser uma lista de meses.");
		}
		List<String> competencias = new ArrayList<>();
		for (JsonNode mes : meses) {
			if (!mes.isString()) {
				throw ConfirmarParametrosException
					.requisicao("Cada competência precisa ser um mês entre 2025-07 e 2025-12.");
			}
			competencias.add(mes.asString());
		}
		if (competencias.isEmpty() || !MESES.containsAll(competencias)) {
			throw ConfirmarParametrosException
				.requisicao("Informe competências entre 2025-07 e 2025-12, em uma lista não vazia.");
		}
		if (new HashSet<>(competencias).size() != competencias.size()) {
			throw ConfirmarParametrosException.requisicao("O campo competencias não permite meses repetidos.");
		}
		return competencias.stream().sorted().toList();
	}

}
