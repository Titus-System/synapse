package synapse.api.job;

import java.sql.Timestamp;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.List;
import java.util.UUID;

import org.jspecify.annotations.Nullable;
import tools.jackson.databind.json.JsonMapper;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import synapse.api.core.outbox.EventoOutbox;
import synapse.api.core.outbox.Outbox;
import synapse.api.job.VersoesDaRegra.VersaoRegra;
import synapse.api.job.SimulacaoConcluidaService.DesfechoAplicado;

@Service
class SugestaoAdaptacaoService {

	private final JdbcTemplate jdbc;

	private final MaquinaDeEstadosDoJob maquina;

	private final VersoesDaRegra versoes;

	private final Outbox outbox;

	private final SimulacaoConcluidaService conclusao;

	private final JsonMapper json = new JsonMapper();

	SugestaoAdaptacaoService(JdbcTemplate jdbc, MaquinaDeEstadosDoJob maquina, VersoesDaRegra versoes, Outbox outbox,
			SimulacaoConcluidaService conclusao) {
		this.jdbc = jdbc;
		this.maquina = maquina;
		this.versoes = versoes;
		this.outbox = outbox;
		this.conclusao = conclusao;
	}

	@Transactional
	@Nullable SugestaoAplicada aplicar(UUID jobId, UUID regraOrigemId, UUID resultadoId, RepresentacaoRegraDto representacao) {
		var percentual = representacao.nucleo().percentual();
		if (percentual == null || percentual.signum() <= 0) {
			return null;
		}
		List<Contexto> contextos = this.jdbc.query("""
				SELECT j.status, j.competencias, j.orcamento, j.submissao_id,
				       CASE WHEN j.job_origem_id IS NOT NULL THEN 'reprocessamento' ELSE s.tipo END AS origem
				FROM jobs j LEFT JOIN submissoes s ON s.id = j.submissao_id
				WHERE j.id = ? FOR UPDATE OF j
				""",
				(rs, numero) -> new Contexto(JobStatus.deColuna(rs.getString("status")), new RegraSubmetidaDto(jobId,
						rs.getString("origem"), List.of((String[]) rs.getArray("competencias").getArray()),
						rs.getBigDecimal("orcamento"), rs.getObject("submissao_id", UUID.class), regraOrigemId)),
				jobId);
		if (contextos.isEmpty()) {
			return null;
		}
		Contexto contexto = contextos.getFirst();
		if (!List.of(JobStatus.GERANDO_REGRA, JobStatus.SIMULANDO, JobStatus.SIMULACAO_INVIAVEL)
			.contains(contexto.status())) {
			return null;
		}
		String hash = HashDaRegra.calcular(representacao);
		Boolean valida = this.jdbc.queryForObject("""
				SELECT EXISTS (
				    SELECT 1 FROM regras r
				    JOIN codigos_gerados c ON c.regra_id = r.id AND c.job_id = r.job_id
				    JOIN resultados_simulacao rs ON rs.codigo_gerado_id = c.id AND rs.job_id = r.job_id
				    WHERE r.id = ? AND r.job_id = ? AND rs.id = ?
				      AND rs.status = 'sucesso' AND rs.veredito = 'inviavel'
				      AND r.origem <> 'sugestao_adaptacao'
				      AND NOT EXISTS (SELECT 1 FROM regras outra WHERE outra.job_id = r.job_id
				          AND (outra.versao > r.versao OR outra.origem = 'sugestao_adaptacao' OR outra.hash = ?))
				      AND (r.nucleo->>'percentual')::numeric > ?
				      AND r.nucleo - 'percentual' = ?::jsonb - 'percentual'
				      AND r.especificacoes = ?::jsonb
				)
				""", Boolean.class, regraOrigemId, jobId, resultadoId, hash, percentual,
				this.json.writeValueAsString(representacao.nucleo()),
				this.json.writeValueAsString(representacao.especificacoes()));
		if (!Boolean.TRUE.equals(valida)) {
			return null;
		}
		// As filas não têm ordem entre si: a proposta pode anteceder o evento do
		// resultado.
		DesfechoAplicado desfechoOriginal = null;
		if (contexto.status() != JobStatus.SIMULACAO_INVIAVEL) {
			desfechoOriginal = this.conclusao.aplicar(jobId, resultadoId, DesfechoDaSimulacao.INVIAVEL);
			if (desfechoOriginal == null) {
				return null;
			}
			if (desfechoOriginal.simulacaoId() == null) {
				// no-concluido pode ter vinculado o resultado antes de sua notificação.
				List<UUID> simulacoes = this.jdbc.query(
						"SELECT id FROM simulacoes WHERE job_id = ? AND resultado_id = ?",
						(rs, numero) -> rs.getObject("id", UUID.class), jobId, resultadoId);
				if (!simulacoes.isEmpty()) {
					desfechoOriginal = new DesfechoAplicado(desfechoOriginal.origem(), simulacoes.getFirst(),
							desfechoOriginal.avancouDeGerandoRegra());
				}
			}
		}
		JobStatus origem = this.maquina.transicionar(jobId, JobStatus.GERANDO_REGRA, "evento",
				"sugestao_adaptacao_proposta");
		Instant agora = Instant.now().truncatedTo(ChronoUnit.MICROS);
		VersaoRegra versao = this.versoes.resolver(jobId, representacao, hash, "sugestao_adaptacao", regraOrigemId,
				Timestamp.from(agora), agora);
		RegraSubmetidaDto entrada = contexto.entrada();
		this.outbox.registrar(jobId, EventoOutbox.REGRA_SUBMETIDA, new RegraSubmetidaDto(jobId, entrada.origem(),
				entrada.competencias(), entrada.orcamento(), entrada.submissao_id(), versao.id()));
		return new SugestaoAplicada(origem, versao, desfechoOriginal);
	}

	private record Contexto(JobStatus status, RegraSubmetidaDto entrada) {
	}

	record SugestaoAplicada(JobStatus origem, VersaoRegra versao, @Nullable DesfechoAplicado desfechoOriginal) {
	}

}
