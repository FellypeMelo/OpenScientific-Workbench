import { configDefaults, defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './vitest.setup.ts',
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
    // `tests/e2e/**` holds Playwright specs (`@playwright/test`), not Vitest
    // specs -- without this exclusion, Vitest's default include glob also
    // picks them up and fails to resolve `@playwright/test` inside the unit
    // test runner (see docs/planning/execution_plan_gap_closure.md Fase 5).
    // Spread `configDefaults.exclude` rather than replacing it outright --
    // setting `exclude` overrides Vitest's own default patterns instead of
    // merging with them.
    exclude: [...configDefaults.exclude, 'tests/e2e/**'],
    coverage: {
      exclude: ['tests/e2e/**'],
    },
  },
})
