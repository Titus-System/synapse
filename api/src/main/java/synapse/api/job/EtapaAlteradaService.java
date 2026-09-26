package synapse.api.job;

import java.util.UUID;

import org.jspecify.annotations.Nullable;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * Traduz {@code etapa-alterada} em transição do job, que é o que tira o job de
 * {@code gerando_regra}: a entrada em {@code delegacao_worker} o leva a
 * {@code simulando}, e {@code status = erro} o leva a {@code erro}. Só age a partir de
 * {@code gerando_regra}; depois disso o desfecho é do worker.
 */
@Service
class EtapaAlteradaService {

	private static final String ATOR = "evento";

	private static final String STATUS_INICIADA = "iniciada";

	private static final String STATUS_ERRO = "erro";

	private static final String RAZAO_ERRO = "Falha durante o processamento da regra, antes da simulação.";

	private final MaquinaDeEstadosDoJob maquina;

	EtapaAlteradaService(MaquinaDeEstadosDoJob maquina) {
		this.maquina = maquina;
	}

	/**
	 * O evento {@code estado} da transição aplicada, ou {@code null} quando a combinação
	 * não move o job ou ele já saiu de {@code gerando_regra}.
	 */
	@Transactional
	@Nullable EventoEstadoDto aplicar(UUID jobId, EtapaDoGrafo etapa, String status) {
		if (etapa == EtapaDoGrafo.DELEGACAO_WORKER && STATUS_INICIADA.equals(status)) {
			return avancarDeGerandoRegra(jobId, JobStatus.SIMULANDO, null, null);
		}
		if (STATUS_ERRO.equals(status)) {
			return avancarDeGerandoRegra(jobId, JobStatus.ERRO, "erro_" + etapa.paraEvento(), RAZAO_ERRO);
		}
		return null;
	}

	private @Nullable EventoEstadoDto avancarDeGerandoRegra(UUID jobId, JobStatus destino,
			@Nullable String motivoDaTrilha, @Nullable String razao) {
		boolean avancou = this.maquina.avancarSeEm(jobId, JobStatus.GERANDO_REGRA, destino, ATOR, motivoDaTrilha);
		return avancou ? EventoEstadoDto.transicao(jobId, JobStatus.GERANDO_REGRA, destino, razao) : null;
	}

}
