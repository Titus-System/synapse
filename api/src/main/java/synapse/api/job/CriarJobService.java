package synapse.api.job;

import java.sql.Timestamp;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.Objects;
import java.util.UUID;

import tools.jackson.databind.json.JsonMapper;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.SqlArrayValue;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
class CriarJobService {

	private final JdbcTemplate jdbc;

	private final MaquinaDeEstadosDoJob maquina;

	private final JsonMapper json = new JsonMapper();

	CriarJobService(JdbcTemplate jdbc, MaquinaDeEstadosDoJob maquina) {
		this.jdbc = jdbc;
		this.maquina = maquina;
	}

	@Transactional
	JobCriadoDto criar(UUID usuarioId, CriarJobRequisicao requisicao) {
		Instant agora = Instant.now().truncatedTo(ChronoUnit.MICROS);
		Timestamp timestamp = Timestamp.from(agora);
		RepresentacaoRegraDto representacao = requisicao.representacao();
		String hash = HashDaRegra.calcular(representacao);
		UUID submissaoId = Objects.requireNonNull(this.jdbc.queryForObject("""
				INSERT INTO submissoes (usuario_id, tipo, conteudo, criado_em)
				VALUES (?, ?, ?::jsonb, ?) RETURNING id
				""", UUID.class, usuarioId, requisicao.origem(), this.json.writeValueAsString(requisicao.conteudo()),
				timestamp));
		String status = JobStatus.AGUARDANDO_CONFIRMACAO_PARAMETROS.paraColuna();
		UUID jobId = Objects.requireNonNull(this.jdbc.queryForObject("""
				INSERT INTO jobs (status, usuario_id, submissao_id, competencias, orcamento, criado_em)
				VALUES (?, ?, ?, ?, ?, ?) RETURNING id
				""", UUID.class, status, usuarioId, submissaoId,
				new SqlArrayValue("text", requisicao.competencias().toArray()), requisicao.orcamento(), timestamp));
		this.maquina.registrarCriacao(jobId, "usuario");
		UUID regraId = Objects.requireNonNull(this.jdbc.queryForObject("""
				INSERT INTO regras (job_id, versao, origem, nucleo, especificacoes, hash, criada_em)
				VALUES (?, 1, 'confirmacao_usuario', ?::jsonb, '[]'::jsonb, ?, ?) RETURNING id
				""", UUID.class, jobId, this.json.writeValueAsString(representacao.nucleo()), hash, timestamp));
		RegraCriadaDto regra = new RegraCriadaDto(regraId, 1, "confirmacao_usuario", representacao, agora);
		return new JobCriadoDto(jobId, status, requisicao.origem(), requisicao.competencias(), requisicao.orcamento(),
				agora, submissaoId, regra);
	}

}
