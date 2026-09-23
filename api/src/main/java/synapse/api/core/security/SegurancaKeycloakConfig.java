package synapse.api.core.security;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.autoconfigure.condition.ConditionalOnWebApplication;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.Customizer;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.security.oauth2.jwt.JwtValidators;
import org.springframework.security.oauth2.jwt.NimbusJwtDecoder;
import org.springframework.security.web.SecurityFilterChain;

import jakarta.servlet.DispatcherType;
import jakarta.servlet.http.HttpServletResponse;

import synapse.api.core.config.AppProperties;

@Configuration
@ConditionalOnWebApplication(type = ConditionalOnWebApplication.Type.SERVLET)
@ConditionalOnProperty(name = "app.keycloak.enabled", havingValue = "true", matchIfMissing = true)
public class SegurancaKeycloakConfig {

	@Bean
	SecurityFilterChain cadeiaDeFiltros(HttpSecurity http) throws Exception {
		return http.csrf(csrf -> csrf.disable())
			.cors(Customizer.withDefaults())
			.authorizeHttpRequests(autorizacao -> autorizacao.dispatcherTypeMatchers(DispatcherType.ERROR)
				.permitAll()
				.requestMatchers("/actuator/health", "/health", "/metrics", "/docs/**", "/redocly", "/openapi/**",
						"/swagger-ui/**", "/v3/api-docs/**")
				.permitAll()
				.anyRequest()
				.authenticated())
			.exceptionHandling(excecoes -> excecoes
				.authenticationEntryPoint((requisicao, resposta, excecao) -> escreverErro(resposta,
						HttpServletResponse.SC_UNAUTHORIZED, "nao_autenticado", "Sessão ausente ou expirada."))
				.accessDeniedHandler((requisicao, resposta, excecao) -> escreverErro(resposta,
						HttpServletResponse.SC_FORBIDDEN, "sem_permissao", "Você não tem permissão para esta ação.")))
			.oauth2ResourceServer(oauth2 -> oauth2.jwt(Customizer.withDefaults()))
			.build();
	}

	@Bean
	JwtDecoder decodificadorJwt(AppProperties properties) {
		NimbusJwtDecoder decodificador = NimbusJwtDecoder.withJwkSetUri(properties.keycloak().jwkSetUri()).build();
		decodificador.setJwtValidator(JwtValidators.createDefaultWithIssuer(properties.keycloak().issuerUri()));
		return decodificador;
	}

	private static void escreverErro(HttpServletResponse resposta, int status, String codigo, String mensagem)
			throws java.io.IOException {
		resposta.setStatus(status);
		resposta.setContentType("application/json");
		resposta.getWriter().write("{\"codigo\":\"%s\",\"mensagem\":\"%s\"}".formatted(codigo, mensagem));
	}

}
