package synapse.api.core.sse;

import java.io.IOException;
import java.time.Duration;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;
import java.util.function.Supplier;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.SmartLifecycle;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import synapse.api.core.config.AppProperties;
import synapse.api.core.logging.CorrelationContext;

/**
 * Mapa {@code job_id -> emissores conectados}. Núcleo de infraestrutura: não conhece
 * status de job nem nome de evento de negócio - só transporta o que a fatia de negócio
 * (hoje {@code synapse.api.job}) decide enviar.
 *
 * <p>
 * Instância única: o mapa vive em memória do processo. Com mais de uma instância da
 * `api`, um cliente inscrito numa instância nunca veria um evento emitido a partir da
 * outra - fora do escopo desta tarefa, que assume instância única.
 */
@Component
public class EmissoresSse implements SmartLifecycle {

	private static final Logger log = LoggerFactory.getLogger(EmissoresSse.class);

	private final ConcurrentHashMap<UUID, Set<SseEmitter>> emissoresPorJob = new ConcurrentHashMap<>();

	private final AtomicLong sequencia = new AtomicLong();

	private final Duration timeout;

	private final CorrelationContext correlacao;

	private volatile boolean executando;

	@Autowired
	public EmissoresSse(AppProperties properties, CorrelationContext correlacao) {
		this(properties.sse().timeout(), correlacao);
	}

	EmissoresSse(Duration timeout, CorrelationContext correlacao) {
		this.timeout = timeout;
		this.correlacao = correlacao;
	}

	/**
	 * Abre um emissor para {@code jobId}, registra-o e envia a fotografia produzida por
	 * {@code fotografia}. Se {@code fotografia} lançar, o emissor é descartado sem ter
	 * sido devolvido ao chamador - a requisição segue o caminho síncrono normal de
	 * tratamento de exceção, nunca chega a virar stream.
	 *
	 * <p>
	 * Registro e envio da fotografia acontecem sob o mesmo monitor do emissor que
	 * {@link #emitir} e {@link #enviarHeartbeat} usam para enviar: fecha a corrida em que
	 * uma transição emitida entre a leitura do estado e o envio da fotografia chegaria
	 * fora de ordem.
	 */
	public SseEmitter inscrever(UUID jobId, Supplier<EventoSse> fotografia) {
		SseEmitter emissor = new SseEmitter(this.timeout.toMillis());
		emissor.onCompletion(() -> remover(jobId, emissor));
		emissor.onError((ex) -> remover(jobId, emissor));
		emissor.onTimeout(() -> {
			remover(jobId, emissor);
			emissor.complete();
		});

		synchronized (emissor) {
			registrar(jobId, emissor);
			EventoSse evento;
			try {
				evento = fotografia.get();
			}
			catch (RuntimeException ex) {
				remover(jobId, emissor);
				throw ex;
			}
			enviar(jobId, emissor, evento, this.sequencia.incrementAndGet());
			if (evento.ultimo()) {
				remover(jobId, emissor);
				emissor.complete();
			}
		}

		try (var escopo = this.correlacao.abrir(jobId.toString(), null)) {
			log.debug("cliente inscrito no stream");
		}
		return emissor;
	}

	/**
	 * Envia {@code evento} a todo emissor inscrito em {@code jobId}. Job sem cliente
	 * conectado é descartado sem erro - o progresso é efêmero por natureza.
	 *
	 * <p>
	 * Chame depois do commit da transação que produziu o fato: um cliente que se inscreve
	 * entre o commit e esta chamada recebe, na própria fotografia, o mesmo estado que
	 * este evento anuncia - corrida inofensiva. O inverso não é: emitir antes do commit
	 * arriscaria entregar ao cliente um evento cujo fato ainda não está gravado.
	 */
	public void emitir(UUID jobId, EventoSse evento) {
		Set<SseEmitter> emissores = evento.ultimo() ? this.emissoresPorJob.remove(jobId)
				: this.emissoresPorJob.get(jobId);
		if (emissores == null || emissores.isEmpty()) {
			return;
		}
		long id = this.sequencia.incrementAndGet();
		for (SseEmitter emissor : Set.copyOf(emissores)) {
			synchronized (emissor) {
				enviar(jobId, emissor, evento, id);
				if (evento.ultimo()) {
					emissor.complete();
				}
			}
		}
	}

	/**
	 * Envia um comentário SSE vazio a todo emissor conectado, para manter a conexão viva.
	 */
	void enviarHeartbeat() {
		for (var entrada : this.emissoresPorJob.entrySet()) {
			for (SseEmitter emissor : Set.copyOf(entrada.getValue())) {
				synchronized (emissor) {
					try {
						emissor.send(SseEmitter.event().comment("heartbeat"));
					}
					catch (IOException | IllegalStateException ex) {
						remover(entrada.getKey(), emissor);
					}
				}
			}
		}
	}

	/** Número de emissores conectados neste instante, somado sobre todos os jobs. */
	public int conexoesAtivas() {
		return this.emissoresPorJob.values().stream().mapToInt(Set::size).sum();
	}

	private void registrar(UUID jobId, SseEmitter emissor) {
		this.emissoresPorJob.computeIfAbsent(jobId, (id) -> ConcurrentHashMap.newKeySet()).add(emissor);
	}

	private void remover(UUID jobId, SseEmitter emissor) {
		this.emissoresPorJob.computeIfPresent(jobId, (id, emissores) -> {
			emissores.remove(emissor);
			return emissores.isEmpty() ? null : emissores;
		});
		try (var escopo = this.correlacao.abrir(jobId.toString(), null)) {
			log.debug("cliente removido do stream");
		}
	}

	private void enviar(UUID jobId, SseEmitter emissor, EventoSse evento, long id) {
		try {
			emissor.send(SseEmitter.event().id(Long.toString(id)).name(evento.nome()).data(evento.dados()));
		}
		catch (IOException | IllegalStateException ex) {
			// O cliente saiu (conexão fechada, timeout do lado dele); o próprio container
			// encerra a requisição - não há o que relançar.
			remover(jobId, emissor);
		}
	}

	@Override
	public void start() {
		this.executando = true;
	}

	/**
	 * Fecha todo emissor aberto na parada da aplicação. Sem sobrescrever
	 * {@link #getPhase}, a fase padrão de {@link SmartLifecycle} (o maior {@code int}) é
	 * maior que a do desligamento gracioso do servidor web, o que faz este {@code stop}
	 * rodar antes dele - sem isto, um cliente ainda conectado prenderia o desligamento
	 * gracioso pelo tempo todo configurado, à espera de uma conexão que nunca fecha
	 * sozinha.
	 */
	@Override
	public void stop() {
		this.executando = false;
		for (Set<SseEmitter> emissores : this.emissoresPorJob.values()) {
			for (SseEmitter emissor : Set.copyOf(emissores)) {
				emissor.complete();
			}
		}
		this.emissoresPorJob.clear();
	}

	@Override
	public boolean isRunning() {
		return this.executando;
	}

}
