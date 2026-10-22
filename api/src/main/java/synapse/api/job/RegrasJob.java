package synapse.api.job;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HexFormat;
import java.util.List;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;
import java.util.function.IntFunction;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.networknt.schema.InputFormat;
import com.networknt.schema.JsonSchema;
import com.networknt.schema.JsonSchemaFactory;
import com.networknt.schema.SchemaLocation;
import com.networknt.schema.SchemaValidatorsConfig;
import com.networknt.schema.SpecVersion.VersionFlag;
import org.jspecify.annotations.Nullable;
import tools.jackson.core.StreamWriteFeature;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.MapperFeature;
import tools.jackson.databind.cfg.JsonNodeFeature;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;

import org.springframework.stereotype.Component;

final class HashDaRegra {

	private static final JsonMapper JSON = JsonMapper.builder()
		.enable(MapperFeature.SORT_PROPERTIES_ALPHABETICALLY)
		.disable(MapperFeature.SORT_CREATOR_PROPERTIES_FIRST)
		.enable(StreamWriteFeature.WRITE_BIGDECIMAL_AS_PLAIN)
		.enable(JsonNodeFeature.WRITE_PROPERTIES_SORTED)
		.build();

	private HashDaRegra() {
	}

	/**
	 * O hash de uma versão sem parâmetros - formulário, reprocessamento, sugestão de
	 * adaptação e toda versão anterior à coluna {@code regras.parametros}. A serialização
	 * é a de antes da coluna, e por isso o hash dessas versões não muda: é o que mantém o
	 * índice único {@code (job_id, hash)} reconhecendo as versões já gravadas.
	 */
	static String calcular(RepresentacaoRegraDto regra) {
		return calcular(regra, null);
	}

	/**
	 * A extração pode chegar sem {@code percentual}: o núcleo não exige campo algum, e a
	 * falta é apontada pela validação de domínio do ciclo seguinte, não aqui.
	 * <p>
	 * Com {@code parametros} presente, inclusive vazio, eles entram na serialização
	 * canônica. É o que faz uma correção que muda só o orçamento, a meta ou o período
	 * gerar versão nova em vez de reencontrar a anterior por
	 * {@link VersoesDaRegra#resolver}.
	 */
	static String calcular(RepresentacaoRegraDto regra, @Nullable ParametrosDaSimulacao parametros) {
		NucleoRegraDto nucleo = regra.nucleo();
		NucleoRegraDto canonico = new NucleoRegraDto(nucleo.vigencia(), nucleo.loja(), nucleo.marca(), nucleo.cargo(),
				semZerosAtras(nucleo.percentual()), taxasCanonicas(nucleo.taxas_por_cargo()));
		byte[] json = JSON
			.writeValueAsString(new RegraCanonica(regra.especificacoes(), canonico, canonicos(parametros)))
			.getBytes(StandardCharsets.UTF_8);
		try {
			return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(json));
		}
		catch (NoSuchAlgorithmException ex) {
			throw new IllegalStateException("SHA-256 indisponível.", ex);
		}
	}

	private static @Nullable List<TaxaPorCargoDto> taxasCanonicas(@Nullable List<TaxaPorCargoDto> taxas) {
		return taxas == null ? null
				: taxas.stream()
					.map(taxa -> new TaxaPorCargoDto(taxa.cargo(), taxa.percentual().stripTrailingZeros()))
					.toList();
	}

	/**
	 * O período entra no hash na mesma forma canônica da coluna {@code jobs.competencias}
	 * - ordem crescente, sem repetição -, pelo mesmo motivo do valor monetário: ordem e
	 * repetição são forma, não valor, e duas correções que disserem o mesmo período em
	 * ordem diferente precisam reconhecer a mesma versão, não criar uma nova.
	 */
	private static @Nullable ParametrosDaSimulacao canonicos(@Nullable ParametrosDaSimulacao parametros) {
		if (parametros == null) {
			return null;
		}
		return new ParametrosDaSimulacao(semZerosAtras(parametros.orcamento()), semZerosAtras(parametros.meta_venda()),
				parametros.periodoCanonico());
	}

	/**
	 * Dois valores monetários que só diferem em zeros à direita são o mesmo valor, e
	 * {@code 500000.00} precisa dar o mesmo hash que {@code 500000}.
	 */
	private static @Nullable BigDecimal semZerosAtras(@Nullable BigDecimal valor) {
		return (valor != null) ? valor.stripTrailingZeros() : null;
	}

}

