package synapse.api.job;

import java.net.URI;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

@RestController
class CriarJobController {

	private final CriarJobService service;

	CriarJobController(CriarJobService service) {
		this.service = service;
	}

	@PostMapping(path = "/jobs", consumes = "application/json", produces = "application/json")
	ResponseEntity<JobCriadoDto> criar(@RequestBody String corpo) {
		JobCriadoDto job = this.service.criar(CriarJobRequisicao.deJson(corpo));
		return ResponseEntity.created(URI.create("/api/jobs/" + job.id())).body(job);
	}

}
