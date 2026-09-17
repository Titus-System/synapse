package synapse.api.job;

import java.net.URI;
import java.security.Principal;
import java.util.UUID;

import org.jspecify.annotations.Nullable;

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
	ResponseEntity<JobCriadoDto> criar(@RequestBody String corpo, @Nullable Principal principal) {
		UUID usuarioId = usuarioId(principal);
		JobCriadoDto job = this.service.criar(usuarioId, CriarJobRequisicao.deJson(corpo));
		return ResponseEntity.created(URI.create("/api/jobs/" + job.id())).body(job);
	}

	private static UUID usuarioId(@Nullable Principal principal) {
		if (principal == null) {
			throw CriarJobException.naoAutenticado();
		}
		try {
			return UUID.fromString(principal.getName());
		}
		catch (IllegalArgumentException ex) {
			throw CriarJobException.naoAutenticado();
		}
	}

}
