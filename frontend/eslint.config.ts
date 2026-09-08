import { globalIgnores } from 'eslint/config'
import { defineConfigWithVueTs, vueTsConfigs } from '@vue/eslint-config-typescript'
import pluginVue from 'eslint-plugin-vue'
import pluginVitest from '@vitest/eslint-plugin'
import pluginOxlint from 'eslint-plugin-oxlint'
import skipFormatting from 'eslint-config-prettier/flat'

// To allow more languages other than `ts` in `.vue` files, uncomment the following lines:
// import { configureVueProject } from '@vue/eslint-config-typescript'
// configureVueProject({ scriptLangs: ['ts', 'tsx'] })
// More info at https://github.com/vuejs/eslint-config-typescript/#advanced-setup

export default defineConfigWithVueTs(
  {
    name: 'app/files-to-lint',
    files: ['**/*.{vue,ts,mts,tsx}'],
  },

  globalIgnores(['**/dist/**', '**/dist-ssr/**', '**/coverage/**']),

  ...pluginVue.configs['flat/essential'],
  vueTsConfigs.recommended,

  {
    ...pluginVitest.configs.recommended,
    files: ['src/**/__tests__/*', 'src/**/*.spec.ts'],
  },

  // Boundary between features: what keeps three people working in parallel
  // without coupling one feature to another. See src/features/README.md.
  {
    name: 'app/feature-boundaries',
    files: ['src/features/*/**'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['@/features/*'],
              message:
                'A feature must not import from another feature. Promote the code to shared src/ (components, composables, services, types).',
            },
          ],
        },
      ],
    },
  },

  // The dependency points one way only: feature -> shared.
  {
    name: 'app/shared-never-depends-on-features',
    files: ['src/{components,composables,config,services,stores,layouts,types,views,router}/**'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['@/features/*', '**/features/*'],
              message:
                'Shared code cannot depend on a feature — that reverses the dependency direction and creates a cycle.',
            },
          ],
        },
      ],
    },
  },

  // Environment variables come in through one place: src/config/env.ts.
  {
    name: 'app/env-single-entry',
    files: ['src/**/*.{ts,vue}'],
    ignores: ['src/config/env.ts'],
    rules: {
      'no-restricted-syntax': [
        'error',
        {
          selector: 'MemberExpression[object.type="MetaProperty"][property.name="env"]',
          message:
            "Don't read import.meta.env directly. Import `config` from @/config/env — the single entry point for environment variables.",
        },
      ],
    },
  },

  ...pluginOxlint.buildFromOxlintConfigFile('.oxlintrc.json'),

  skipFormatting,
)
