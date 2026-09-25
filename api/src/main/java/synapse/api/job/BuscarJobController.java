package synapse.api.job;

import java.util.UUID;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;

@RestController
class BuscarJobController {

	private final BuscarJobService service;

	BuscarJobController(BuscarJobService service) {
		this.service = service;
	}

	@AutorizarJob(OperacaoJob.CONSULTAR)
	@GetMapping(path = "/jobs/{id}", produces = "application/json")
	JobDetalhadoDto buscar(@PathVariable UUID id) {
		return this.service.buscar(id);
	}

}
