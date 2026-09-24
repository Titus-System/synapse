package synapse.api.core.security;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.core.Authentication;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import synapse.api.core.config.AppProperties;

@Service
public class UsuarioAtual {

	private final JdbcTemplate jdbc;

	private final AppProperties properties;

	public UsuarioAtual(JdbcTemplate jdbc, AppProperties properties) {
		this.jdbc = jdbc;
		this.properties = properties;
	}

	@Transactional
	public AcessoDoUsuario obter() {
		Authentication autenticacao = SecurityContextHolder.getContext().getAuthentication();
		if (autenticacao == null || !(autenticacao.getPrincipal() instanceof Jwt token)) {
			return usuarioDeDesenvolvimento();
		}

		String subject = Objects.requireNonNull(token.getSubject());
		String login = textoDoToken(token, "preferred_username", subject);
		String nome = textoDoToken(token, "name", login);
		UUID usuarioId = encontrarOuCriar(subject, login, nome);
		return new AcessoDoUsuario(usuarioId, temPapelDeAuditor(token));
	}

	private AcessoDoUsuario usuarioDeDesenvolvimento() {
		if (this.properties.keycloak().enabled()) {
			throw new IllegalStateException("Sessão autenticada não encontrada.");
		}
		List<UUID> usuarios = this.jdbc
			.queryForList("SELECT id FROM usuarios WHERE ativo = true ORDER BY criado_em, id LIMIT 1", UUID.class);
		if (usuarios.isEmpty()) {
			throw new IllegalStateException("Nenhum usuário ativo disponível.");
		}
		return new AcessoDoUsuario(usuarios.getFirst(), false);
	}

	private UUID encontrarOuCriar(String subject, String login, String nome) {
		List<UUID> usuarios = this.jdbc.queryForList("""
				SELECT id FROM usuarios
				WHERE keycloak_sub = ? OR (keycloak_sub IS NULL AND login = ?)
				ORDER BY criado_em, id LIMIT 1
				""", UUID.class, subject, login);
		Timestamp agora = Timestamp.from(Instant.now());
		if (!usuarios.isEmpty()) {
			UUID usuarioId = usuarios.getFirst();
			int atualizados = this.jdbc.update("""
					UPDATE usuarios SET keycloak_sub = ?, nome = ?, ultimo_login_em = ?
					WHERE id = ? AND ativo = true
					""", subject, nome, agora, usuarioId);
			if (atualizados == 0) {
				throw new AccessDeniedException("Conta inativa.");
			}
			return usuarioId;
		}
		return Objects.requireNonNull(this.jdbc.queryForObject("""
				INSERT INTO usuarios (login, senha_hash, nome, papel, ativo, criado_em, ultimo_login_em, keycloak_sub)
				VALUES (?, NULL, ?, 'profissional_rh', true, ?, ?, ?) RETURNING id
				""", UUID.class, login, nome, agora, agora, subject));
	}

	private static String textoDoToken(Jwt token, String campo, String padrao) {
		String valor = token.getClaimAsString(campo);
		return valor == null || valor.isBlank() ? padrao : valor;
	}

	private static boolean temPapelDeAuditor(Jwt token) {
		Map<String, Object> acessoDoRealm = token.getClaimAsMap("realm_access");
		if (acessoDoRealm == null || !(acessoDoRealm.get("roles") instanceof List<?> papeis)) {
			return false;
		}
		return papeis.stream().anyMatch("auditor"::equals);
	}

}
