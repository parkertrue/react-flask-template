import { beforeAll, describe, it, expect } from 'vitest'
import { ESLint } from 'eslint'
import tseslint from 'typescript-eslint'

// The lint rules are config, and config fails silently: a later block
// replaces an earlier one's options, and a rule whose file glob or selector
// stops matching reports nothing. These plant code in made-up files and lint
// it with the real eslint.config.js, as tests/unit/test_import_rules.py and
// test_assertions.py do for the backend. The planted code is untyped, so
// the rules that read types are off for it; 'TypeScript rules' below
// plants typed code with them on.
const eslint = new ESLint({
  overrideConfig: [
    tseslint.configs.disableTypeChecked,
    { files: ['src/**/*.{test,spec}.{ts,tsx}'], rules: { 'vitest/unbound-method': 'off' } },
  ],
})
// Types come from the project, which knows only files on disk, so typed
// code is planted under the path of a real file of the kind it stands for
const typedEslint = new ESLint()
const APP_FILE = 'src/utils/validation.ts'
const COMPONENT_FILE = 'src/pages/HomePage.tsx'
const TEST_FILE = 'src/utils/__tests__/validation.test.ts'

// The first lint loads every plugin, and the first typed lint of each
// project's file builds that project's program, either of which on a busy
// machine takes longer than a test's 5 s, so they happen here, with time
// to spare
beforeAll(async () => {
  await eslint.lintText('\n', { filePath: 'src/x.ts' })
  for (const filePath of [APP_FILE, COMPONENT_FILE, TEST_FILE]) {
    await typedEslint.lintText('\n', { filePath })
  }
}, 120_000)

const ruleIds = async (filePath: string, code: string, linter = eslint) => {
  const results = await linter.lintText(`${code}\n`, { filePath })
  return results.flatMap(result => result.messages.map(message => message.ruleId))
}

describe('import rules', () => {
  it.each([
    // A relative path that leaves its folder, however it is written
    ['src/features/notes/x.ts', "import '../health/useHealth'", 'local/relative-within-folder'],
    ['src/auth/x.ts', "import '../routes'", 'local/relative-within-folder'],
    ['src/auth/x.ts', "export * from '../features/notes/useNotes'", 'local/relative-within-folder'],
    ['src/utils/x.ts', "import('../pages/HomePage')", 'local/relative-within-folder'],
    ['src/routes.tsx', "import './pages/HomePage'", 'local/relative-within-folder'],
    ['src/components/layout/x.ts', "import '../../features/notes/useNotes'", 'no-restricted-imports'],
    // The one-way rules on the @/ alias
    ['src/utils/x.ts', "import '@/features/notes/useNotes'", 'no-restricted-imports'],
    ['src/auth/x.ts', "import '@/routes'", 'no-restricted-imports'],
    ['src/components/x.ts', "import '@/pages/HomePage'", 'no-restricted-imports'],
    ['src/features/notes/x.ts', "import '@/features/health/useHealth'", 'no-restricted-imports'],
    ['src/features/notes/x.ts', "import '@/pages/HomePage'", 'no-restricted-imports'],
    ['src/features/notes/x.ts', "import '@/routes'", 'no-restricted-imports'],
    ['src/features/notes/__tests__/x.ts', "import '@/features/health/useHealth'", 'no-restricted-imports'],
    ['src/legal.ts', "import '@/features/notes/useNotes'", 'no-restricted-imports'],
    ['src/styles/__tests__/x.test.ts', "import '@/pages/HomePage'", 'no-restricted-imports'],
    ['src/test/x.ts', "import '@/features/notes/useNotes'", 'no-restricted-imports'],
    ['src/test/integration/x.test.tsx', "import '@/pages/HomePage'", 'no-restricted-imports'],
  ])('refuses %s: %s', async (filePath, code, ruleId) => {
    expect(await ruleIds(filePath, code)).toContain(ruleId)
  })

  it.each([
    ['src/features/notes/x.ts', "import './useNotes'"],
    ['src/features/notes/x.ts', "import '@/auth/useAuth'"],
    ['src/features/notes/__tests__/x.ts', "import '../useNotes'"],
    ['src/features/notes/__tests__/x.ts', "import '@/routes'"],
    ['src/components/layout/x.ts', "import '../forms/FormField'"],
    ['src/test/integration/x.ts', "import '../fixtures'"],
    // A shared integration test renders the whole app
    ['src/test/integration/x.ts', "import '@/routes'"],
    ['src/__tests__/x.ts', "import '../routes'"],
    ['src/pages/x.ts', "import '@/features/notes/NotesPage'"],
  ])('allows %s: %s', async (filePath, code) => {
    expect(await ruleIds(filePath, code)).toEqual([])
  })
})

