package synapse.api.job;

import java.util.List;
import java.util.UUID;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import org.jspecify.annotations.Nullable;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * Aplica o desfecho de {@code simulacao-concluida} numa transação só: transiciona o job e
 * amarra o resultado à simulação que o produziu, para que as duas confirmem ou desfaçam
 * juntas.
 */
@Service
class SimulacaoConcluidaService {

	private static final Logger log = LoggerFactory.getLogger(SimulacaoConcluidaService.class);

	private final JdbcTemplate jdbc;

	private final MaquinaDeEstadosDoJob maquina;

	SimulacaoConcluidaService(JdbcTemplate jdbc, MaquinaDeEstadosDoJob maquina) {
		this.jdbc = jdbc;
		this.maquina = maquina;
	}

	/**
	 * {@code transicionar} vem primeiro porque é ele quem trava a linha do job
	 * (<code>SELECT ... FOR UPDATE</code>), e é essa trava que serializa uma redelivery
	 * ou um evento fora de ordem contra esta mesma chamada: a segunda entrega encontra o
	 * job já fora do estado de origem esperado e
	 * {@link TransicaoDeStatusInvalidaException} desfaz a transação inteira, inclusive a
	 * amarração abaixo - uma transição só por resultado, sem tabela de deduplicação
	 * dedicada.
	 */
	@Transactional
	DesfechoAplicado aplicar(UUID jobId, UUID resultadoId, DesfechoDaSimulacao desfecho) {
		JobStatus origem = this.maquina.transicionar(jobId, desfecho.destino(), "evento", desfecho.motivoDaTrilha());
		UUID simulacaoId = amarrarResultado(jobId, resultadoId);
		return new DesfechoAplicado(origem, simulacaoId);
	}

	/**
	 * Aponta {@code simulacoes.resultado_id} para a linha que o worker gravou, casando
	 * pelo {@code codigo_gerado_id} que a simulação já registrou no momento em que o
	 * código foi executado. Zero linhas casadas é o caso normal até a api passar a
	 * inserir em {@code simulacoes} (evento {@code no-concluido}): a transição segue do
	 * mesmo jeito, e o evento {@code resultado} do SSE simplesmente não sai.
	 * {@code resultado_id IS NULL} e o índice único {@code uq_simulacoes_resultado_id}
	 * são a segunda barreira de idempotência, abaixo da que a máquina de estados já dá.
	 */
	private @Nullable UUID amarrarResultado(UUID jobId, UUID resultadoId) {
		List<UUID> amarradas = this.jdbc.query("""
				UPDATE simulacoes s SET resultado_id = r.id
				FROM resultados_simulacao r
				WHERE r.id = ? AND r.job_id = ? AND s.job_id = r.job_id
				  AND s.codigo_gerado_id = r.codigo_gerado_id AND s.resultado_id IS NULL
				RETURNING s.id
				""", (linha, numero) -> linha.getObject("id", UUID.class), resultadoId, jobId);
		if (amarradas.isEmpty()) {
			log.atWarn()
				.addKeyValue("resultado_id", resultadoId)
				.log("nenhuma simulação amarrada ao resultado; evento \"resultado\" não será emitido");
			return null;
		}
		return amarradas.getFirst();
	}

	record DesfechoAplicado(JobStatus origem, @Nullable UUID simulacaoId) {
	}

}
