package synapse.api.job;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.HexFormat;
import java.util.List;
import java.util.UUID;
import java.util.function.IntFunction;

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
	 * A extração pode chegar sem {@code percentual}: o núcleo não exige campo algum, e a
	 * falta é apontada pela validação de domínio do ciclo seguinte, não aqui.
	 */
	static String calcular(RepresentacaoRegraDto regra) {
		NucleoRegraDto nucleo = regra.nucleo();
		BigDecimal percentual = nucleo.percentual();
		NucleoRegraDto canonico = new NucleoRegraDto(nucleo.vigencia(), nucleo.loja(), nucleo.marca(), nucleo.cargo(),
				(percentual != null) ? percentual.stripTrailingZeros() : null);
		byte[] json = JSON.writeValueAsString(new RepresentacaoRegraDto(canonico, regra.especificacoes()))
			.getBytes(StandardCharsets.UTF_8);
		try {
			return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(json));
		}
		catch (NoSuchAlgorithmException ex) {
			throw new IllegalStateException("SHA-256 indisponível.", ex);
		}
	}

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

	private final JobRepository repository;

	VersoesDaRegra(JobRepository repository) {
		this.repository = repository;
	}

	VersaoRegra resolver(UUID jobId, RepresentacaoRegraDto representacao, String hash, String origem,
			@Nullable UUID origemId, Timestamp timestamp, Instant agora) {
		return resolver(jobId, hash, origem, agora, (novaVersao) -> this.repository.inserirVersaoRegra(jobId,
				novaVersao, origem, origemId, representacao, hash, timestamp));
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