/**
 * A procedência do conteúdo de uma sugestão de adaptação: a proposta é a versão de origem
 * com as taxas reduzidas e nada mais alterado. Taxa é o percentual do núcleo, cada taxa
 * por cargo e o efeito percentual de faixas e janelas de datas - o mesmo recorte que o
 * codegen reduz na mesma proporção. Valores em reais, limiares, exclusões e texto livre
 * ficam como estavam.
 */
final class ReducaoDasTaxas {

	private static final JsonMapper JSON = new JsonMapper();

	private static final Set<String> CONSTRUTOS_COM_TAXA = Set.of("faixa_valor", "janela_datas");

	private static final Set<String> EFEITOS_PERCENTUAIS = Set.of("acrescimo_pct", "substituicao_pct");

	// O mesmo número chega como inteiro, double ou decimal, conforme quem o leu.
	private static final Comparator<JsonNode> NUMEROS_POR_VALOR = (a, b) -> {
		if (a.isNumber() && b.isNumber()) {
			return a.decimalValue().compareTo(b.decimalValue());
		}
		return a.equals(b) ? 0 : 1;
	};

	private ReducaoDasTaxas() {
	}

	/**
	 * Taxa zero continua zero; as demais mantêm o sinal e diminuem em módulo, e pelo
	 * menos uma precisa ter mudado.
	 */
	static boolean reduzSoAsTaxas(RepresentacaoRegraDto origem, RepresentacaoRegraDto proposta) {
		if (!semTaxas(origem).equals(NUMEROS_POR_VALOR, semTaxas(proposta))) {
			return false;
		}
		List<BigDecimal> deOrigem = taxas(origem);
		List<BigDecimal> propostas = taxas(proposta);
		if (deOrigem.size() != propostas.size()) {
			return false;
		}
		boolean mudou = false;
		for (int i = 0; i < deOrigem.size(); i++) {
			BigDecimal anterior = deOrigem.get(i);
			BigDecimal nova = propostas.get(i);
			if (!reduzida(anterior, nova)) {
				return false;
			}
			mudou |= anterior.compareTo(nova) != 0;
		}
		return mudou;
	}

	private static boolean reduzida(BigDecimal anterior, BigDecimal nova) {
		if (anterior.signum() == 0) {
			return nova.signum() == 0;
		}
		return nova.signum() == anterior.signum() && nova.abs().compareTo(anterior.abs()) < 0;
	}

	private static List<BigDecimal> taxas(RepresentacaoRegraDto regra) {
		List<BigDecimal> taxas = new ArrayList<>();
		BigDecimal percentual = regra.nucleo().percentual();
		if (percentual != null) {
			taxas.add(percentual);
		}
		List<TaxaPorCargoDto> porCargo = regra.nucleo().taxas_por_cargo();
		if (porCargo != null) {
			porCargo.forEach((taxa) -> taxas.add(taxa.percentual()));
		}
		for (JsonNode elemento : regra.especificacoes()) {
			if (temTaxa(elemento)) {
				taxas.add(elemento.path("efeito").path("valor").decimalValue());
			}
		}
		return taxas;
	}

	private static JsonNode semTaxas(RepresentacaoRegraDto regra) {
		JsonNode arvore = JSON.valueToTree(regra);
		if (arvore.path("nucleo") instanceof ObjectNode nucleo) {
			nucleo.remove("percentual");
			for (JsonNode taxa : nucleo.path("taxas_por_cargo")) {
				if (taxa instanceof ObjectNode objeto) {
					objeto.remove("percentual");
				}
			}
		}
		for (JsonNode elemento : arvore.path("especificacoes")) {
			if (temTaxa(elemento) && elemento.path("efeito") instanceof ObjectNode efeito) {
				efeito.remove("valor");
			}
		}
		return arvore;
	}

	private static boolean temTaxa(JsonNode elemento) {
		JsonNode construto = elemento.path("construto");
		JsonNode efeito = elemento.path("efeito");
		JsonNode tipo = efeito.path("tipo");
		return construto.isString() && CONSTRUTOS_COM_TAXA.contains(construto.stringValue()) && tipo.isString()
				&& EFEITOS_PERCENTUAIS.contains(tipo.stringValue()) && efeito.path("valor").isNumber();
	}

}

