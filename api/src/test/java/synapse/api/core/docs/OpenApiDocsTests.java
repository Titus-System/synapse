package synapse.api.core.docs;

import java.net.URI;
import java.util.concurrent.atomic.AtomicReference;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import org.junit.jupiter.api.Test;

import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.test.web.servlet.client.RestTestClient;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Um erro na cópia de build deixaria /docs de pé, mas com um contrato ausente ou
 * incompleto.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class OpenApiDocsTests {

	@LocalServerPort
	private int port;

	private RestTestClient client() {
		return RestTestClient.bindToServer().baseUrl("http://localhost:" + this.port).build();
	}

	@Test
	void redirectsDocsToTheSwaggerUiPage() {
		this.client()
			.get()
			.uri("/docs")
			.exchange()
			.expectStatus()
			.is3xxRedirection()
			.expectHeader()
			.valueEquals("Location", "/swagger-ui/index.html");
	}

	@Test
	void servesTheSwaggerUiPageConfiguredToReadTheContract() {
		this.client()
			.get()
			.uri("/swagger-ui/index.html")
			.exchange()
			.expectStatus()
			.isOk()
			.expectBody(String.class)
			.value((body) -> assertThat(body).contains("id=\"swagger-ui\""));
	}

	@Test
	void servesTheContractFileCopiedFromContracts() {
		this.client()
			.get()
			.uri("/openapi/http/openapi.yaml")
			.exchange()
			.expectStatus()
			.isOk()
			.expectBody(String.class)
			.value((body) -> assertThat(body).contains("Synapse - API HTTP").contains("/jobs"));
	}

	@Test
	void servesTheDomainSchemasTheContractReferencesRelatively() {
		this.client()
			.get()
			.uri("/openapi/domain/representacao-regra.schema.json")
			.exchange()
			.expectStatus()
			.isOk()
			.expectBody(String.class)
			.value((body) -> assertThat(body).contains("regra-nucleo.schema.json"));
	}

	@Test
	void stripsIdFromTheServedDomainSchemas() {
		// $id em contracts/domain/ é só identificador (https://synapse.local/...), nunca
		// endereço de verdade. O Swagger UI trata $id como URI de fetch: com ele
		// presente,
		// o resolvedor tenta buscar esse host de verdade e falha em vez de seguir o
		// caminho relativo por onde já chegou até o arquivo.
		this.client()
			.get()
			.uri("/openapi/domain/comum.schema.json")
			.exchange()
			.expectStatus()
			.isOk()
			.expectBody(String.class)
			.value((body) -> assertThat(body).doesNotContain("\"$id\""));
	}

	@Test
	void redirectsRedoclyToTheRedocPage() {
		// Relativo, não absoluto: atrás de um proxy que não repassa o host público, um
		// Location absoluto construído a partir do request interno aponta para o
		// endereço errado. Ver o Javadoc de DocsWebConfig.
		this.client()
			.get()
			.uri("/redocly")
			.exchange()
			.expectStatus()
			.is3xxRedirection()
			.expectHeader()
			.valueEquals("Location", "/openapi/http/synapse-openapi.html");
	}

	@Test
	void servesTheRedocPageCopiedFromContracts() {
		this.client()
			.get()
			.uri("/openapi/http/synapse-openapi.html")
			.exchange()
			.expectStatus()
			.isOk()
			.expectBody(String.class)
			.value((body) -> assertThat(body).contains("redoc-container"));
	}

	@Test
	void swaggerAndRedocPointAtTheSameContractFile() {
		AtomicReference<String> swaggerUiUrl = new AtomicReference<>();
		this.client()
			.get()
			.uri("/swagger-ui/swagger-initializer.js")
			.exchange()
			.expectStatus()
			.isOk()
			.expectBody(String.class)
			.value((body) -> swaggerUiUrl.set(extractQuoted(body, "url:")));

		AtomicReference<String> redocRef = new AtomicReference<>();
		this.client()
			.get()
			.uri("/openapi/http/synapse-openapi.html")
			.exchange()
			.expectStatus()
			.isOk()
			.expectBody(String.class)
			.value((body) -> redocRef.set(extractQuoted(body, "Redoc.init(")));

		URI swaggerAbsolute = URI.create(swaggerUiUrl.get());
		URI redocAbsolute = URI.create("/openapi/http/synapse-openapi.html").resolve(redocRef.get());
		assertThat(redocAbsolute).isEqualTo(swaggerAbsolute);
	}

	private static String extractQuoted(String source, String afterLiteral) {
		Pattern pattern = Pattern.compile(Pattern.quote(afterLiteral) + "\\s*\"([^\"]+)\"");
		Matcher matcher = pattern.matcher(source);
		if (!matcher.find()) {
			throw new IllegalStateException("Nenhuma URL entre aspas encontrada após " + afterLiteral);
		}
		return matcher.group(1);
	}

	@Test
	void neverGeneratesRoutesFromAnnotations() {
		// paths-to-match vazio: o documento gerado por anotação existe (a UI depende
		// dos beans que ele sustenta), mas fica sempre sem rota - não é uma segunda
		// fonte do contrato, mesmo quando um controller for escrito no futuro.
		this.client()
			.get()
			.uri("/v3/api-docs")
			.exchange()
			.expectStatus()
			.isOk()
			.expectBody(String.class)
			.value((body) -> assertThat(body).contains("\"paths\":{}"));
	}

}
