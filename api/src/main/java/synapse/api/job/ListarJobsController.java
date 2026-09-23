package synapse.api.job;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import synapse.api.core.security.UsuarioAtual;

@RestController
class ListarJobsController {

	private final ListarJobsService service;

	private final UsuarioAtual usuarioAtual;

	ListarJobsController(ListarJobsService service, UsuarioAtual usuarioAtual) {
		this.service = service;
		this.usuarioAtual = usuarioAtual;
	}

	@GetMapping(path = "/jobs", produces = "application/json")
	PaginaJobsDto listar(@RequestParam(name = "pagina", defaultValue = "0") int pagina,
			@RequestParam(name = "tamanho", defaultValue = "20") int tamanho) {
		return this.service.listar(new ListarJobsRequisicao(pagina, tamanho), this.usuarioAtual.obter());
	}

}
