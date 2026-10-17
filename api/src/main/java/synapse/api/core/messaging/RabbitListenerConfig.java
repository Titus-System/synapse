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

	/**
	 * O consumidor de propostas registra erros sanitizados; o container não deve repetir
	 * o payload.
	 */
	@Bean
	SimpleRabbitListenerContainerFactory correcaoPropostaContainerFactory(
			SimpleRabbitListenerContainerFactoryConfigurer configurer, ConnectionFactory connectionFactory) {
		SimpleRabbitListenerContainerFactory factory = new SimpleRabbitListenerContainerFactory();
		configurer.configure(factory, connectionFactory);
		factory.setErrorHandler(erro -> {
			for (Throwable causa = erro; causa != null; causa = causa.getCause()) {
				if (causa instanceof org.springframework.amqp.AmqpRejectAndDontRequeueException) {
					throw new org.springframework.amqp.AmqpRejectAndDontRequeueException(
							"correcao-proposta fora do contrato");
				}
			}
			throw new org.springframework.amqp.ImmediateRequeueAmqpException("correcao-proposta não confirmada");
		});
		return factory;
	}

	@Bean
	SimpleRabbitListenerContainerFactory rabbitListenerContainerFactory(
			SimpleRabbitListenerContainerFactoryConfigurer configurer, ConnectionFactory connectionFactory) {
		SimpleRabbitListenerContainerFactory factory = new SimpleRabbitListenerContainerFactory();
		configurer.configure(factory, connectionFactory);
		factory.setMessageConverter(new JacksonJsonMessageConverter());
		return factory;
	}

}
