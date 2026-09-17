package synapse.api.job;

import java.sql.Array;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

import org.jspecify.annotations.Nullable;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

@Service
class ListarJobsService {

	private final JdbcTemplate jdbc;

	ListarJobsService(JdbcTemplate jdbc) {
		this.jdbc = jdbc;
	}

	/**
	 * {@code REPEATABLE_READ} faz a contagem e a página lerem o mesmo snapshot. O
	 * veredito é o da simulação mais recente do job, e só quando ela terminou com
	 * sucesso.
	 */
	@Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
	PaginaJobsDto listar(ListarJobsRequisicao requisicao) {
		long total = Objects.requireNonNull(this.jdbc.queryForObject("SELECT count(*) FROM jobs", Long.class));
		List<JobResumoDto> itens = this.jdbc.query("""
				SELECT j.id, j.status, j.competencias, j.orcamento, j.criado_em, j.finalizado_em,
				       j.job_origem_id, rs.veredito
				FROM jobs j
				LEFT JOIN LATERAL (
				    SELECT s.resultado_id FROM simulacoes s
				    WHERE s.job_id = j.id
				    ORDER BY s.criado_em DESC, s.id DESC
				    LIMIT 1
				) corrente ON true
				LEFT JOIN resultados_simulacao rs ON rs.id = corrente.resultado_id AND rs.status = 'sucesso'
				ORDER BY j.criado_em DESC, j.id DESC
				LIMIT ? OFFSET ?
				""", (linha, numero) -> resumo(linha), requisicao.tamanho(), requisicao.deslocamento());
		return new PaginaJobsDto(itens, requisicao.pagina(), requisicao.tamanho(), total);
	}

	private static JobResumoDto resumo(ResultSet linha) throws SQLException {
		return new JobResumoDto(Objects.requireNonNull(linha.getObject("id", UUID.class)),
				Objects.requireNonNull(linha.getString("status")), competencias(linha.getArray("competencias")),
				Objects.requireNonNull(linha.getBigDecimal("orcamento")), linha.getString("veredito"),
				Objects.requireNonNull(instante(linha, "criado_em")), instante(linha, "finalizado_em"),
				linha.getObject("job_origem_id", UUID.class));
	}

	private static List<String> competencias(Array coluna) throws SQLException {
		return List.of((String[]) coluna.getArray());
	}

	private static @Nullable Instant instante(ResultSet linha, String coluna) throws SQLException {
		OffsetDateTime valor = linha.getObject(coluna, OffsetDateTime.class);
		return valor == null ? null : valor.toInstant();
	}

}
