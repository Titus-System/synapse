package synapse.api.core.security;

import java.sql.ResultSet;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.stream.Stream;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;
import org.junit.jupiter.params.provider.EnumSource;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;

import synapse.api.core.config.AppProperties;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class UsuarioAtualTests {

	private final JdbcTemplate jdbc = mock(JdbcTemplate.class);

	private final AppProperties properties = mock(AppProperties.class);

	private final UsuarioAtual usuarioAtual = new UsuarioAtual(this.jdbc, this.properties);

	@AfterEach
	void limparSessao() {
		SecurityContextHolder.clearContext();
	}

	static Stream<Arguments> papeisValidos() {
		return Stream.of(Arguments.of(List.of("profissional-rh"), PapelDoUsuario.PROFISSIONAL_RH),
				Arguments.of(List.of("auditor"), PapelDoUsuario.AUDITOR),
				Arguments.of(List.of("default-roles-synapse", "offline_access", "profissional-rh"),
						PapelDoUsuario.PROFISSIONAL_RH),
				Arguments.of(List.of("default-roles-synapse", "offline_access", "auditor"), PapelDoUsuario.AUDITOR));
	}

	@ParameterizedTest
	@MethodSource("papeisValidos")
	void resolvePapelAntesDeCriarContaComPapelCorrespondente(List<String> papeis, PapelDoUsuario esperado) {
		autenticar(Map.of("roles", papeis));
		UUID id = UUID.randomUUID();
		when(this.jdbc.queryForList(anyString(), eq(UUID.class), eq("subject-a"), eq("login-a"))).thenReturn(List.of());
		when(this.jdbc.queryForObject(contains("INSERT INTO usuarios"), eq(UUID.class), eq("login-a"), eq("Nome A"),
				eq(esperado.paraColuna()), any(), any(), eq("subject-a")))
			.thenReturn(id);

		assertThat(this.usuarioAtual.obter()).isEqualTo(new AcessoDoUsuario(id, esperado));
		verify(this.jdbc).queryForObject(contains("INSERT INTO usuarios"), eq(UUID.class), eq("login-a"), eq("Nome A"),
				eq(esperado.paraColuna()), any(), any(), eq("subject-a"));
	}

	static Stream<Object> papeisInvalidos() {
		return Stream.of(Map.of(), Map.of("roles", List.of()), Map.of("roles", List.of("offline_access")),
				Map.of("roles", List.of("profissional-rh", "auditor")),
				Map.of("roles", List.of("profissional-rh", "auditor", "offline_access")),
				Map.of("roles", "profissional-rh"), "realm-invalido");
	}

	@ParameterizedTest
	@MethodSource("papeisInvalidos")
	void rejeitaSemQualquerConsultaInsertOuUpdateLocal(Object realm) {
		autenticar(realm);
		assertThatThrownBy(this.usuarioAtual::obter).isInstanceOf(AccessDeniedException.class);
		verifyNoInteractions(this.jdbc);
	}

	@Test
	void realmAusenteTambemNaoTocaBanco() {
		SecurityContextHolder.getContext()
			.setAuthentication(new JwtAuthenticationToken(
					Jwt.withTokenValue("teste").header("alg", "RS256").subject("subject-a").build()));
		assertThatThrownBy(this.usuarioAtual::obter).isInstanceOf(AccessDeniedException.class);
		verifyNoInteractions(this.jdbc);
	}

	@Test
	void contaExistenteUsaSubEPapelDoTokenSemSincronizarPapelLocal() {
		autenticar(Map.of("roles", List.of("auditor")));
		UUID id = UUID.randomUUID();
		when(this.jdbc.queryForList(anyString(), eq(UUID.class), eq("subject-a"), eq("login-a")))
			.thenReturn(List.of(id));
		when(this.jdbc.update(contains("UPDATE usuarios"), eq("subject-a"), eq("Nome A"), any(), eq(id))).thenReturn(1);
		assertThat(this.usuarioAtual.obter()).isEqualTo(new AcessoDoUsuario(id, PapelDoUsuario.AUDITOR));
		verify(this.jdbc).update(argThat(sql -> !sql.contains("papel")), eq("subject-a"), eq("Nome A"), any(), eq(id));
	}

	@ParameterizedTest
	@EnumSource(PapelDoUsuario.class)
	void desenvolvimentoLeOPapelCanonicoLocal(PapelDoUsuario papel) throws Exception {
		when(this.properties.keycloak()).thenReturn(new AppProperties.Keycloak(false, "issuer", "jwks"));
		UUID id = UUID.randomUUID();
		ResultSet linha = mock(ResultSet.class);
		when(linha.getObject("id", UUID.class)).thenReturn(id);
		when(linha.getString("papel")).thenReturn(papel.paraColuna());
		when(this.jdbc.query(contains("SELECT id, papel"),
				org.mockito.ArgumentMatchers.<RowMapper<AcessoDoUsuario>>any()))
			.thenAnswer(invocacao -> {
				RowMapper<AcessoDoUsuario> mapper = invocacao.getArgument(1);
				return List.of(mapper.mapRow(linha, 0));
			});
		assertThat(this.usuarioAtual.obter()).isEqualTo(new AcessoDoUsuario(id, papel));
	}

	private static void autenticar(Object realm) {
		Jwt token = Jwt.withTokenValue("teste")
			.header("alg", "RS256")
			.subject("subject-a")
			.claim("preferred_username", "login-a")
			.claim("name", "Nome A")
			.claim("realm_access", realm)
			.build();
		SecurityContextHolder.getContext().setAuthentication(new JwtAuthenticationToken(token));
	}

}
