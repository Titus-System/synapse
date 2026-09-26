package synapse.api.job;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.UUID;

import org.springframework.dao.EmptyResultDataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * Aplica uma ação de finalização: transiciona o job pela {@link MaquinaDeEstadosDoJob} e
 * registra a ação em {@code job_acoes}, na mesma transação. A recusa por inviabilidade e
 * a recusa por estado inválido são a mesma {@link TransicaoDeStatusInvalidaException}
 * vinda da máquina, distinguidas aqui pelo par (destino pedido, origem atual).
 */
@Service
class ExecutarAcaoService {

	private final JdbcTemplate jdbc;

	private final MaquinaDeEstadosDoJob maquina;

	private final BuscarJobService buscarJob;

	ExecutarAcaoService(JdbcTemplate jdbc, MaquinaDeEstadosDoJob maquina, BuscarJobService buscarJob) {
		this.jdbc = jdbc;
		this.maquina = maquina;
		this.buscarJob = buscarJob;
	}

	@Transactional
	AcaoAplicada aplicar(UUID jobId, AcaoJob acao) {
		JobStatus origem;
		try {
			origem = this.maquina.transicionar(jobId, acao.destino(), "usuario", null);
		}
		catch (EmptyResultDataAccessException ex) {
			throw new JobNaoEncontradoException(jobId);
		}
		catch (TransicaoDeStatusInvalidaException ex) {
			if (acao.destino() == JobStatus.LIBERADO && ex.origem() == JobStatus.SIMULACAO_INVIAVEL) {
				throw ExecutarAcaoException.simulacaoInviavel();
			}
			throw ExecutarAcaoException.estadoInvalido(acao, ex.origem());
		}
		this.jdbc.update("""
				INSERT INTO job_acoes (job_id, acao, executado_em) VALUES (?, ?, ?)
				""", jobId, acao.paraColuna(), Timestamp.from(Instant.now()));
		EventoEstadoDto evento = EventoEstadoDto.transicao(jobId, origem, acao.destino(), null);
		JobDetalhadoDto job = this.buscarJob.buscar(jobId);
		return new AcaoAplicada(evento, job);
	}

	record AcaoAplicada(EventoEstadoDto evento, JobDetalhadoDto job) {
	}

}
