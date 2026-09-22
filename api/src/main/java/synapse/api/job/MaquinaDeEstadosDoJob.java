package synapse.api.job;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

import org.jspecify.annotations.Nullable;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

/**
 * Único ponto do código autorizado a escrever {@code jobs.status}. Toda transição,
 * inclusive a inicial, é gravada em {@code job_transicoes} com timestamp na mesma
 * transação que atualiza o job. Uma transição para status terminal também grava
 * {@code jobs.finalizado_em} com o mesmo instante.
 *
 * <p>
 * Quem dispara cada transição - eventos consumidos do RabbitMQ ou ações do usuário - é
 * responsabilidade de outras fatias; esta classe só decide se a transição pedida é
 * permitida e a registra.
 */
@Component
public class MaquinaDeEstadosDoJob {

	private final JdbcTemplate jdbcTemplate;

	MaquinaDeEstadosDoJob(JdbcTemplate jdbcTemplate) {
		this.jdbcTemplate = jdbcTemplate;
	}

	/**
	 * Registra na trilha a transição inicial do job recém-criado. O destino inicial é
	 * explícito porque origens diferentes podem iniciar em etapas diferentes do grafo: o
	 * formulário já entrega uma representação estruturada e começa diretamente em
	 * {@code gerando_regra}, sem passar pela etapa intermediária de confirmação do
	 * usuário; fluxos que ainda precisam dela podem usar a sobrecarga compatível abaixo.
	 */
	@Transactional
	public void registrarCriacao(UUID jobId, JobStatus destino, String ator) {
		registrarTransicao(jobId, null, destino, ator, null);
	}

	@Transactional
	public void registrarCriacao(UUID jobId, String ator) {
		registrarCriacao(jobId, JobStatus.AGUARDANDO_CONFIRMACAO_PARAMETROS, ator);
	}

	/**
	 * Move o job do status atual para {@code destino} e devolve o status de origem, do
	 * qual a máquina já tinha a trava (ver {@link #statusAtual}) - quem chama precisa
	 * dele para anunciar a transição (evento SSE {@code estado}) sem uma segunda consulta
	 * fora da trava, que correria com outra transição concorrente. Lança
	 * {@link TransicaoDeStatusInvalidaException} quando a transição não está no grafo
	 * declarado em {@link JobStatus}, incluindo qualquer tentativa a partir de um status
	 * terminal.
	 */
	@Transactional
	public JobStatus transicionar(UUID jobId, JobStatus destino, String ator, @Nullable String motivo) {
		JobStatus origem = statusAtual(jobId);
		if (!origem.permiteTransicaoPara(destino)) {
			throw new TransicaoDeStatusInvalidaException(origem, destino);
		}
		registrarTransicao(jobId, origem, destino, ator, motivo);
		return origem;
	}

	/**
	 * Como {@link #transicionar}, mas só age se o job ainda está em
	 * {@code origemEsperada}: devolve {@code false}, sem transição, quando ele já saiu de
	 * lá. É o que faz uma reentrega ou um evento fora de ordem virar no-op em vez de
	 * exceção.
	 */
	@Transactional
	public boolean avancarSeEm(UUID jobId, JobStatus origemEsperada, JobStatus destino, String ator,
			@Nullable String motivo) {
		if (statusAtual(jobId) != origemEsperada) {
			return false;
		}
		if (!origemEsperada.permiteTransicaoPara(destino)) {
			throw new TransicaoDeStatusInvalidaException(origemEsperada, destino);
		}
		registrarTransicao(jobId, origemEsperada, destino, ator, motivo);
		return true;
	}

	/**
	 * Trava a linha do job para a duração da transação: um evento fora de ordem e uma
	 * ação do usuário disputando o mesmo job serializam em vez de correr sobre o mesmo
	 * status atual.
	 */
	private JobStatus statusAtual(UUID jobId) {
		String status = Objects.requireNonNull(this.jdbcTemplate
			.queryForObject("SELECT status FROM jobs WHERE id = ? FOR UPDATE", String.class, jobId));
		return JobStatus.deColuna(status);
	}

	private void registrarTransicao(UUID jobId, @Nullable JobStatus origem, JobStatus destino, String ator,
			@Nullable String motivo) {
		Timestamp agora = Timestamp.from(Instant.now());
		if (destino.terminal()) {
			this.jdbcTemplate.update("UPDATE jobs SET status = ?, finalizado_em = ? WHERE id = ?", destino.paraColuna(),
					agora, jobId);
		}
		else {
			this.jdbcTemplate.update("UPDATE jobs SET status = ? WHERE id = ?", destino.paraColuna(), jobId);
		}
		this.jdbcTemplate.update("""
				INSERT INTO job_transicoes (job_id, status_anterior, status_novo, ocorrido_em, ator, motivo)
				VALUES (?, ?, ?, ?, ?, ?)
				""", jobId, (origem != null) ? origem.paraColuna() : null, destino.paraColuna(), agora, ator, motivo);
	}

}
