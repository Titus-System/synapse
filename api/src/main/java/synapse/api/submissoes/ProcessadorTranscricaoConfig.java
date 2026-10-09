package synapse.api.submissoes;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import org.springframework.boot.autoconfigure.condition.ConditionalOnBooleanProperty;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.scheduling.annotation.SchedulingConfigurer;
import org.springframework.scheduling.config.ScheduledTaskRegistrar;

import synapse.api.core.config.AppProperties;

/**
 * Agenda {@link ProcessadorTranscricao} a cada {@code app.transcription.processor.poll-
 * interval}. Atraso fixo, como o poller do outbox: o intervalo conta a partir do fim do
 * ciclo anterior, então um ciclo que esperou o provedor não se sobrepõe ao seguinte.
 *
 * <p>
 * Sem a chave do provedor nada é agendado, e a mesma condição que faz
 * {@code POST /submissoes} recusar a voz com {@code estado_invalido}
 * ({@link DisponibilidadeTranscricao}) mantém o processador parado. A api sobe
 * normalmente e as rotas existentes continuam funcionando.
 */
@Configuration
@EnableScheduling
@ConditionalOnBooleanProperty(name = "app.transcription.processor.enabled", matchIfMissing = true)
class ProcessadorTranscricaoConfig implements SchedulingConfigurer {

	private static final Logger log = LoggerFactory.getLogger(ProcessadorTranscricaoConfig.class);

	private final ProcessadorTranscricao processador;

	private final DisponibilidadeTranscricao disponibilidade;

	private final AppProperties properties;

	ProcessadorTranscricaoConfig(ProcessadorTranscricao processador, DisponibilidadeTranscricao disponibilidade,
			AppProperties properties) {
		this.processador = processador;
		this.disponibilidade = disponibilidade;
		this.properties = properties;
	}

	@Override
	public void configureTasks(ScheduledTaskRegistrar registrar) {
		if (!this.disponibilidade.disponivel()) {
			log.info("processador de transcrição desligado: provedor não configurado");
			return;
		}
		registrar.addFixedDelayTask(this.processador::processarPendentes,
				this.properties.transcription().processor().pollInterval());
	}

}
