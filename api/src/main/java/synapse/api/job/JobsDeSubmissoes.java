package synapse.api.job;

import java.time.Instant;
import java.util.UUID;

import synapse.api.core.security.AcessoDoUsuario;

/** Operações síncronas que participam da transação aberta pela fatia de submissões. */
public interface JobsDeSubmissoes {

	JobCriado criar(UUID submissaoId, TipoEntrada tipo, AcessoDoUsuario acesso, Instant criadoEm);

	/**
	 * Retorna false quando o job já saiu da espera ou não pertence à submissão de voz.
	 */
	boolean concluirTranscricao(UUID jobId, UUID submissaoId);

	boolean falharTranscricao(UUID jobId, UUID submissaoId);

	enum TipoEntrada {

		TEXTO, VOZ

	}

	record JobCriado(UUID id, String status) {
	}

}
