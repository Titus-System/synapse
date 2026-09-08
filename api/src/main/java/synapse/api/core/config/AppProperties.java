package synapse.api.core.config;

import java.net.InetAddress;
import java.net.UnknownHostException;

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
 * @param observability logs e traces
 * @param postgres banco de dados
 */
@ConfigurationProperties("app")
@Validated
public record AppProperties(@NotBlank String environment, @NotNull @Valid Service service,
		@NotNull @Valid Observability observability, @NotNull @Valid Postgres postgres) {

	/**
	 * @param name nome do serviço, no envelope de log e nas métricas
	 * @param description descrição exibida na documentação da API
	 * @param publicUrl URL pública, para links absolutos
	 * @param version versão, no envelope de log
	 */
	public record Service(@NotBlank String name, String description, @NotBlank String publicUrl,
			@NotBlank String version) {
	}

	/**
	 * @param logLevel nível mínimo emitido
	 * @param logPath diretório dos logs estruturados
	 * @param traceSampleRate fração das requisições amostradas para trace
	 * @param otlpEndpoint endpoint OTLP do Alloy
	 * @param host instância onde o processo roda; cai no hostname da máquina se vazio
	 */
	public record Observability(@NotBlank @Pattern(regexp = "TRACE|DEBUG|INFO|WARN|ERROR|FATAL|OFF",
			message = "deve ser um nível do Logback: TRACE, DEBUG, INFO, WARN, ERROR, FATAL ou OFF") String logLevel,

			@NotBlank String logPath,

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

	public record Postgres(@NotBlank String host, @Positive int port, @NotBlank String user, @NotBlank String password,
			@NotBlank String database) {

		public String jdbcUrl() {
			return "jdbc:postgresql://%s:%d/%s".formatted(this.host, this.port, this.database);
		}

	}

}
