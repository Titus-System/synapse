package synapse.api.core.web;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.client.RestTestClient;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * O frontend é servido em domínio próprio, então toda chamada dele à api é cross-origin:
 * sem estes cabeçalhos o navegador descarta a resposta mesmo com a api respondendo 200.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
		properties = "app.cors.allowed-origins=https://app.exemplo.com,http://localhost:5173")
@ActiveProfiles("test")
class CorsConfigTests {

	private static final String ORIGEM = "https://app.exemplo.com";

	@LocalServerPort
	private int port;

	private RestTestClient client;

	@BeforeEach
	void bindToServer() {
		this.client = RestTestClient.bindToServer().baseUrl("http://localhost:" + this.port).build();
	}

	@Test
	void allowsThePreflightOfAConfiguredOrigin() {
		this.client.options()
			.uri("/jobs")
			.header("Origin", ORIGEM)
			.header("Access-Control-Request-Method", "POST")
			.header("Access-Control-Request-Headers", "content-type")
			.exchange()
			.expectStatus()
			.isOk()
			.expectHeader()
			.valueEquals("Access-Control-Allow-Origin", ORIGEM)
			.expectHeader()
			.value("Access-Control-Allow-Methods", (metodos) -> assertThat(metodos).contains("POST"))
			.expectHeader()
			.value("Access-Control-Allow-Headers",
					(cabecalhos) -> assertThat(cabecalhos).containsIgnoringCase("Content-Type"));
	}

	/** Cada origem da lista vale por si; o separador é vírgula, não um valor só. */
	@Test
	void allowsEveryOriginOfTheList() {
		this.client.options()
			.uri("/jobs")
			.header("Origin", "http://localhost:5173")
			.header("Access-Control-Request-Method", "GET")
			.exchange()
			.expectStatus()
			.isOk()
			.expectHeader()
			.valueEquals("Access-Control-Allow-Origin", "http://localhost:5173");
	}

	@Test
	void rejectsThePreflightOfAnOriginOutsideTheList() {
		this.client.options()
			.uri("/jobs")
			.header("Origin", "https://outro.exemplo.com")
			.header("Access-Control-Request-Method", "POST")
			.exchange()
			.expectStatus()
			.isForbidden()
			.expectHeader()
			.doesNotExist("Access-Control-Allow-Origin");
	}

	/** O contrato em contracts/http/ só tem GET e POST. */
	@Test
	void rejectsThePreflightOfAMethodOutsideTheContract() {
		this.client.options()
			.uri("/jobs")
			.header("Origin", ORIGEM)
			.header("Access-Control-Request-Method", "DELETE")
			.exchange()
			.expectStatus()
			.isForbidden()
			.expectHeader()
			.doesNotExist("Access-Control-Allow-Origin");
	}

	/**
	 * A resposta da requisição real também carrega a origem — o preflight libera o envio,
	 * não a leitura do corpo.
	 */
	@Test
	void echoesTheOriginOnTheActualRequest() {
		this.client.get()
			.uri("/redocly")
			.header("Origin", ORIGEM)
			.exchange()
			.expectStatus()
			.is3xxRedirection()
			.expectHeader()
			.valueEquals("Access-Control-Allow-Origin", ORIGEM);
	}

	/**
	 * Sem credenciais o navegador não manda cookie nem repete sessão de outra aba. A
	 * autenticação da api é por token no cabeçalho, não por cookie.
	 */
	@Test
	void doesNotAllowCredentials() {
		this.client.options()
			.uri("/jobs")
			.header("Origin", ORIGEM)
			.header("Access-Control-Request-Method", "POST")
			.exchange()
			.expectStatus()
			.isOk()
			.expectHeader()
			.doesNotExist("Access-Control-Allow-Credentials");
	}

}
