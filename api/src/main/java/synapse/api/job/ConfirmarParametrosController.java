package synapse.api.job;

import java.util.UUID;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

@RestController
class ConfirmarParametrosController {

	private final ConfirmarParametrosService service;

	ConfirmarParametrosController(ConfirmarParametrosService service) {
		this.service = service;
	}

	@PostMapping(path = "/jobs/{id}/parameters", consumes = "application/json", produces = "application/json")
	ResponseEntity<JobCriadoDto> confirmar(@PathVariable("id") UUID id, @RequestBody String corpo) {
		JobCriadoDto job = this.service.confirmar(id, ConfirmarParametrosRequisicao.deJson(corpo));
		return ResponseEntity.status(HttpStatus.ACCEPTED).body(job);
	}

}
