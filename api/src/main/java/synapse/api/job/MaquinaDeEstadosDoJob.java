package synapse.api.job;

import java.sql.Timestamp;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.UUID;

import org.jspecify.annotations.Nullable;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import synapse.api.core.outbox.EventoOutbox;
import synapse.api.core.outbox.Outbox;
import synapse.api.core.logging.CorrelationContext;

/**
 * Único ponto do código autorizado a escrever {@code jobs.status}. Toda transição,
 * inclusive a inicial, é gravada em {@code job_transicoes} com timestamp na mesma
 * transação que atualiza o job. A primeira transição para um status de processamento
 * grava {@code jobs.iniciado_em}, e a transição para status terminal grava
 * {@code jobs.finalizado_em}, ambas com o mesmo instante da transição.
 *
 * <p>
 * A transição para status terminal também grava {@code job-encerrado} no outbox, na mesma
 * transação: o evento só existe se a transição foi confirmada, e uma transição desfeita
 * não deixa evento publicável. Como um status terminal não tem saída, cada job produz
 * esse evento uma vez só.
 *
 * <p>
 * Quem dispara cada transição - eventos consumidos do RabbitMQ ou ações do usuário - é
 * responsabilidade de outras fatias; esta classe só decide se a transição pedida é
 * permitida e a registra.
 */
@Component
public class MaquinaDeEstadosDoJob {

	private static final Logger log = LoggerFactory.getLogger(MaquinaDeEstadosDoJob.class);

	private final JobRepository repository;

	private final Outbox outbox;

	MaquinaDeEstadosDoJob(JobRepository repository, Outbox outbox) {
		this.repository = repository;
		this.outbox = outbox;
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
		String status = this.repository.buscarStatusComTrava(jobId);
		return JobStatus.deColuna(status);
	}

	private void registrarTransicao(UUID jobId, @Nullable JobStatus origem, JobStatus destino, String ator,
			@Nullable String motivo) {
		// Microssegundos são a precisão do timestamptz: o instante gravado e o que vai no
		// evento de encerramento têm de ser o mesmo, inclusive quando o evento é montado
		// de
		// novo a partir do banco.
		Instant instante = Instant.now().truncatedTo(ChronoUnit.MICROS);
		Timestamp agora = Timestamp.from(instante);
		if (destino.terminal()) {
			this.repository.atualizarStatusFinalizado(jobId, destino.paraColuna(), agora);
		}
		else if (destino.emProcessamento()) {
			this.repository.atualizarStatusIniciado(jobId, destino.paraColuna(), agora);
		}
		else {
			this.repository.atualizarStatus(jobId, destino.paraColuna());
		}
		UUID transicaoId = this.repository.inserirTransicao(jobId, (origem != null) ? origem.paraColuna() : null,
				destino.paraColuna(), agora, ator, motivo);
		if (destino.terminal()) {
			anunciarEncerramento(jobId, transicaoId, destino, instante);
		}
	}

	/**
	 * O id da transição terminal é o {@code evento_id}: estável em toda republicação e no
	 * registro dos encerramentos anteriores ao evento (changeset 018), que o lê da mesma
	 * linha.
	 */
	private void anunciarEncerramento(UUID jobId, UUID transicaoId, JobStatus destino, Instant instante) {
		this.outbox.registrar(jobId, EventoOutbox.JOB_ENCERRADO,
				new JobEncerradoDto(transicaoId, jobId, destino.paraColuna(), instante));
		String usuarioId = MDC.get(CorrelationContext.USER_ID_KEY);
		Runnable registrar = () -> {
			try (var escopo = new CorrelationContext().abrir(jobId.toString(), usuarioId)) {
				log.atInfo()
					.addKeyValue("evento_id", transicaoId)
					.addKeyValue("status", destino.paraColuna())
					.log("encerramento do job registrado no outbox");
			}
		};
		// Só depois do commit: uma transação desfeita não pode aparecer no log como
		// encerrada.
		if (TransactionSynchronizationManager.isSynchronizationActive()) {
			TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
				@Override
				public void afterCommit() {
					registrar.run();
				}
			});
		}
		else {
			registrar.run();
		}
	}

}