/**
 * A forma serializada para o hash. Os componentes saem em ordem alfabética (ver o
 * {@code JsonMapper} de {@link HashDaRegra}) e {@code parametros} nulo sai ausente, de
 * modo que uma versão sem parâmetros produz exatamente os bytes de antes de a coluna
 * existir.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
record RegraCanonica(List<JsonNode> especificacoes, NucleoRegraDto nucleo, @Nullable ParametrosDaSimulacao parametros) {
}

/**
 * Resolve a versão de {@code regras} de um job: reaproveita a linha de mesmo hash ou
 * insere a próxima. Único lugar que escreve na tabela, para que a regra de deduplicação e
 * a numeração da versão não se repitam por caminho de entrada - hoje a confirmação do
 * usuário, a sugestão de adaptação e a extração do codegen, que só diferem em
 * {@code origem}, na versão de que derivam e em de onde vem a representação.
 *
 * <p>
 * A deduplicação por {@code (job_id, hash)} é o que faz reenviar a mesma representação
 * não criar versão nova: é ela que sustenta o índice único da migration {@code 006} e o
 * caminho em que o usuário confirma sem ter editado nada.
 */
@Component
class VersoesDaRegra {

	static final String ORIGEM_EXTRACAO = "extracao";

	static final String ORIGEM_SUGESTAO = "sugestao_adaptacao";

	private final JobRepository repository;

	VersoesDaRegra(JobRepository repository) {
		this.repository = repository;
	}

	/**
	 * {@code parametrosJson} é o artefato bruto a carregar para a versão nova, exatamente
	 * como estava na versão de origem - nunca reserializado a partir do
	 * {@link ParametrosDaSimulacao} com que {@code hash} foi calculado, para a coluna e o
	 * hash nunca discordarem do que a versão de origem tinha.
	 */
	VersaoRegra resolver(UUID jobId, RepresentacaoRegraDto representacao, @Nullable String parametrosJson, String hash,
			String origem, @Nullable UUID origemId, Timestamp timestamp, Instant agora) {
		return resolver(jobId, hash, origem, agora, (novaVersao) -> this.repository.inserirVersaoRegra(jobId,
				novaVersao, origem, origemId, representacao, parametrosJson, hash, null, timestamp));
	}

	/**
	 * A versão de uma sugestão de taxa nova, com a {@code tentativa} que o codegen
	 * informou - nula nas propostas anteriores ao campo.
	 */
	VersaoRegra resolverSugestao(UUID jobId, RepresentacaoRegraDto representacao, @Nullable String parametrosJson,
			String hash, UUID origemId, @Nullable Integer tentativa, Timestamp timestamp, Instant agora) {
		return resolver(jobId, hash, ORIGEM_SUGESTAO, agora, (novaVersao) -> this.repository.inserirVersaoRegra(jobId,
				novaVersao, ORIGEM_SUGESTAO, origemId, representacao, parametrosJson, hash, tentativa, timestamp));
	}

	/**
	 * A versão raiz copiada de {@code extracoes_regras} pelo próprio banco: a api não
	 * reescreve a representação extraída, e a versão é o artefato exatamente como o
	 * codegen o gravou, sem passar por {@link RepresentacaoRegraDto}.
	 */
	VersaoRegra resolverExtracao(UUID jobId, UUID extracaoId, String hash, Timestamp timestamp, Instant agora) {
		return resolver(jobId, hash, ORIGEM_EXTRACAO, agora, (novaVersao) -> this.repository
			.inserirVersaoDaExtracao(jobId, novaVersao, extracaoId, hash, timestamp));
	}

	private VersaoRegra resolver(UUID jobId, String hash, String origem, Instant agora, IntFunction<UUID> inserir) {
		List<VersaoRegra> existentes = this.repository.buscarRegraPorHash(jobId, hash);
		if (!existentes.isEmpty()) {
			return existentes.getFirst();
		}

		int novaVersao = proximaVersao(jobId);
		UUID id = inserir.apply(novaVersao);
		return new VersaoRegra(id, novaVersao, origem, agora);
	}

	/**
	 * Preserva o artefato completo da proposta sem alterar a identidade canônica
	 * existente.
	 */
	VersaoRegra resolver(UUID jobId, JsonNode representacao, @Nullable String parametrosJson, String hash,
			UUID origemId, Timestamp timestamp, Instant agora) {
		return resolver(jobId, hash, "correcao", agora, numero -> this.repository.inserirVersaoCorrecao(jobId, numero,
				origemId, representacao, parametrosJson, hash, timestamp));
	}

