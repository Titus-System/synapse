package synapse.api.job;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Set;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.networknt.schema.JsonSchema;
import com.networknt.schema.JsonSchemaFactory;
import com.networknt.schema.SpecVersion.VersionFlag;
import com.networknt.schema.ValidationMessage;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Valida um payload de evento contra o schema real em {@code contracts/events/}, com o
 * {@code $ref} para {@code contracts/domain/} resolvido pelo {@code $id} do schema, não
 * por uma cópia nem por uma lista de campos escrita à mão - o mesmo registro por
 * {@code $id} que o codegen usa (skill {@code outbox}).
 */
final class ContratoDeEvento {

	private static final Path DIRETORIO_CONTRATOS = localizarDiretorioContratos();

	private static final ObjectMapper JSON = new ObjectMapper();

	/**
	 * O {@code $id} dos schemas é absoluto ({@code https://synapse.local/contracts/...})
	 * e nunca um endereço de verdade; o {@code $ref} relativo entre eles só resolve
	 * redirecionando esse prefixo para o diretório local, o mesmo problema documentado em
	 * {@code OpenApiDocsTests.stripsIdFromTheServedDomainSchemas}.
	 */
	private static final JsonSchemaFactory FACTORY = JsonSchemaFactory.getInstance(VersionFlag.V202012,
			(builder) -> builder.schemaMappers((mappers) -> mappers.mapPrefix("https://synapse.local/contracts/",
					DIRETORIO_CONTRATOS.toUri().toString())));

	private ContratoDeEvento() {
	}

	static void validar(String nomeDoEvento, String payloadJson) throws IOException {
		Path caminhoDoSchema = DIRETORIO_CONTRATOS.resolve("events/" + nomeDoEvento + ".schema.json");
		JsonNode schemaNode = JSON.readTree(Files.readString(caminhoDoSchema));
		JsonSchema schema = FACTORY.getSchema(schemaNode);
		Set<ValidationMessage> erros = schema.validate(JSON.readTree(payloadJson));
		assertThat(erros).as("payload de %s não conforme ao schema: %s", nomeDoEvento, erros).isEmpty();
	}

	private static Path localizarDiretorioContratos() {
		Path diretorioAtual = Path.of("").toAbsolutePath();
		while (diretorioAtual != null) {
			Path contratos = diretorioAtual.resolve("contracts");
			if (Files.isDirectory(contratos)) {
				return contratos;
			}
			diretorioAtual = diretorioAtual.getParent();
		}

		throw new IllegalStateException("Diretório contracts não encontrado a partir do diretório atual.");
	}

}
