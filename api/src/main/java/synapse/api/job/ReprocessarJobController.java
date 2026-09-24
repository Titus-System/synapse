package synapse.api.job;

import java.net.URI;
import java.util.UUID;

import org.jspecify.annotations.Nullable;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

@RestController
class ReprocessarJobController {

	private final ReprocessarJobService service;

	ReprocessarJobController(ReprocessarJobService service) {
		this.service = service;
	}

	@PostMapping(path = "/jobs/{id}/reprocessar", produces = "application/json")
	ResponseEntity<JobCriadoDto> reprocessar(@PathVariable("id") UUID id,
			@RequestBody(required = false) @Nullable String corpo) {
		JobCriadoDto job = this.service.reprocessar(id, ReprocessarJobRequisicao.deJson(corpo));
		return ResponseEntity.created(URI.create("/api/jobs/" + job.id())).body(job);
	}

}
