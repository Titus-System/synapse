package synapse.api.job;

import java.util.List;
import java.util.UUID;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;

import synapse.api.job.JobsDeSubmissoes.Rodada;

@RestController
class RodadasController {

	private final RodadasRepository rodadas;

	RodadasController(RodadasRepository rodadas) {
		this.rodadas = rodadas;
	}

	@AutorizarJob(OperacaoJob.CONSULTAR)
	@GetMapping(path = "/jobs/{id}/rodadas", produces = "application/json")
	List<Rodada> listar(@PathVariable UUID id) {
		return this.rodadas.listar(id);
	}

}
