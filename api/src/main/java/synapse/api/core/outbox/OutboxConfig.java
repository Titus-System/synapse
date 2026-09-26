package synapse.api.core.outbox;

import org.springframework.boot.autoconfigure.condition.ConditionalOnBooleanProperty;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.scheduling.annotation.SchedulingConfigurer;
import org.springframework.scheduling.config.ScheduledTaskRegistrar;

import synapse.api.core.config.AppProperties;

/**
 * Agenda {@link PublicadorOutbox} a cada {@code app.outbox.poll-interval}. Atraso fixo, e
 * não taxa fixa: o intervalo conta a partir do fim do ciclo anterior, então um ciclo
 * lento nunca se sobrepõe ao seguinte.
 */
@Configuration
@EnableScheduling
@ConditionalOnBooleanProperty(name = "app.outbox.enabled", matchIfMissing = true)
class OutboxConfig implements SchedulingConfigurer {

	private final PublicadorOutbox publicador;

	private final AppProperties properties;

	OutboxConfig(PublicadorOutbox publicador, AppProperties properties) {
		this.publicador = publicador;
		this.properties = properties;
	}

	@Override
	public void configureTasks(ScheduledTaskRegistrar registrar) {
		registrar.addFixedDelayTask(this.publicador::publicarPendentes, this.properties.outbox().pollInterval());
	}

}
