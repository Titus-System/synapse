package synapse.api.submissoes;

import java.util.UUID;

import org.jspecify.annotations.Nullable;
import tools.jackson.core.JacksonException;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

record EntradaSubmissao(String texto, @Nullable UUID jobId) {

	private static final JsonMapper JSON = JsonMapper.builder()
		.enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS, DeserializationFeature.FAIL_ON_TRAILING_TOKENS)
		.build();

	static EntradaSubmissao ler(String corpo, String tipo) {
		return ler(analisar(corpo), tipo);
	}

	static JsonNode analisar(String corpo) {
		JsonNode raiz;
		try {
			raiz = JSON.readTree(corpo);
		}
		catch (JacksonException ex) {
			throw SubmissaoException.requisicao("O corpo deve conter um objeto JSON válido.");
		}
		if (raiz == null || !raiz.isObject()) {
			throw SubmissaoException.requisicao("O corpo deve conter um objeto JSON válido.");
		}
		return raiz;
	}

	static @Nullable UUID jobDaCorrecao(JsonNode raiz) {
		if (!"correcao".equals(raiz.path("finalidade").asString())) {
			return null;
		}
		JsonNode campo = raiz.path("job_id");
		if (!campo.isString()) {
			throw SubmissaoException.requisicao("Informe um job_id válido para a correção.");
		}
		String valor = campo.asString();
		try {
			UUID id = UUID.fromString(valor);
			if (!id.toString().equalsIgnoreCase(valor)) {
				throw new IllegalArgumentException();
			}
			return id;
		}
		catch (IllegalArgumentException ex) {
			throw SubmissaoException.requisicao("Informe um job_id válido para a correção.");
		}
	}

	static EntradaSubmissao ler(JsonNode raiz, String tipo) {
		boolean correcao = "correcao".equals(raiz.path("finalidade").asString());
		if ((!"entrada_inicial".equals(raiz.path("finalidade").asString()) && !correcao)
				|| !tipo.equals(raiz.path("tipo").asString()) || (correcao && !"texto".equals(tipo))) {
			throw SubmissaoException.requisicao("Informe finalidade e tipo compatíveis com a submissão.");
		}
		String texto = "";
		if ("texto".equals(tipo)) {
			JsonNode valor = raiz.path("texto");
			if (!valor.isString() || semConteudo(valor.asString())) {
				throw SubmissaoException.requisicao("Escreva a descrição da regra antes de enviar.");
			}
			texto = valor.asString();
			if (texto.codePointCount(0, texto.length()) > (correcao ? 4000 : 8000)) {
				throw SubmissaoException.requisicao(correcao ? "A correção pode ter no máximo 4000 caracteres."
						: "A descrição da regra pode ter no máximo 8000 caracteres.");
			}
		}
		return new EntradaSubmissao(texto, jobDaCorrecao(raiz));
	}

	/**
	 * Vale para o texto digitado e para o transcrito: {@code isBlank} não cobre o espaço
	 * ideográfico nem o NBSP, que um teclado e um provedor de ASR produzem. Uma gravação
	 * sem fala não pode chegar à extração como uma regra vazia.
	 */
	static boolean semConteudo(String texto) {
		return texto.codePoints().allMatch(c -> Character.isWhitespace(c) || Character.isSpaceChar(c));
	}
}
