package synapse.api.job;

import java.util.UUID;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;

import synapse.api.core.security.UsuarioAtual;

@RestController
class BuscarJobController {

	private final BuscarJobService service;

	private final AutorizadorDeJob autorizador;

	private final UsuarioAtual usuarioAtual;

	BuscarJobController(BuscarJobService service, AutorizadorDeJob autorizador, UsuarioAtual usuarioAtual) {
		this.service = service;
		this.autorizador = autorizador;
		this.usuarioAtual = usuarioAtual;
	}

	@GetMapping(path = "/jobs/{id}", produces = "application/json")
	JobDetalhadoDto buscar(@PathVariable UUID id) {
		this.autorizador.exigirAcesso(id, this.usuarioAtual.obter());
		return this.service.buscar(id);
	}

}
