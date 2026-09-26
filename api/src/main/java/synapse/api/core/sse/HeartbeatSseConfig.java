package synapse.api.core.sse;

import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.scheduling.annotation.SchedulingConfigurer;
import org.springframework.scheduling.config.ScheduledTaskRegistrar;

import synapse.api.core.config.AppProperties;

/**
 * Agenda o heartbeat de {@link EmissoresSse} no intervalo de {@code app.sse.heartbeat}.
 * {@code SchedulingConfigurer} em vez de {@code @Scheduled(fixedRateString = "...")}
 * porque o intervalo vem de {@link AppProperties}, não de uma chave lida direto do
 * ambiente (skill {@code configuration}).
 */
@Configuration
@EnableScheduling
class HeartbeatSseConfig implements SchedulingConfigurer {

	private final EmissoresSse emissores;

	private final AppProperties properties;

	HeartbeatSseConfig(EmissoresSse emissores, AppProperties properties) {
		this.emissores = emissores;
		this.properties = properties;
	}

	@Override
	public void configureTasks(ScheduledTaskRegistrar registrar) {
		registrar.addFixedRateTask(this.emissores::enviarHeartbeat, this.properties.sse().heartbeat());
	}

}
