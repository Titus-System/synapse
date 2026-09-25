import { fileURLToPath } from 'node:url'
import { mergeConfig, defineConfig, configDefaults } from 'vitest/config'
import viteConfig from './vite.config'

export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: 'jsdom',
      exclude: [...configDefaults.exclude, 'e2e/**'],
      root: fileURLToPath(new URL('./', import.meta.url)),
      // Sem isto o `.env` da máquina entra no teste: um dev que aponte
      // VITE_API_BASE_URL para a api local quebra as asserções de URL,
      // enquanto a CI (que não tem `.env`) continua verde.
      env: {
        VITE_API_BASE_URL: '/api',
        VITE_KEYCLOAK_URL: 'http://localhost:8081',
        VITE_KEYCLOAK_REALM: 'synapse',
        VITE_KEYCLOAK_CLIENT_ID: 'synapse-frontend',
      },
    },
  }),
)
