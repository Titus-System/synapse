package synapse.api.job;

import java.math.BigDecimal;
import java.sql.Timestamp;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.json.JsonMapper;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.SqlArrayValue;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import synapse.api.core.outbox.EventoOutbox;
import synapse.api.core.outbox.Outbox;

@Service
class ReprocessarJobService {

	private final JdbcTemplate jdbc;

	private final MaquinaDeEstadosDoJob maquina;

	private final Outbox outbox;

	private final JsonMapper json = JsonMapper.builder()
		.enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS)
		.build();

	ReprocessarJobService(JdbcTemplate jdbc, MaquinaDeEstadosDoJob maquina, Outbox outbox) {
		this.jdbc = jdbc;
		this.maquina = maquina;
		this.outbox = outbox;
	}

	@Transactional
	JobCriadoDto reprocessar(UUID origemId, ReprocessarJobRequisicao requisicao) {
		JobDeOrigem origem = carregarOrigem(origemId);
		if (origem.status() != JobStatus.ARQUIVADO) {
			throw ReprocessarJobException.estadoInvalido();
		}
		List<UUID> regras = this.jdbc.queryForList("""
				SELECT id FROM regras WHERE job_id = ? ORDER BY versao DESC LIMIT 1
				""", UUID.class, origemId);
		if (regras.isEmpty()) {
			throw ReprocessarJobException.semRegra();
		}
		List<String> competencias = requisicao.competencias() != null ? requisicao.competencias()
				: origem.competencias();
		BigDecimal orcamento = requisicao.orcamento() != null ? requisicao.orcamento() : origem.orcamento();
		Instant agora = Instant.now().truncatedTo(ChronoUnit.MICROS);
		Timestamp timestamp = Timestamp.from(agora);
		JobStatus status = JobStatus.AGUARDANDO_CONFIRMACAO_PARAMETROS;
		UUID jobId = Objects.requireNonNull(this.jdbc.queryForObject("""
				INSERT INTO jobs (status, usuario_id, job_origem_id, competencias, orcamento, criado_em)
				VALUES (?, ?, ?, ?, ?, ?) RETURNING id
				""", UUID.class, status.paraColuna(), origem.usuarioId(), origemId,
				new SqlArrayValue("text", competencias.toArray()), orcamento, timestamp));
		this.maquina.registrarCriacao(jobId, status, "usuario");
		RegraCriadaDto regra = Objects.requireNonNull(this.jdbc.queryForObject("""
				INSERT INTO regras (job_id, versao, origem, regra_origem_id, nucleo, especificacoes, hash, criada_em)
				SELECT ?, 1, 'reprocessamento', id, nucleo, especificacoes, hash, ?
				FROM regras WHERE id = ?
				RETURNING id, nucleo, especificacoes
				""", (rs, linha) -> new RegraCriadaDto(Objects.requireNonNull(rs.getObject("id", UUID.class)), 1,
				"reprocessamento",
				new RepresentacaoRegraDto(
						this.json.readValue(Objects.requireNonNull(rs.getString("nucleo")), NucleoRegraDto.class),
						this.json.readTree(Objects.requireNonNull(rs.getString("especificacoes")))
							.valueStream()
							.toList()),
				agora), jobId, timestamp, regras.getFirst()));
		this.outbox.registrar(jobId, EventoOutbox.REGRA_SUBMETIDA,
				new RegraSubmetidaDto(jobId, "reprocessamento", competencias, orcamento, null, regra.id()));
		return new JobCriadoDto(jobId, status.paraColuna(), "reprocessamento", competencias, orcamento, agora, null,
				origemId, regra);
	}

	private JobDeOrigem carregarOrigem(UUID jobId) {
		List<JobDeOrigem> jobs = this.jdbc.query("""
				SELECT status, usuario_id, competencias, orcamento FROM jobs WHERE id = ?
				""",
				(rs, linha) -> new JobDeOrigem(JobStatus.deColuna(Objects.requireNonNull(rs.getString("status"))),
						Objects.requireNonNull(rs.getObject("usuario_id", UUID.class)),
						List.of((String[]) rs.getArray("competencias").getArray()),
						Objects.requireNonNull(rs.getBigDecimal("orcamento"))),
				jobId);
		if (jobs.isEmpty()) {
			throw new JobNaoEncontradoException(jobId);
		}
		return jobs.getFirst();
	}

	private record JobDeOrigem(JobStatus status, UUID usuarioId, List<String> competencias, BigDecimal orcamento) {
	}

}
