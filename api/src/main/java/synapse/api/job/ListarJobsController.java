package synapse.api.job;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.bind.annotation.RequestAttribute;

import synapse.api.core.security.AcessoDoUsuario;

@RestController
class ListarJobsController {

	private final ListarJobsService service;

	ListarJobsController(ListarJobsService service) {
		this.service = service;
	}

	@AutorizarJob(OperacaoJob.LISTAR)
	@GetMapping(path = "/jobs", produces = "application/json")
	PaginaJobsDto listar(@RequestParam(name = "pagina", defaultValue = "0") int pagina,
			@RequestParam(name = "tamanho", defaultValue = "20") int tamanho,
			@RequestAttribute(AutorizacaoJobsInterceptor.ACESSO) AcessoDoUsuario acesso) {
		return this.service.listar(new ListarJobsRequisicao(pagina, tamanho), acesso);
	}

}
