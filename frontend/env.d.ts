/// <reference types="vite/client" />

/**
 * Types for environment variables — holds no value (that's `.env`).
 * Gives autocomplete and makes type-check catch a misspelled name.
 * The only file allowed to read these variables is `src/config/env.ts`.
 */
interface ImportMetaEnv {
  /** API base. Absolute URL or '/...' path. Default: '/api'. */
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
