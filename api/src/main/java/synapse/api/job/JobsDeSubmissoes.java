package synapse.api.job;

import java.time.Instant;
import java.util.UUID;
import java.util.function.Function;

import org.jspecify.annotations.Nullable;
import tools.jackson.databind.JsonNode;

import synapse.api.core.security.AcessoDoUsuario;

/** Operações síncronas que participam da transação aberta pela fatia de submissões. */
public interface JobsDeSubmissoes {

	JobCriado criar(UUID submissaoId, TipoEntrada tipo, AcessoDoUsuario acesso, Instant criadoEm);

	/**
	 * Retorna false quando o job já saiu da espera ou não pertence à submissão de voz.
	 */
	boolean concluirTranscricao(UUID jobId, UUID submissaoId);

	boolean falharTranscricao(UUID jobId, UUID submissaoId);

	/** Confere a espera com trava, na transação que reagenda o trabalho. */
	boolean aguardandoTranscricao(UUID jobId, UUID submissaoId);

	/** Grava a submissão somente depois da autorização e da trava do job. */
	CorrecaoRecebida corrigir(UUID jobId, AcessoDoUsuario acesso, Function<UUID, UUID> gravarSubmissao, Instant agora);

	record CorrecaoRecebida(UUID submissaoId, JobCriado job, Rodada rodada) {
	}

	record Rodada(UUID id, @Nullable UUID rodada_anterior_id, UUID regra_analisada_id, JsonNode conflitos,
			@Nullable Correcao correcao, @Nullable UUID regra_resultante_id, String estado, Instant criada_em) {
	}

	record Correcao(String tipo, @Nullable String texto, Instant enviada_em) {
	}

	class CorrecaoRecusada extends RuntimeException {

		private final int status;

		private final String codigo;

		private final @Nullable UUID rodadaId;

		CorrecaoRecusada(int status, String codigo, String mensagem, @Nullable UUID rodadaId) {
			super(mensagem);
			this.status = status;
			this.codigo = codigo;
			this.rodadaId = rodadaId;
		}

		public int status() {
			return this.status;
		}

		public String codigo() {
			return this.codigo;
		}

		public @Nullable UUID rodadaId() {
			return this.rodadaId;
		}

		@Override
		public String getMessage() {
			return java.util.Objects.requireNonNull(super.getMessage());
		}

	}

	enum TipoEntrada {

		TEXTO, VOZ

	}

	record JobCriado(UUID id, String status) {
	}

}