describe('code rules', () => {
  it.each([
    // Form controls go through FormField, in .ts files as in .tsx
    ['src/pages/x.tsx', 'export const X = () => <input />', 'no-restricted-syntax'],
    ['src/features/notes/x.tsx', 'export const X = () => <textarea />', 'no-restricted-syntax'],
    ['src/pages/__tests__/x.test.tsx', 'render(<select />)', 'no-restricted-syntax'],
    // Markup rules hold everywhere, FormField's folder and tests included
    ['src/pages/x.tsx', 'export const X = () => <p dangerouslySetInnerHTML={{ __html: x }} />', 'no-restricted-syntax'],
    ['src/pages/x.tsx', 'export const X = () => <p data-testid="x" />', 'no-restricted-syntax'],
    ['src/pages/x.tsx', 'export const X = () => <button disabled />', 'no-restricted-syntax'],
    ['src/features/notes/x.tsx', 'export const X = () => <form onSubmit={f} />', 'no-restricted-syntax'],
    ['src/components/forms/x.tsx', 'export const X = () => <input disabled />', 'no-restricted-syntax'],
    ['src/pages/__tests__/x.test.tsx', "screen.getByTestId('x')", 'no-restricted-syntax'],
    ['src/pages/__tests__/x.test.tsx', "expect(x).toHaveClass('x')", 'no-restricted-syntax'],
    ['e2e/x.spec.ts', "page.getByTestId('x')", 'no-restricted-syntax'],
    ['e2e/x.spec.ts', "expect(x).toHaveClass('x')", 'no-restricted-syntax'],
    ['src/pages/__tests__/x.test.tsx', "vi.mock('@/auth/storage')", 'no-restricted-syntax'],
    ['src/auth/__tests__/x.test.tsx', "vi.mock('../storage')", 'no-restricted-syntax'],
    // The session is read and written in auth/storage.ts alone
    ['src/features/notes/x.ts', "localStorage.getItem('x')", 'no-restricted-globals'],
    ['src/auth/x.ts', 'sessionStorage.clear()', 'no-restricted-globals'],
    ['src/pages/x.tsx', 'window.localStorage.clear()', 'no-restricted-properties'],
    // Leftovers and strings run as code
    ['src/utils/x.ts', "console.log('x')", 'no-console'],
    ['src/utils/x.ts', '// TODO: x', 'no-warning-comments'],
    ['src/utils/x.ts', "eval('x')", 'no-eval'],
    ['src/utils/x.ts', "setTimeout('x()')", 'no-implied-eval'],
    ['src/utils/x.ts', "new Function('x')", 'no-new-func'],
    // TanStack Query: a key that misses what the fetch uses would serve one
    // note's data for another, and a client made on every render forgets
    // its cache
    ['src/features/notes/x.ts', "export const useX = id => useQuery({ queryKey: ['x'], queryFn: () => get(id) })", '@tanstack/query/exhaustive-deps'],
    ['src/auth/x.tsx', "import { QueryClient, QueryClientProvider } from '@tanstack/react-query'; export function X() { const client = new QueryClient(); return <QueryClientProvider client={client} /> }", '@tanstack/query/stable-query-client'],
    ['src/pages/x.ts', "import { useQuery } from '@tanstack/react-query'; export function useX() { const { data, ...rest } = useQuery({ queryKey: ['x'], queryFn: get }); return [data, rest] }", '@tanstack/query/no-rest-destructuring'],
  ])('refuses %s: %s', async (filePath, code, ruleId) => {
    expect(await ruleIds(filePath, code)).toContain(ruleId)
  })

  it.each([
    ['src/components/forms/x.tsx', 'export const X = () => <input />'],
    ['src/pages/x.tsx', 'export const X = () => <button aria-disabled="true" />'],
    ['src/pages/x.tsx', 'export const X = f => <form noValidate onSubmit={f} />'],
    ['src/pages/__tests__/x.test.tsx', "import { vi } from 'vitest'; vi.mock('@/api/api')"],
    ['src/auth/storage.ts', "localStorage.getItem('x')"],
    ['src/test/x.ts', 'window.localStorage.clear()'],
    ['src/auth/__tests__/x.test.ts', 'localStorage.clear()'],
    ['e2e/x.ts', "console.log('x')"],
  ])('allows %s: %s', async (filePath, code) => {
    expect(await ruleIds(filePath, code)).toEqual([])
  })
})

