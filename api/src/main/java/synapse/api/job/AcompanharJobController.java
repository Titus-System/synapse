package synapse.api.job;

import java.util.UUID;

import org.springframework.http.CacheControl;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import synapse.api.core.logging.CorrelationContext;
import synapse.api.core.security.UsuarioAtual;

@RestController
class AcompanharJobController {

	private final AcompanharJobService service;

	private final CorrelationContext correlacao;

	private final AutorizadorDeJob autorizador;

	private final UsuarioAtual usuarioAtual;

	AcompanharJobController(AcompanharJobService service, CorrelationContext correlacao, AutorizadorDeJob autorizador,
			UsuarioAtual usuarioAtual) {
		this.service = service;
		this.correlacao = correlacao;
		this.autorizador = autorizador;
		this.usuarioAtual = usuarioAtual;
	}

	@GetMapping(path = "/jobs/{id}/events", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
	ResponseEntity<SseEmitter> acompanhar(@PathVariable("id") UUID id) {
		this.autorizador.exigirAcesso(id, this.usuarioAtual.obter());
		try (var escopo = this.correlacao.abrir(id.toString(), null)) {
			SseEmitter emissor = this.service.acompanhar(id);
			return ResponseEntity.ok().cacheControl(CacheControl.noStore()).body(emissor);
		}
	}

}
