package synapse.api.core.config;

import java.net.InetAddress;
import java.net.UnknownHostException;
import java.time.Duration;
import java.util.List;

import jakarta.validation.Valid;
import jakarta.validation.constraints.DecimalMax;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Positive;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.util.StringUtils;
import org.springframework.validation.annotation.Validated;

/**
 * Todas as configurações de ambiente da API, vindas do {@code .env}.
 *
 * @param environment ambiente de execução; define o perfil ativo
 * @param service identidade do serviço
 * @param cors origens de navegador autorizadas a chamar a api
 * @param observability logs e traces
 * @param postgres banco de dados
 * @param rabbitmq broker de mensageria
 * @param sse stream de acompanhamento do job
 * @param outbox publicação dos eventos gravados no outbox transacional
 */
@ConfigurationProperties("app")
@Validated
public record AppProperties(@NotBlank String environment, @NotNull @Valid Service service, @NotNull @Valid Cors cors,
		@NotNull @Valid Observability observability, @NotNull @Valid Postgres postgres,
		@NotNull @Valid Rabbitmq rabbitmq, @NotNull @Valid Sse sse, @NotNull @Valid Outbox outbox) {

	/**
	 * Configura a identidade pública do serviço.
	 *
	 * @param name nome do serviço, no envelope de log e nas métricas
	 * @param description descrição exibida na documentação da API
	 * @param publicUrl URL pública, para links absolutos
	 * @param version versão, no envelope de log
	 */
	public record Service(@NotBlank String name, String description, @NotBlank String publicUrl,
			@NotBlank String version) {
	}

	/**
	 * Configura a política de CORS aplicada pela api.
	 *
	 * @param allowedOrigins origens de navegador autorizadas a chamar a api, separadas
	 * por vírgula. Cada item é esquema + host + porta, sem caminho nem barra final; a
	 * lista vazia não libera origem nenhuma
	 */
	public record Cors(@NotNull List<@NotBlank String> allowedOrigins) {
	}

	/**
	 * Configura os dados técnicos de observabilidade.
	 *
	 * @param logLevel nível mínimo emitido
	 * @param traceSampleRate fração das requisições amostradas para trace
	 * @param otlpEndpoint endpoint OTLP do Alloy
	 * @param host instância onde o processo roda; cai no hostname da máquina se vazio
	 */
	public record Observability(@NotBlank @Pattern(regexp = "TRACE|DEBUG|INFO|WARN|ERROR|FATAL|OFF",
			message = "deve ser um nível do Logback: TRACE, DEBUG, INFO, WARN, ERROR, FATAL ou OFF") String logLevel,

			@NotNull @DecimalMin("0.0") @DecimalMax("1.0") Double traceSampleRate,

			@NotBlank String otlpEndpoint,

			@NotBlank String host) {

		public Observability {
			host = StringUtils.hasLength(host) ? host : localHostname();
		}

		private static String localHostname() {
			try {
				return InetAddress.getLocalHost().getHostName();
			}
			catch (UnknownHostException ex) {
				return "unknown";
			}
		}

	}

	/**
	 * @param host endereço do Postgres
	 * @param port porta do Postgres
	 * @param database nome do banco, compartilhado pelos três serviços
	 * @param user usuário com que a aplicação opera
	 * @param password senha do usuário de runtime
	 * @param owner dono do schema, usado apenas para migrar
	 * @param roles nomes dos usuários dos outros serviços, para os GRANT das migrations
	 */
	public record Postgres(@NotBlank String host, @Positive int port, @NotBlank String database, @NotBlank String user,
			@NotBlank String password, @NotNull @Valid Owner owner, @NotNull @Valid Roles roles) {

		public String jdbcUrl() {
			return "jdbc:postgresql://%s:%d/%s".formatted(this.host, this.port, this.database);
		}

		/**
		 * @param user usuário dono do schema
		 * @param password senha do dono
		 */
		public record Owner(@NotBlank String user, @NotBlank String password) {
		}

		/**
		 * Nome do usuário de banco de cada serviço que não é a api. A api nunca conecta
		 * com eles, mas precisa dos nomes porque executa as migrations.
		 *
		 * @param codegen usuário de banco do codegen
		 * @param worker usuário de banco do worker
		 */
		public record Roles(@NotBlank String codegen, @NotBlank String worker) {
		}

	}

	/**
	 * @param host endereço do RabbitMQ
	 * @param port porta do RabbitMQ
	 * @param user usuário com que a aplicação conecta
	 * @param password senha do usuário
	 * @param vhost virtual host do broker
	 */
	public record Rabbitmq(@NotBlank String host, @Positive int port, @NotBlank String user, @NotBlank String password,
			@NotBlank String vhost) {
	}

	/**
	 * @param heartbeat intervalo entre comentários SSE enviados a todo emissor conectado,
	 * para manter a conexão viva através de proxy e detectar cliente que saiu
	 * @param timeout tempo máximo que um emissor fica aberto sem atividade antes do
	 * container encerrá-lo
	 */
	public record Sse(@NotNull Duration heartbeat, @NotNull Duration timeout) {
	}

	/**
	 * @param enabled liga o poller que publica os eventos pendentes; desligado, os
	 * eventos continuam sendo gravados e ficam pendentes
	 * @param pollInterval pausa entre o fim de um ciclo do poller e o início do seguinte;
	 * é a latência somada entre o commit de um evento e sua publicação
	 */
	public record Outbox(boolean enabled, @NotNull Duration pollInterval) {
	}

}
