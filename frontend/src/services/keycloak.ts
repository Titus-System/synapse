import Keycloak from 'keycloak-js'
import { config } from '@/config/env'

let clienteKeycloak: Keycloak | undefined

function obterClienteKeycloak(): Keycloak {
  clienteKeycloak ??= new Keycloak({
    url: config.keycloakUrl,
    realm: config.keycloakRealm,
    clientId: config.keycloakClientId,
  })
  return clienteKeycloak
}

function urlDeRetorno(caminhoDeRetorno?: string): string {
  const origemDaAplicacao = new URL(config.baseUrl, window.location.origin)

  if (!caminhoDeRetorno?.startsWith('/')) return origemDaAplicacao.toString()

  return new URL(caminhoDeRetorno, origemDaAplicacao.origin).toString()
}

export async function inicializarKeycloak(): Promise<boolean> {
  return obterClienteKeycloak().init({
    onLoad: 'check-sso',
    checkLoginIframe: false,
    pkceMethod: 'S256',
    silentCheckSsoRedirectUri: new URL(`${config.baseUrl}silent-check-sso.html`, window.location.origin).toString(),
  })
}

export async function obterTokenDeAcesso(): Promise<string | undefined> {
  const cliente = obterClienteKeycloak()
  if (!cliente.token) return undefined

  try {
    await cliente.updateToken(30)
  } catch (error) {
    // O adaptador limpa o token quando o refresh é rejeitado por sessão inválida.
    if (!cliente.token) return undefined
    throw error
  }
  return cliente.token
}

export async function iniciarLogin(caminhoDeRetorno?: string): Promise<void> {
  await obterClienteKeycloak().login({ redirectUri: urlDeRetorno(caminhoDeRetorno) })
}

export async function iniciarLogout(): Promise<void> {
  const cliente = obterClienteKeycloak()
  cliente.clearToken()
  await cliente.logout({ redirectUri: urlDeRetorno() })
}

export function limparTokenDoKeycloak(): void {
  obterClienteKeycloak().clearToken()
}
