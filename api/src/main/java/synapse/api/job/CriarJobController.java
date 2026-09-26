package synapse.api.job;

import java.net.URI;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.bind.annotation.RequestAttribute;

import synapse.api.core.security.AcessoDoUsuario;

@RestController
class CriarJobController {

	private final CriarJobService service;

	CriarJobController(CriarJobService service) {
		this.service = service;
	}

	@AutorizarJob(OperacaoJob.CRIAR)
	@PostMapping(path = "/jobs", consumes = "application/json", produces = "application/json")
	ResponseEntity<JobCriadoDto> criar(@RequestBody String corpo,
			@RequestAttribute(AutorizacaoJobsInterceptor.ACESSO) AcessoDoUsuario acesso) {
		JobCriadoDto job = this.service.criar(CriarJobRequisicao.deJson(corpo), acesso.usuarioId());
		return ResponseEntity.created(URI.create("/api/jobs/" + job.id())).body(job);
	}

}
