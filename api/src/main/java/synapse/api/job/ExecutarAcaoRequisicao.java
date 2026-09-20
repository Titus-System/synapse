package synapse.api.job;

import tools.jackson.core.JacksonException;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

record ExecutarAcaoRequisicao(AcaoJob acao) {

	private static final JsonMapper JSON = JsonMapper.builder()
		.enable(DeserializationFeature.FAIL_ON_TRAILING_TOKENS)
		.disable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
		.build();

	static ExecutarAcaoRequisicao deJson(String corpo) {
		JsonNode raiz;
		try {
			raiz = JSON.readTree(corpo);
		}
		catch (JacksonException ex) {
			throw ExecutarAcaoException.requisicao("O corpo deve conter um objeto JSON válido.");
		}
		if (raiz == null || !raiz.isObject() || !raiz.path("acao").isString()) {
			throw ExecutarAcaoException
				.requisicao("O campo acao é obrigatório e deve ser confirmar_liberar, cancelar, salvar ou arquivar.");
		}
		AcaoJob acao;
		try {
			acao = AcaoJob.deColuna(raiz.path("acao").asString());
		}
		catch (IllegalArgumentException ex) {
			throw ExecutarAcaoException
				.requisicao("O campo acao deve ser confirmar_liberar, cancelar, salvar ou arquivar.");
		}
		return new ExecutarAcaoRequisicao(acao);
	}

}
