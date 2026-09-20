package synapse.api.core.web;

import java.util.List;

import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.CorsRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

import synapse.api.core.config.AppProperties;

/**
 * Libera o frontend, servido em domínio próprio, a chamar a api pelo navegador. Os
 * métodos e cabeçalhos são os que o contrato em {@code contracts/http/} expõe; a lista de
 * origens vem do ambiente (skill {@code configuration}).
 */
@Configuration
class CorsConfig implements WebMvcConfigurer {

	private final AppProperties properties;

	CorsConfig(AppProperties properties) {
		this.properties = properties;
	}

	@Override
	public void addCorsMappings(CorsRegistry registry) {
		List<String> origens = this.properties.cors().allowedOrigins();
		if (origens.isEmpty()) {
			return;
		}
		registry.addMapping("/**")
			.allowedOrigins(origens.toArray(String[]::new))
			.allowedMethods("GET", "POST")
			.allowedHeaders("Accept", "Content-Type")
			.allowCredentials(false);
	}

}
