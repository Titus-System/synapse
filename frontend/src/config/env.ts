export const config = {
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL ?? '/api',
  baseUrl: import.meta.env.BASE_URL,
  keycloakClientId: import.meta.env.VITE_KEYCLOAK_CLIENT_ID ?? 'synapse-frontend',
  keycloakRealm: import.meta.env.VITE_KEYCLOAK_REALM ?? 'synapse',
  keycloakUrl: import.meta.env.VITE_KEYCLOAK_URL ?? 'http://localhost:8081',
}
