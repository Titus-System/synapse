package synapse.api.core.security;

import java.util.UUID;

/** Identidade local associada à sessão autenticada. */
public record AcessoDoUsuario(UUID usuarioId, boolean auditor) {
}
