package synapse.api.core.messaging;

import java.util.List;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import org.springframework.amqp.core.AmqpAdmin;
import org.springframework.amqp.core.Binding;
import org.springframework.amqp.core.BindingBuilder;
import org.springframework.amqp.core.Declarables;
import org.springframework.amqp.core.ExchangeBuilder;
import org.springframework.amqp.core.FanoutExchange;
import org.springframework.amqp.core.Queue;
import org.springframework.amqp.core.QueueBuilder;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.autoconfigure.condition.ConditionalOnBooleanProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Topologia do RabbitMQ da api: as filas simples que publica e consome, e a fila própria
 * ligada à exchange fanout de {@code simulacao-concluida}. A declaração é idempotente,
 * nunca exclusiva, porque a ordem de subida entre os três serviços não é garantida.
 */
@Configuration
public class RabbitTopologyConfig {

	public static final String REGRA_SUBMETIDA = "regra-submetida";

	public static final String PARAMETROS_CONFIRMADOS = "parametros-confirmados";

	public static final String ETAPA_ALTERADA = "etapa-alterada";

	public static final String NO_CONCLUIDO = "no-concluido";

	public static final String SUGESTAO_ADAPTACAO_PROPOSTA = "sugestao-adaptacao-proposta";

	public static final String SIMULACAO_CONCLUIDA_EXCHANGE = "simulacao-concluida";

	public static final String SIMULACAO_CONCLUIDA_API = "simulacao-concluida.api";

	private static final Logger log = LoggerFactory.getLogger(RabbitTopologyConfig.class);

	@Bean
	Declarables topologiaDaApi() {
		FanoutExchange simulacaoConcluida = ExchangeBuilder.fanoutExchange(SIMULACAO_CONCLUIDA_EXCHANGE)
			.durable(true)
			.build();
		Queue simulacaoConcluidaApi = QueueBuilder.durable(SIMULACAO_CONCLUIDA_API).build();
		Binding simulacaoConcluidaBinding = BindingBuilder.bind(simulacaoConcluidaApi).to(simulacaoConcluida);

		return new Declarables(QueueBuilder.durable(REGRA_SUBMETIDA).build(),
				QueueBuilder.durable(PARAMETROS_CONFIRMADOS).build(), QueueBuilder.durable(ETAPA_ALTERADA).build(),
				QueueBuilder.durable(NO_CONCLUIDO).build(), QueueBuilder.durable(SUGESTAO_ADAPTACAO_PROPOSTA).build(),
				simulacaoConcluida, simulacaoConcluidaApi, simulacaoConcluidaBinding);
	}

	/**
	 * O {@code RabbitAdmin} só declara a topologia quando a primeira conexão é aberta, e
	 * a api ainda não publica nem consome nada que abra uma sozinha - sem isto, a
	 * topologia só apareceria por acidente, na primeira vez que outra coisa (o
	 * healthcheck, por exemplo) tocasse o broker. {@code initialize()} força essa
	 * primeira conexão aqui, na subida; se o broker estiver inalcançável, a exceção
	 * derruba o boot em vez de deixar a ausência pendente e silenciosa. Desligado junto
	 * com o bean {@code AmqpAdmin} (mesma condição do autoconfigure) no perfil de teste,
	 * que não tem broker algum.
	 */
	@Bean
	@ConditionalOnBooleanProperty(name = "spring.rabbitmq.dynamic", matchIfMissing = true)
	ApplicationRunner declararTopologiaNaSubida(AmqpAdmin admin) {
		return (args) -> {
			admin.initialize();
			log.atInfo()
				.addKeyValue("filas",
						List.of(REGRA_SUBMETIDA, PARAMETROS_CONFIRMADOS, ETAPA_ALTERADA, NO_CONCLUIDO,
								SIMULACAO_CONCLUIDA_API))
				.addKeyValue("exchange", SIMULACAO_CONCLUIDA_EXCHANGE)
				.log("topologia do RabbitMQ declarada");
		};
	}

}
