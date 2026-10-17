package synapse.api.job;

import java.util.UUID;

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

import org.springframework.amqp.AmqpRejectAndDontRequeueException;

final class ValidacaoCorrecaoProposta {

	private static final JsonMapper JSON = JsonMapper.builder()
		.enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS)
		.build();

	private static final JsonSchema SCHEMA = JsonSchemaFactory
		.getInstance(VersionFlag.V202012,
				builder -> builder.schemaMappers(
						mappers -> mappers.mapPrefix("https://synapse.local/contracts/", "classpath:static/openapi/")))
		.getSchema(SchemaLocation.of("classpath:static/openapi/events/correcao-proposta.schema.json"),
				SchemaValidatorsConfig.builder().formatAssertionsEnabled(true).build());

	private ValidacaoCorrecaoProposta() {
	}

	static @Nullable JsonNode ler(byte[] corpo) {
		try {
			return JSON.readTree(corpo);
		}
		catch (JacksonException ex) {
			return null;
		}
	}

	static @Nullable UUID jobId(@Nullable JsonNode corpo) {
		if (corpo == null)
			return null;
		try {
			return UUID.fromString(corpo.path("job_id").asString());
		}
		catch (IllegalArgumentException ex) {
			return null;
		}
	}

	static CorrecaoPropostaDto validar(@Nullable JsonNode corpo) {
		if (corpo == null || !SCHEMA.validate(corpo.toString(), InputFormat.JSON).isEmpty()) {
			throw new AmqpRejectAndDontRequeueException("correcao-proposta fora do contrato");
		}
		return new CorrecaoPropostaDto(UUID.fromString(corpo.path("job_id").asString()),
				UUID.fromString(corpo.path("regra_origem_id").asString()),
				UUID.fromString(corpo.path("submissao_id").asString()), corpo.path("representacao"),
				corpo.get("parametros"), corpo);
	}

}