	private int proximaVersao(UUID jobId) {
		Integer maior = this.repository.buscarMaiorVersao(jobId);
		return ((maior != null) ? maior : 0) + 1;
	}

	record VersaoRegra(UUID id, int versao, String origem, Instant criadaEm) {
	}

}

/**
 * A representação que o codegen gravou em {@code extracoes_regras}, conferida contra
 * {@code contracts/domain/representacao-regra.schema.json} antes de virar versão. O
 * artefato vem de outro serviço: fora do contrato, ele quebraria a conversão para o hash
 * numa exceção que a reentrega repetiria para sempre.
 */
final class RepresentacaoExtraida {

	private static final JsonSchema SCHEMA = JsonSchemaFactory
		.getInstance(VersionFlag.V202012,
				(builder) -> builder.schemaMappers((mappers) -> mappers
					.mapPrefix("https://synapse.local/contracts/domain/", "classpath:static/openapi/domain/")))
		.getSchema(SchemaLocation.of("classpath:static/openapi/domain/representacao-regra.schema.json"),
				SchemaValidatorsConfig.builder().formatAssertionsEnabled(true).build());

	private static final JsonMapper JSON = JsonMapper.builder()
		.enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS)
		.build();

	private RepresentacaoExtraida() {
	}

	/**
	 * A representação lida de {@code json}, ou {@code null} quando ela viola o contrato.
	 */
	static @Nullable RepresentacaoRegraDto validada(String json) {
		if (!SCHEMA.validate(json, InputFormat.JSON).isEmpty()) {
			return null;
		}
		JsonNode representacao = JSON.readTree(json);
		return new RepresentacaoRegraDto(JSON.treeToValue(representacao.path("nucleo"), NucleoRegraDto.class),
				representacao.path("especificacoes").valueStream().toList());
	}

}

/**
 * Os parâmetros que o codegen gravou em {@code extracoes_regras.parametros}, conferidos
 * contra {@code contracts/domain/parametros-simulacao.schema.json} antes de chegarem ao
 * job. O artefato vem de outro serviço, e o que o schema recusa não é um parâmetro
 * inválido - orçamento negativo, meta zero e competência fora das publicadas são válidos
 * ali, para a validação de domínio apontá-los como conflito -, é um artefato fora do
 * contrato, que a reentrega repetiria para sempre.
 */
final class ParametrosExtraidos {

	private static final JsonSchema SCHEMA = JsonSchemaFactory
		.getInstance(VersionFlag.V202012,
				(builder) -> builder.schemaMappers((mappers) -> mappers
					.mapPrefix("https://synapse.local/contracts/domain/", "classpath:static/openapi/domain/")))
		.getSchema(SchemaLocation.of("classpath:static/openapi/domain/parametros-simulacao.schema.json"),
				SchemaValidatorsConfig.builder().formatAssertionsEnabled(true).build());

	private static final JsonMapper JSON = JsonMapper.builder()
		.enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS)
		.build();

	private ParametrosExtraidos() {
	}

	/**
	 * Os parâmetros lidos de {@code json}, ou {@code null} quando eles violam o contrato.
	 * Um objeto vazio, que é o default da coluna e o texto que não disse parâmetro algum,
	 * equivale a {@link ParametrosDaSimulacao#NENHUM}.
	 */
	static @Nullable ParametrosDaSimulacao validados(String json) {
		if (!SCHEMA.validate(json, InputFormat.JSON).isEmpty()) {
			return null;
		}
		return JSON.readValue(json, ParametrosDaSimulacao.class);
	}

	/**
	 * Os parâmetros de uma versão já gravada por esta api, lidos de volta para
	 * carregá-los para uma versão nova sem reescrevê-los (confirmação, sugestão de
	 * adaptação). Não é o artefato de outro serviço chegando agora: uma violação do
	 * contrato aqui é inconsistência interna, e {@code json} não nulo que falhe a
	 * validação propaga como {@link NullPointerException} em vez de ser tratado como "sem
	 * parâmetros" - o que reintroduziria o descompasso entre hash e coluna que esta
	 * leitura existe para evitar.
	 */
	static @Nullable ParametrosDaSimulacao deVersaoExistente(@Nullable String json) {
		return (json != null) ? Objects.requireNonNull(validados(json)) : null;
	}

}
