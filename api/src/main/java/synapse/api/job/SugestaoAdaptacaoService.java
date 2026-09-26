package synapse.api.job;

import java.sql.Timestamp;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.UUID;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import synapse.api.core.outbox.EventoOutbox;
import synapse.api.core.outbox.Outbox;
import synapse.api.job.VersoesDaRegra.VersaoRegra;

/**
 * Aplica a sugestão de adaptação numa transação só: transiciona o job de volta para
 * {@code gerando_regra}, grava a versão proposta e publica {@code parametros-confirmados}
 * pelo outbox, que é o que devolve a alternativa ao grafo do codegen.
 *
 * <p>
 * A alternativa não tem atalho: ela volta pela geração e precisa de uma simulação nova
 * antes de chegar ao usuário ({@link JobStatus}), que é a exigência de a alternativa ser
 * simulada antes de ser mostrada (ARCHITECTURE.md §3.3).
 */
@Service
class SugestaoAdaptacaoService {

	private final MaquinaDeEstadosDoJob maquina;

	private final VersoesDaRegra versoes;

	private final Outbox outbox;

	SugestaoAdaptacaoService(MaquinaDeEstadosDoJob maquina, VersoesDaRegra versoes, Outbox outbox) {
		this.maquina = maquina;
		this.versoes = versoes;
		this.outbox = outbox;
	}

	/**
	 * A máquina vem primeiro porque é ela quem trava a linha do job
	 * (<code>SELECT ... FOR UPDATE</code>): uma reentrega da proposta encontra o job já
	 * fora de {@code simulacao_inviavel} e {@link TransicaoDeStatusInvalidaException}
	 * desfaz a transação inteira, sem versão duplicada nem segundo
	 * {@code parametros-confirmados}. A deduplicação por hash em {@link VersoesDaRegra} é
	 * a segunda barreira, para a proposta que chega depois de o usuário ter confirmado a
	 * mesma representação à mão.
	 */
	@Transactional
	SugestaoAplicada aplicar(UUID jobId, UUID regraOrigemId, RepresentacaoRegraDto representacao) {
		JobStatus origem = this.maquina.transicionar(jobId, JobStatus.GERANDO_REGRA, "evento",
				"sugestao_adaptacao_proposta");
		Instant agora = Instant.now().truncatedTo(ChronoUnit.MICROS);
		VersaoRegra versao = this.versoes.resolver(jobId, representacao, HashDaRegra.calcular(representacao),
				"sugestao_adaptacao", regraOrigemId, Timestamp.from(agora), agora);
		this.outbox.registrar(jobId, EventoOutbox.PARAMETROS_CONFIRMADOS,
				new ParametrosConfirmadosDto(jobId, versao.id()));
		return new SugestaoAplicada(origem, versao);
	}

	record SugestaoAplicada(JobStatus origem, VersaoRegra versao) {
	}

}
