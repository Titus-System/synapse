package synapse.api.core.security;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.autoconfigure.condition.ConditionalOnWebApplication;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.web.SecurityFilterChain;

/**
 * Mantém o ambiente local e os testes sem autenticação quando o Keycloak está
 * desabilitado.
 */
@Configuration
@ConditionalOnWebApplication(type = ConditionalOnWebApplication.Type.SERVLET)
@ConditionalOnProperty(name = "app.keycloak.enabled", havingValue = "false", matchIfMissing = true)
class SegurancaSemKeycloakConfig {

	@Bean
	SecurityFilterChain cadeiaDeFiltrosSemKeycloak(HttpSecurity http) throws Exception {
		return http.csrf(csrf -> csrf.disable())
			.authorizeHttpRequests(autorizacao -> autorizacao.anyRequest().permitAll())
			.build();
	}

}
