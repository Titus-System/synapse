package synapse.api.submissoes;

import tools.jackson.core.JacksonException;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

record EntradaSubmissao(String texto) {

	private static final JsonMapper JSON = JsonMapper.builder()
		.enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS, DeserializationFeature.FAIL_ON_TRAILING_TOKENS)
		.build();

	static EntradaSubmissao ler(String corpo, String tipo) {
		JsonNode raiz;
		try {
			raiz = JSON.readTree(corpo);
		}
		catch (JacksonException ex) {
			throw SubmissaoException.requisicao("O corpo deve conter um objeto JSON válido.");
		}
		if (raiz == null || !raiz.isObject() || !"entrada_inicial".equals(raiz.path("finalidade").asString())
				|| !tipo.equals(raiz.path("tipo").asString())) {
			throw SubmissaoException.requisicao("Informe finalidade e tipo compatíveis com a entrada inicial.");
		}
		String texto = "";
		if ("texto".equals(tipo)) {
			JsonNode valor = raiz.path("texto");
			if (!valor.isString() || valor.asString()
				.codePoints()
				.allMatch(c -> Character.isWhitespace(c) || Character.isSpaceChar(c))) {
				throw SubmissaoException.requisicao("Escreva a descrição da regra antes de enviar.");
			}
			texto = valor.asString();
			if (texto.codePointCount(0, texto.length()) > 8000) {
				throw SubmissaoException.requisicao("A descrição da regra pode ter no máximo 8000 caracteres.");
			}
		}
		return new EntradaSubmissao(texto);
	}
}
