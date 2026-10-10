package synapse.api.job;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;

import com.networknt.schema.InputFormat;
import com.networknt.schema.JsonSchema;
import com.networknt.schema.JsonSchemaFactory;
import com.networknt.schema.SchemaLocation;
import com.networknt.schema.SchemaValidatorsConfig;
import com.networknt.schema.SpecVersion.VersionFlag;
import org.jspecify.annotations.Nullable;
import tools.jackson.core.JacksonException;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

record CriarJobRequisicao(String origem, List<String> competencias, BigDecimal orcamento, JsonNode conteudo) {

	private static final JsonMapper JSON = JsonMapper.builder()
		.enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS, DeserializationFeature.FAIL_ON_TRAILING_TOKENS)
		.disable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
		.build();

	CriarJobRequisicao {
		if (!"formulario".equals(origem)) {
			throw CriarJobException.requisicao("O campo origem deve ser formulario.");
		}
		if (competencias.isEmpty() || !CompetenciasPublicadas.TODAS.containsAll(competencias)) {
			throw CriarJobException.requisicao("Informe competências entre 2025-08 e 2025-12, em uma lista não vazia.");
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
		List<String> competencias = CompetenciasPublicadas.TODAS;
		if (raiz.has("competencias")) {
			JsonNode meses = raiz.path("competencias");
			if (!meses.isArray()) {
				throw CriarJobException.requisicao("O campo competencias precisa ser uma lista de meses.");
			}
			competencias = new ArrayList<>();
			for (JsonNode mes : meses) {
				if (!mes.isString()) {
					throw CriarJobException.requisicao("Cada competência precisa ser um mês entre 2025-08 e 2025-12.");
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

record ListarJobsRequisicao(int pagina, int tamanho) {

	static final int TAMANHO_MAXIMO = 100;

	ListarJobsRequisicao {
		if (pagina < 0) {
			throw ListarJobsException.pagina();
		}
		if (tamanho < 1 || tamanho > TAMANHO_MAXIMO) {
			throw ListarJobsException.tamanho();
		}
	}

	long deslocamento() {
		return (long) this.pagina * this.tamanho;
	}

}

/**
 * Corpo de {@code POST /jobs/{id}/parameters}: a representação confirmada e, opcionais,
 * um orçamento e competências ajustados na mesma tela. Valida o núcleo com o mesmo rigor
 * da criação do job; a verificação de coerência mais profunda da representação é do
 * codegen (T-052).
 */
record ConfirmarParametrosRequisicao(RepresentacaoRegraDto representacao, @Nullable BigDecimal orcamento,
		@Nullable List<String> competencias) {

	private static final List<String> MESES = List.of("2025-08", "2025-09", "2025-10", "2025-11", "2025-12");

	private static final List<String> CAMPOS_NUCLEO = List.of("vigencia", "loja", "marca", "cargo", "percentual");

	private static final JsonSchema ESPECIFICACOES = JsonSchemaFactory
		.getInstance(VersionFlag.V202012,
				builder -> builder.schemaMappers(mappers -> mappers.mapPrefix("https://synapse.local/contracts/domain/",
						"classpath:static/openapi/domain/")))
		.getSchema(SchemaLocation.of("classpath:static/openapi/domain/regra-especificacoes.schema.json"),
				SchemaValidatorsConfig.builder().formatAssertionsEnabled(true).build());

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
				JSON.treeToValue(regra.path("nucleo"), NucleoRegraDto.class),
				regra.path("especificacoes").valueStream().toList());
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
		if (!especificacoes.isArray()
				|| !ESPECIFICACOES.validate(especificacoes.toString(), InputFormat.JSON).isEmpty()) {
			throw ConfirmarParametrosException
				.requisicao("O campo regra.especificacoes deve ser uma lista de elementos válidos da regra.");
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
					.requisicao("Cada competência precisa ser um mês entre 2025-08 e 2025-12.");
			}
			competencias.add(mes.asString());
		}
		if (competencias.isEmpty() || !MESES.containsAll(competencias)) {
			throw ConfirmarParametrosException
				.requisicao("Informe competências entre 2025-08 e 2025-12, em uma lista não vazia.");
		}
		if (new HashSet<>(competencias).size() != competencias.size()) {
			throw ConfirmarParametrosException.requisicao("O campo competencias não permite meses repetidos.");
		}
		return competencias.stream().sorted().toList();
	}

}

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
