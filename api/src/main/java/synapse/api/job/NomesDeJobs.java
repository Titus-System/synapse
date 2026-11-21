package synapse.api.job;

import java.util.Collection;
import java.util.Map;
import java.util.UUID;

import org.springframework.stereotype.Service;

/**
 * O nome de exibição dos jobs pela mesma regra de {@code GET /jobs} e {@code GET
 * /jobs/{id}}: o definido pelo usuário, senão o padrão tirado do texto inicial. Job sem
 * nome resolvido fica fora do mapa.
 */
public interface NomesDeJobs {

	Map<UUID, String> resolver(Collection<UUID> jobIds);

}

@Service
class NomesDeJobsService implements NomesDeJobs {

	private final JobRepository repository;

	NomesDeJobsService(JobRepository repository) {
		this.repository = repository;
	}

	@Override
	public Map<UUID, String> resolver(Collection<UUID> jobIds) {
		return jobIds.isEmpty() ? Map.of() : this.repository.resolverNomes(jobIds);
	}

}
