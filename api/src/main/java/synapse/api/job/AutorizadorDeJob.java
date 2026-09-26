package synapse.api.job;

import java.util.List;
import java.util.UUID;

import org.jspecify.annotations.Nullable;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import synapse.api.core.security.AcessoDoUsuario;
import synapse.api.core.security.PapelDoUsuario;

@Service
class AutorizadorDeJob {

	private final JdbcTemplate jdbc;

	AutorizadorDeJob(JdbcTemplate jdbc) {
		this.jdbc = jdbc;
	}

	void exigir(OperacaoJob operacao, @Nullable UUID jobId, AcessoDoUsuario acesso) {
		boolean permitido = switch (operacao) {
			case CRIAR, LISTAR, CONSULTAR, ACOMPANHAR, CONFIRMAR_PARAMETROS, EXECUTAR_ACAO, REPROCESSAR ->
				acesso.papel() == PapelDoUsuario.PROFISSIONAL_RH;
		};
		if (!permitido) {
			throw new SemPermissaoNoJobException();
		}
		if (!operacao.exigePosse()) {
			return;
		}
		if (jobId == null) {
			throw new SemPermissaoNoJobException();
		}
		List<UUID> donos = this.jdbc.queryForList("SELECT usuario_id FROM jobs WHERE id = ?", UUID.class, jobId);
		if (donos.isEmpty()) {
			throw new JobNaoEncontradoException(jobId);
		}
		if (!acesso.usuarioId().equals(donos.getFirst())) {
			throw new SemPermissaoNoJobException();
		}
	}

}