describe('test rules', () => {
  it.each([
    // Unit tests, named .test or .spec, as Vitest runs both
    ['src/x/__tests__/a.test.tsx', "it('a', () => { if (x) expect(x).toBe(1) })", 'vitest/no-conditional-expect'],
    ['src/x/__tests__/a.spec.tsx', "it('a', () => { if (x) expect(x).toBe(1) })", 'vitest/no-conditional-expect'],
    ['src/x/__tests__/a.test.ts', "it('a', () => { if (x) run(); expect(y).toBe(1) })", 'vitest/no-conditional-in-test'],
    ['src/x/__tests__/a.test.ts', "it('a', () => { run() })", 'vitest/expect-expect'],
    ['src/x/__tests__/a.test.ts', "it.skip('a', () => { expect(x).toBe(1) })", 'vitest/no-disabled-tests'],
    ['src/x/__tests__/a.test.ts', "it.only('a', () => { expect(x).toBe(1) })", 'vitest/no-focused-tests'],
    ['src/x/__tests__/a.test.ts', "// it('a', () => { expect(x).toBe(1) })", 'vitest/no-commented-out-tests'],
    ['src/x/__tests__/a.test.ts', "it('a', () => { expect(x).toBeDefined() })", 'vitest/no-restricted-matchers'],
    ['src/x/__tests__/a.test.ts', "it('a', () => { expect(x).toBeTruthy() })", 'vitest/no-restricted-matchers'],
    ['src/x/__tests__/a.test.ts', "it('a', () => { expect(x).not.toBeNull() })", 'vitest/no-restricted-matchers'],
    ['src/x/__tests__/a.test.ts', "it('a', () => { expect(x).toBeOneOf([1, 2]) })", 'vitest/no-restricted-matchers'],
    ['src/x/__tests__/a.test.ts', "it('a', () => { expect([400, 422]).toContain(x) })", 'no-restricted-syntax'],
    ['src/x/__tests__/a.test.ts', "it('a', () => { expect(x === 1 || x === 2).toBe(true) })", 'no-restricted-syntax'],
    ['src/components/forms/__tests__/a.test.ts', "it('a', () => { expect([1, 2]).toContainEqual(x) })", 'no-restricted-syntax'],
    // Shared helpers that assert
    ['src/test/x.ts', 'export const check = x => expect([400, 422]).toContain(x)', 'no-restricted-syntax'],
    ['src/test/x.ts', 'export const check = x => expect(x.a || x.b).toBe(true)', 'no-restricted-syntax'],
    ['e2e/helpers.ts', 'export const check = x => expect([400, 422]).toContain(x)', 'no-restricted-syntax'],
    // An assertion that may not run, outside a test's callback
    ['src/test/x.ts', 'export const check = x => { if (x.ok) expect(x.status).toBe(1) }', 'no-restricted-syntax'],
    ['src/test/x.ts', 'export const check = x => { try { run() } catch { expect(x).toBe(1) } }', 'no-restricted-syntax'],
    ['e2e/helpers.ts', 'export const check = x => { if (x.ok) expect(x.status).toBe(1) }', 'no-restricted-syntax'],
    ['e2e/helpers.ts', 'export const check = x => { try { expect(x).toBe(1) } catch { run() } }', 'no-restricted-syntax'],
    ['e2e/helpers.ts', 'export const check = x => (x.ok ? expect(x).toBe(1) : run())', 'no-restricted-syntax'],
    ['src/x/__tests__/a.test.ts', 'const check = x => x.ok && expect(x.status).toBe(1)', 'no-restricted-syntax'],
    ['e2e/x.spec.ts', 'function check(x) { switch (x) { case 1: expect(x).toBe(1) } }', 'no-restricted-syntax'],
    ['e2e/helpers.ts', 'export const check = x => { while (x.more()) expect(x.next()).toBe(1) }', 'no-restricted-syntax'],
    ['src/test/x.ts', 'export const check = x => { do { expect(x.next()).toBe(1) } while (x.more()) }', 'no-restricted-syntax'],
    // An assertion on a constant, or on a choice the test makes itself
    ['src/x/__tests__/a.test.ts', "it('a', () => { run(); expect(true).toBe(true) })", 'no-restricted-syntax'],
    ['e2e/x.spec.ts', "test('a', async () => { await run(); expect('x').toBe('x') })", 'no-restricted-syntax'],
    ['src/x/__tests__/a.test.ts', "it('a', () => { expect(c ? x : 1).toBe(1) })", 'no-restricted-syntax'],
    ['e2e/helpers.ts', 'export const check = (c, x) => expect(c ? x : 1).toBe(1)', 'no-restricted-syntax'],
    ['src/x/__tests__/a.test.ts', `it('a', () => { expect(x).toMatchInlineSnapshot(\`${'\n'.repeat(60)}\`) })`, 'vitest/no-large-snapshots'],
    // End-to-end tests
    ['e2e/x.spec.ts', "test('a', async ({ page }) => { await page.goto('/') })", 'playwright/expect-expect'],
    ['e2e/x.spec.ts', "test('a', async ({ page }) => { if (x) await expect(page).toHaveURL('/') })", 'playwright/no-conditional-in-test'],
    ['e2e/x.spec.ts', "test.skip('a', async ({ page }) => { await expect(page).toHaveURL('/') })", 'playwright/no-skipped-test'],
    ['e2e/x.spec.ts', "test.only('a', async ({ page }) => { await expect(page).toHaveURL('/') })", 'playwright/no-focused-test'],
    ['e2e/x.spec.ts', "test('a', async ({ page }) => { await page.waitForTimeout(1); await expect(page).toHaveURL('/') })", 'playwright/no-wait-for-timeout'],
    ['e2e/x.spec.ts', "test('a', async () => { expect([400, 422]).toContain(x.status()) })", 'no-restricted-syntax'],
    ['e2e/x.spec.ts', "test('a', async () => { expect(x.a || x.b).toBe(true) })", 'no-restricted-syntax'],
    ['e2e/x.spec.ts', "test('a', async ({ page }) => { expect(await page.title()).toBeTruthy() })", 'playwright/no-restricted-matchers'],
    ['e2e/x.spec.ts', "test('a', async ({ page }) => { expect(await page.title()).not.toBeNull() })", 'playwright/no-restricted-matchers'],
  ])('refuses %s: %s', async (filePath, code, ruleId) => {
    expect(await ruleIds(filePath, code)).toContain(ruleId)
  })

  it.each([
    ['src/x/__tests__/a.test.ts', "import { it, expect } from 'vitest'; const x = 1; it('a', () => { expect(x).toBe(1) })"],
    ['src/x/__tests__/a.test.ts', "import { it, expect } from 'vitest'; const x = [1]; it('a', () => { expect([1]).toEqual(x) })"],
    ['src/components/forms/__tests__/a.test.tsx', "import { it, expect } from 'vitest'; const x = <input />; it('a', () => { expect(x).toBe(x) })"],
    ['e2e/x.spec.ts', "import { test, expect } from '@playwright/test'\n\ntest('a', async ({ page }) => { await expect(page).toHaveURL('/') })"],
    // A loop's assert runs on every pass; a finally's failure still fails
    ['e2e/helpers.ts', "import { expect } from '@playwright/test'\n\nexport const check = xs => { for (const x of xs) expect(x).toBe(1) }"],
    ['e2e/helpers.ts', "import { expect } from '@playwright/test'\n\nexport const check = (x, done) => { try { expect(x).toBe(1) } finally { done() } }"],
  ])('allows %s: %s', async (filePath, code) => {
    expect(await ruleIds(filePath, code)).toEqual([])
  })
})

