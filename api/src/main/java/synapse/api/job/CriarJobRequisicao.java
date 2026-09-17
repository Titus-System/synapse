package synapse.api.job;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;

import tools.jackson.core.JacksonException;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

record CriarJobRequisicao(String origem, List<String> competencias, BigDecimal orcamento, JsonNode conteudo) {

	private static final List<String> COMPETENCIAS = List.of("2025-07", "2025-08", "2025-09", "2025-10", "2025-11",
			"2025-12");

	private static final JsonMapper JSON = JsonMapper.builder()
		.enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS, DeserializationFeature.FAIL_ON_TRAILING_TOKENS)
		.disable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
		.build();

	CriarJobRequisicao {
		if (!"formulario".equals(origem)) {
			throw CriarJobException.requisicao("O campo origem deve ser formulario.");
		}
		if (competencias.isEmpty() || !COMPETENCIAS.containsAll(competencias)) {
			throw CriarJobException.requisicao("Informe competências entre 2025-07 e 2025-12, em uma lista não vazia.");
		}
		if (new HashSet<>(competencias).size() != competencias.size()) {
			throw CriarJobException.requisicao("O campo competencias não permite meses repetidos.");
		}
		competencias = competencias.stream().sorted().toList();
		validarConteudo(conteudo);
		conteudo = conteudo.deepCopy();
	}

	static CriarJobRequisicao deJson(String corpo) {
		JsonNode raiz;
		try {
			raiz = JSON.readTree(corpo);
		}
		catch (JacksonException ex) {
			throw CriarJobException.requisicao("O corpo deve conter um objeto JSON válido.");
		}
		if (raiz == null || !raiz.isObject()) {
			throw CriarJobException.requisicao("O corpo deve conter um objeto JSON válido.");
		}
		if (!raiz.path("origem").isString()) {
			throw CriarJobException.requisicao("O campo origem deve ser formulario.");
		}
		JsonNode orcamento = raiz.path("orcamento");
		if (!orcamento.isNumber()) {
			throw CriarJobException.requisicao("O campo orcamento é obrigatório e precisa ser um número.");
		}
		List<String> competencias = COMPETENCIAS;
		if (raiz.has("competencias")) {
			JsonNode meses = raiz.path("competencias");
			if (!meses.isArray()) {
				throw CriarJobException.requisicao("O campo competencias precisa ser uma lista de meses.");
			}
			competencias = new ArrayList<>();
			for (JsonNode mes : meses) {
				if (!mes.isString()) {
					throw CriarJobException.requisicao("Cada competência precisa ser um mês entre 2025-07 e 2025-12.");
				}
				competencias.add(mes.asString());
			}
		}
		return new CriarJobRequisicao(raiz.path("origem").asString(), competencias, orcamento.decimalValue(),
				raiz.path("conteudo"));
	}

	RepresentacaoRegraDto representacao() {
		NucleoRegraDto nucleo = JSON.treeToValue(conteudo.path("nucleo"), NucleoRegraDto.class);
		return new RepresentacaoRegraDto(nucleo, List.of());
	}

	private static void validarConteudo(JsonNode conteudo) {
		if (!conteudo.isObject()) {
			throw CriarJobException.requisicao("O campo conteudo é obrigatório e precisa ser um objeto.");
		}
		JsonNode nucleo = conteudo.path("nucleo");
		if (!nucleo.isObject()) {
			throw CriarJobException.requisicao("O campo conteudo.nucleo é obrigatório e precisa ser um objeto.");
		}
		List<ElementoErroDto> ausentes = new ArrayList<>();
		for (String campo : List.of("vigencia", "loja", "marca", "cargo", "percentual")) {
			if (nucleo.path(campo).isMissingNode() || nucleo.path(campo).isNull()) {
				ausentes.add(new ElementoErroDto("nucleo." + campo, "Campo obrigatório não informado."));
			}
		}
		if (!ausentes.isEmpty()) {
			throw CriarJobException.nucleoIncompleto(ausentes);
		}
		JsonNode vigencia = nucleo.path("vigencia");
		for (String limite : List.of("inicio", "fim")) {
			JsonNode mes = vigencia.path(limite);
			if (!mes.isString() || !mes.asString().matches("[0-9]{4}-(0[1-9]|1[0-2])")) {
				throw CriarJobException.campoInvalido("vigencia",
						"Informe vigencia." + limite + " no formato AAAA-MM.");
			}
		}
		if (vigencia.path("inicio").asString().compareTo(vigencia.path("fim").asString()) > 0) {
			throw CriarJobException.campoInvalido("vigencia",
					"O início da vigência deve ser anterior ou igual ao fim.");
		}
		for (String campo : List.of("loja", "marca", "cargo")) {
			JsonNode codigos = nucleo.path(campo);
			if (!codigos.isArray()) {
				throw CriarJobException.campoInvalido(campo, "Informe uma lista de códigos.");
			}
			for (JsonNode codigo : codigos) {
				if (!codigo.isString() || codigo.asString().isEmpty()) {
					throw CriarJobException.campoInvalido(campo, "Cada código precisa ser uma string não vazia.");
				}
			}
		}
		if (!nucleo.path("percentual").isNumber()) {
			throw CriarJobException.campoInvalido("percentual", "Informe o percentual como número em fração.");
		}
		JsonNode texto = conteudo.path("texto_livre");
		if (!texto.isNull() && !texto.isString()) {
			throw CriarJobException.requisicao("O campo conteudo.texto_livre é obrigatório e deve ser texto ou null.");
		}
	}
}
