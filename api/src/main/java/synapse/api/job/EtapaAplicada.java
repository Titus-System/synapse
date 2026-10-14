package synapse.api.job;

import java.util.UUID;

import org.jspecify.annotations.Nullable;

import synapse.api.job.JobEventosService.FimDaIteracao;

record EtapaAplicada(DesfechoCorrecao desfecho, @Nullable EventoEstadoDto transicao, @Nullable UUID regraId,
		@Nullable UUID rodadaId, int numeroConflitos, @Nullable FimDaIteracao fim) {

	static EtapaAplicada comum(@Nullable EventoEstadoDto transicao) {
		return comum(transicao, null);
	}

	static EtapaAplicada comum(@Nullable EventoEstadoDto transicao, @Nullable FimDaIteracao fim) {
		return new EtapaAplicada(DesfechoCorrecao.COMUM, transicao, null, null, 0, fim);
	}

	boolean emitirEtapa() {
		return this.desfecho == DesfechoCorrecao.COMUM || this.desfecho == DesfechoCorrecao.RODADA_ABERTA
				|| this.desfecho == DesfechoCorrecao.REEXTRACAO_FALHOU;
	}

}

enum DesfechoCorrecao {

	COMUM("comum", "nenhum"), RODADA_ABERTA("rodada_aberta", "nenhum"),
	REEXTRACAO_FALHOU("reextracao_falhou", "nenhum"), DUPLICADA("duplicada", "nenhum"),
	EVENTO_INVALIDO("descartada", "evento_invalido"), JOB_INEXISTENTE("descartada", "job_inexistente"),
	ESTADO_INCOMPATIVEL("descartada", "estado_incompativel"), REGRA_AUSENTE("descartada", "regra_ausente"),
	REGRA_NAO_ATUAL("descartada", "regra_nao_atual"), CONFLITOS_INVALIDOS("descartada", "conflitos_invalidos"),
	SEM_REEXTRACAO("descartada", "sem_reextracao"), REGRA_DIVERGENTE("descartada", "regra_divergente"),
	TENTATIVA_AUSENTE("descartada", "tentativa_ausente"),
	TENTATIVA_DESCONHECIDA("descartada", "tentativa_desconhecida"),
	TENTATIVA_AMBIGUA("descartada", "tentativa_ambigua");

	private final String resultado;

	private final String motivo;

	DesfechoCorrecao(String resultado, String motivo) {
		this.resultado = resultado;
		this.motivo = motivo;
	}

	String resultado() {
		return this.resultado;
	}

	String motivo() {
		return this.motivo;
	}

}
