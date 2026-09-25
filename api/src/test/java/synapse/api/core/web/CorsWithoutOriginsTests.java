package synapse.api.core.web;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.client.RestTestClient;

/**
 * {@code CORS_ALLOWED_ORIGINS} vazio fecha a api para o navegador, em vez de liberar
 * qualquer origem. Sem mapeamento de CORS registrado, o preflight cai no tratamento
 * padrão de OPTIONS do MVC e responde 200 - é a ausência do cabeçalho de origem, não o
 * status, que faz o navegador descartar a resposta.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT, properties = "app.cors.allowed-origins=")
@ActiveProfiles("test")
class CorsWithoutOriginsTests {

	@LocalServerPort
	private int port;

	private RestTestClient client;

	@BeforeEach
	void bindToServer() {
		this.client = RestTestClient.bindToServer().baseUrl("http://localhost:" + this.port).build();
	}

	@Test
	void liberatesNoOriginAtAll() {
		this.client.options()
			.uri("/jobs")
			.header("Origin", "https://app.exemplo.com")
			.header("Access-Control-Request-Method", "POST")
			.exchange()
			.expectStatus()
			.isOk()
			.expectHeader()
			.doesNotExist("Access-Control-Allow-Origin");
	}

}
