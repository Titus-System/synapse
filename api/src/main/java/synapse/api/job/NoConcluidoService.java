package synapse.api.job;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

import org.jspecify.annotations.Nullable;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * Grava o que {@code no-concluido} traz para a trilha de auditoria (T-046): a linha em
 * {@code trilhas_auditoria} do nó, e, no nó {@code geracao_codigo}, a linha em
 * {@code simulacoes} que amarra a versão da regra ao código executado - é por
 * {@code codigo_gerado_id} que {@link SimulacaoConcluidaService} depois encontra a
 * simulação a amarrar ao resultado.
 */
@Service
class NoConcluidoService {

	private final JdbcTemplate jdbc;

	NoConcluidoService(JdbcTemplate jdbc) {
		this.jdbc = jdbc;
	}

	@Transactional
	void aplicar(UUID jobId, UUID eventoId, EtapaDoGrafo no, NoConcluidoDto evento) {
		this.jdbc.queryForObject("SELECT id FROM jobs WHERE id = ?", UUID.class, jobId);

		UUID simulacaoId = evento.simulacao_id();
		UUID regraId = evento.regra_id();
		UUID codigoGeradoId = evento.codigo_gerado_id();
		if (no == EtapaDoGrafo.GERACAO_CODIGO && regraId != null && codigoGeradoId != null) {
			simulacaoId = registrarSimulacao(jobId, regraId, codigoGeradoId, simulacaoId,
					Objects.requireNonNull(evento.concluido_em()));
		}

		registrarTrilha(eventoId, jobId, simulacaoId, no, evento);
	}

	/**
	 * {@code ON CONFLICT DO NOTHING} sem alvo cobre tanto a reentrega (mesmo
	 * {@code codigo_gerado_id}, índice único {@code uq_simulacoes_codigo_gerado_id})
	 * quanto um {@code resultado_id} já amarrado a outra linha - os dois casos não
	 * escrevem de novo, e a leitura seguinte por {@code codigo_gerado_id} devolve a linha
	 * que existe.
	 */
	private UUID registrarSimulacao(UUID jobId, UUID regraId, UUID codigoGeradoId, @Nullable UUID simulacaoId,
			Instant concluidoEm) {
		this.jdbc.update("""
				INSERT INTO simulacoes (id, criado_em, regra_id, job_id, codigo_gerado_id, resultado_id)
				VALUES (COALESCE(?, uuidv7()), ?, ?, ?, ?,
					(SELECT id FROM resultados_simulacao WHERE job_id = ? AND codigo_gerado_id = ?
						ORDER BY criado_em DESC, id DESC LIMIT 1))
				ON CONFLICT DO NOTHING
				""", simulacaoId, Timestamp.from(concluidoEm), regraId, jobId, codigoGeradoId, jobId, codigoGeradoId);
		return Objects.requireNonNull(this.jdbc.queryForObject("SELECT id FROM simulacoes WHERE codigo_gerado_id = ?",
				UUID.class, codigoGeradoId));
	}

	private void registrarTrilha(UUID eventoId, UUID jobId, @Nullable UUID simulacaoId, EtapaDoGrafo no,
			NoConcluidoDto evento) {
		this.jdbc.update(
				"""
						INSERT INTO trilhas_auditoria
							(evento_id, job_id, simulacao_id, no, concluido_em, regra_id, conclusao, prompt_id, codigo_gerado_id, explicacao_id)
						VALUES (?, ?, ?, ?, ?, ?, ?::jsonb, ?, ?, ?)
						ON CONFLICT (evento_id) DO NOTHING
						""",
				eventoId, jobId, simulacaoId, no.paraEvento(),
				Timestamp.from(Objects.requireNonNull(evento.concluido_em())), evento.regra_id(),
				Objects.requireNonNull(evento.conclusao()).toString(), evento.prompt_id(), evento.codigo_gerado_id(),
				evento.explicacao_id());
	}

}
