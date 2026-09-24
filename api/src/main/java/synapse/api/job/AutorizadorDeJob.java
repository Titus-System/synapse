package synapse.api.job;

import java.util.List;
import java.util.UUID;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import synapse.api.core.security.AcessoDoUsuario;

@Service
class AutorizadorDeJob {

	private final JdbcTemplate jdbc;

	AutorizadorDeJob(JdbcTemplate jdbc) {
		this.jdbc = jdbc;
	}

	void exigirAcesso(UUID jobId, AcessoDoUsuario acesso) {
		List<UUID> donos = this.jdbc.queryForList("SELECT usuario_id FROM jobs WHERE id = ?", UUID.class, jobId);
		if (donos.isEmpty()) {
			throw new JobNaoEncontradoException(jobId);
		}
		if (!acesso.auditor() && !acesso.usuarioId().equals(donos.getFirst())) {
			throw new SemPermissaoNoJobException();
		}
	}

}
