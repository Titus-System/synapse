package synapse.api.job;

import java.util.List;

final class CompetenciasPublicadas {

	/** Julho foi excluído do dataset pela decisão EXCLUDE_2025_07. */
	static final List<String> TODAS = List.of("2025-08", "2025-09", "2025-10", "2025-11", "2025-12");

	private CompetenciasPublicadas() {
	}

}
