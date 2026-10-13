import { readFileSync } from 'node:fs'
import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

const getStateBaseline = Object.keys(JSON.parse(
  readFileSync(new URL('./tests/getStateBudget.json', import.meta.url), 'utf8'),
))

export default defineConfig([
  globalIgnores(['dist', 'playwright-report', 'test-results', 'blob-report']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
  },
  {
    files: ['src/**/*.tsx'],
    ignores: [
      'src/stores/**',
      'src/features/*/store/**',
      'src/features/*/store.ts',
      ...getStateBaseline,
    ],
    rules: {
      'no-restricted-syntax': ['error', {
        selector: "MemberExpression[property.name='getState'][object.name=/^use(?:[A-Z]\\w*)?Store$/]",
        message: 'Read store state with a selector, or move this logic into a slice or feature action.',
      }],
    },
  },
])
