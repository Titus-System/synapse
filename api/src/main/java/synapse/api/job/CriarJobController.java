package synapse.api.job;

import java.net.URI;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

import synapse.api.core.security.UsuarioAtual;

@RestController
class CriarJobController {

	private final CriarJobService service;

	private final UsuarioAtual usuarioAtual;

	CriarJobController(CriarJobService service, UsuarioAtual usuarioAtual) {
		this.service = service;
		this.usuarioAtual = usuarioAtual;
	}

	@PostMapping(path = "/jobs", consumes = "application/json", produces = "application/json")
	ResponseEntity<JobCriadoDto> criar(@RequestBody String corpo) {
		JobCriadoDto job = this.service.criar(CriarJobRequisicao.deJson(corpo), this.usuarioAtual.obter().usuarioId());
		return ResponseEntity.created(URI.create("/api/jobs/" + job.id())).body(job);
	}

}