describe('TypeScript rules', () => {
  it.each([
    // tsc checks TypeScript alone
    ['src/utils/x.js', 'export const x = 1', 'no-restricted-syntax'],
    ['src/pages/x.jsx', 'export const X = () => <p />', 'no-restricted-syntax'],
    ['e2e/x.spec.js', 'export const x = 1', 'no-restricted-syntax'],
    ['vite.config.mjs', 'export default {}', 'no-restricted-syntax'],
    // The ways around the type check
    [APP_FILE, 'export const x: any = 1', '@typescript-eslint/no-explicit-any'],
    [APP_FILE, '// @ts-ignore\nexport const x: number = 1', '@typescript-eslint/ban-ts-comment'],
    [APP_FILE, "// @ts-expect-error\nexport const x: number = 'x'", '@typescript-eslint/ban-ts-comment'],
    [APP_FILE, 'export const f = (x: string | null) => x!.length', '@typescript-eslint/no-non-null-assertion'],
    // Rules that read types
    [APP_FILE, 'const f = async () => 1\nexport const g = () => { f() }', '@typescript-eslint/no-floating-promises'],
    [APP_FILE, 'export const f = (x: string) => x ?? 1', '@typescript-eslint/no-unnecessary-condition'],
    [APP_FILE, 'export const f = (x: string) => JSON.parse(x).a', '@typescript-eslint/no-unsafe-member-access'],
    [COMPONENT_FILE, 'export const X = ({ f }: { f: () => Promise<void> }) => <button type="button" onClick={f} />', '@typescript-eslint/no-misused-promises'],
    [TEST_FILE, "import { it, expect } from 'vitest'; const o = { m() { return this } }; it('a', () => { const m = o.m; expect(m()).toBe(o) })", 'vitest/unbound-method'],
  ])('refuses %s: %s', async (filePath, code, ruleId) => {
    expect(await ruleIds(filePath, code, typedEslint)).toContain(ruleId)
  })

  it.each([
    // A count in a message, and a state setter in an arrow
    [APP_FILE, 'export const f = (n: number) => `${n} left`'],
    [COMPONENT_FILE, "import { useState } from 'react'\nexport const X = () => { const [, set] = useState(false); return <button type=\"button\" onClick={() => set(true)} /> }"],
    // A mocked method passed to expect
    [TEST_FILE, "import { it, expect, vi } from 'vitest'\nimport { api } from '@/api/api'\nvi.mock('@/api/api')\nit('a', () => { expect(api.post).not.toHaveBeenCalled() })"],
  ])('allows %s: %s', async (filePath, code) => {
    expect(await ruleIds(filePath, code, typedEslint)).toEqual([])
  })
})
