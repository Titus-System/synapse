package synapse.api.job;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import java.util.Set;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.fasterxml.jackson.dataformat.yaml.YAMLFactory;
import com.networknt.schema.JsonSchema;
import com.networknt.schema.JsonSchemaFactory;
import com.networknt.schema.SpecVersion.VersionFlag;
import com.networknt.schema.ValidationMessage;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Valida um payload contra o contrato real em {@code contracts/}, com o {@code $ref} para
 * {@code contracts/domain/} resolvido pelo {@code $id} do schema, não por uma cópia nem
 * por uma lista de campos escrita à mão - o mesmo registro por {@code $id} que o codegen
 * usa (skill {@code outbox}). Cobre as duas fronteiras que têm contrato publicado: os
 * eventos de fila, em {@code contracts/events/}, e os eventos do stream SSE, declarados
 * como {@code EventoProgresso} em {@code contracts/http/openapi.yaml}.
 */
final class ContratoDeEvento {

	private static final Path DIRETORIO_CONTRATOS = localizarDiretorioContratos();

	private static final ObjectMapper JSON = new ObjectMapper();

	private static final ObjectMapper YAML = new ObjectMapper(new YAMLFactory());

	/**
	 * Nome na linha {@code event:} para o schema que descreve a linha {@code data:}. Quem
	 * discrimina as três formas é o nome do evento, não o payload - nenhuma delas fecha o
	 * objeto, então elas não se distinguem sozinhas (ver {@code EventoProgresso}).
	 */
	private static final Map<String, String> SCHEMA_POR_EVENTO = Map.of("etapa", "EventoEtapa", "estado",
			"EventoEstado", "resultado", "EventoResultado");

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

	/**
	 * Valida o JSON de uma linha {@code data:} do stream contra o schema do componente
	 * que o nome do evento seleciona.
	 * <p>
	 * O documento do openapi entra inteiro como raiz, com um {@code $ref} para o
	 * componente: é o que faz um {@code $ref} interno
	 * ({@code #/components/schemas/StatusJob}) resolver. O {@code $id} sintético dá a ele
	 * a posição de {@code contracts/http/}, para que o {@code ../domain/} dos refs
	 * externos caia no prefixo que a fábrica já mapeia.
	 */
	/**
	 * Valida um payload contra um schema de {@code contracts/domain/} - o formato de uma
	 * coluna {@code jsonb}, que é contrato do mesmo jeito que o de um evento.
	 */
	static void validarDominio(String nomeDoSchema, String json) throws IOException {
		Path caminho = DIRETORIO_CONTRATOS.resolve("domain/" + nomeDoSchema);
		JsonSchema schema = FACTORY.getSchema(JSON.readTree(Files.readString(caminho)));
		Set<ValidationMessage> erros = schema.validate(JSON.readTree(json));
		assertThat(erros).as("payload não conforme a %s: %s", nomeDoSchema, erros).isEmpty();
	}

	static void validarEventoDoStream(String nomeDoEvento, String dataJson) throws IOException {
		String componente = SCHEMA_POR_EVENTO.get(nomeDoEvento);
		assertThat(componente).as("evento \"%s\" não tem schema no contrato do stream", nomeDoEvento).isNotNull();
		ObjectNode raiz = (ObjectNode) YAML
			.readTree(Files.readString(DIRETORIO_CONTRATOS.resolve("http/openapi.yaml")));
		raiz.put("$id", "https://synapse.local/contracts/http/openapi.yaml");
		raiz.put("$ref", "#/components/schemas/" + componente);
		Set<ValidationMessage> erros = FACTORY.getSchema(raiz).validate(JSON.readTree(dataJson));
		assertThat(erros).as("evento \"%s\" não conforme a %s: %s", nomeDoEvento, componente, erros).isEmpty();
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
