package synapse.api.core.messaging;

import org.springframework.amqp.rabbit.config.SimpleRabbitListenerContainerFactory;
import org.springframework.amqp.rabbit.connection.ConnectionFactory;
import org.springframework.amqp.support.converter.JacksonJsonMessageConverter;
import org.springframework.boot.amqp.autoconfigure.SimpleRabbitListenerContainerFactoryConfigurer;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Substitui o {@code MessageConverter} default (Java serializado) do
 * {@code rabbitListenerContainerFactory} autoconfigurado pelo Boot por um de JSON, o
 * mesmo vocabulário que {@code PublicadorOutbox} já publica e
 * {@code ExemplosDeContratoTests} já lê. Passar pelo {@code configurer} antes de trocar o
 * converter preserva {@code spring.rabbitmq.listener.simple.*} (concorrência, prefetch,
 * modo de ack).
 */
@Configuration
public class RabbitListenerConfig {

	@Bean
	SimpleRabbitListenerContainerFactory rabbitListenerContainerFactory(
			SimpleRabbitListenerContainerFactoryConfigurer configurer, ConnectionFactory connectionFactory) {
		SimpleRabbitListenerContainerFactory factory = new SimpleRabbitListenerContainerFactory();
		configurer.configure(factory, connectionFactory);
		factory.setMessageConverter(new JacksonJsonMessageConverter());
		return factory;
	}

}
