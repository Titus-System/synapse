package synapse.api.core.docs;

import java.net.URI;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * /redocly, ao lado do /docs que o springdoc já registra sozinho para o Swagger UI. Os
 * dois leem o mesmo contrato copiado de contracts/http/ (ver pom.xml).
 *
 * O Location é escrito direto na resposta, nunca por {@code sendRedirect()}: o Tomcat é
 * obrigado a reescrever um redirecionamento relativo do {@code sendRedirect()} em URL
 * absoluta a partir do Host que recebeu, e atrás do Caddy sem repasse de cabeçalho
 * configurado isso seria o endereço interno do container, não o domínio público.
 */
@RestController
class DocsWebConfig {

	@GetMapping("/redocly")
	ResponseEntity<Void> redocly() {
		return ResponseEntity.status(HttpStatus.FOUND)
			.location(URI.create("/openapi/http/synapse-openapi.html"))
			.build();
	}

}
