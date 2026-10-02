package synapse.api.job;

import org.jspecify.annotations.Nullable;

/**
 * Único tradutor do token gravado em {@code job_transicoes.motivo} para a razão
 * localizada que o usuário lê, tanto no evento SSE {@code estado} quanto em {@code GET
 * /jobs/{id}}. A trilha guarda o token, e não a razão, porque é por ele que as falhas
 * ficam distinguíveis para a decisão operacional; a tradução só acontece na saída.
 */
final class MotivoDaParada {

	static final String FALHA_ANTES_DA_SIMULACAO = "Falha durante o processamento da regra, antes da simulação.";

	private static final String PREFIXO_FALHA_NA_ETAPA = "erro_";

	private MotivoDaParada() {
	}

	/** O token de {@code job_transicoes.motivo} de uma falha anterior à simulação. */
	static String falhaNaEtapa(EtapaDoGrafo etapa) {
		return PREFIXO_FALHA_NA_ETAPA + etapa.paraEvento();
	}

	/**
	 * A razão da parada que levou o job a {@code status}, ou {@code null} quando o token
	 * não descreve uma parada que termina nesse status: sem token, token de transição sem
	 * parada ({@code sugestao_adaptacao_proposta}), token desconhecido ou token de uma
	 * parada que leva a outro estado. É o destino que impede uma causa antiga de ser lida
	 * como o motivo do estado corrente.
	 */
	static @Nullable String razaoLocalizada(JobStatus status, @Nullable String motivoDaTrilha) {
		if (motivoDaTrilha == null) {
			return null;
		}
		DesfechoDaSimulacao desfecho = DesfechoDaSimulacao.peloMotivoDaTrilha(motivoDaTrilha);
		if (desfecho != null) {
			return (desfecho.destino() == status) ? desfecho.razaoLocalizada() : null;
		}
		if (status == JobStatus.ERRO && motivoDaTrilha.startsWith(PREFIXO_FALHA_NA_ETAPA)
				&& EtapaDoGrafo.deEvento(motivoDaTrilha.substring(PREFIXO_FALHA_NA_ETAPA.length())) != null) {
			return FALHA_ANTES_DA_SIMULACAO;
		}
		return null;
	}

}
