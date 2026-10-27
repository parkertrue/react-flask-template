import { beforeAll, describe, it, expect } from 'vitest'
import { ESLint } from 'eslint'

// The lint rules are config, and config fails silently: a later block
// replaces an earlier one's options, and a rule whose file glob or selector
// stops matching reports nothing. These plant code in made-up files and lint
// it with the real eslint.config.js, as tests/unit/test_import_rules.py and
// test_assertions.py do for the backend.
const eslint = new ESLint()

// The first lint loads every plugin, which on a busy machine takes longer
// than a test's 5 s, so it happens here, with time to spare
beforeAll(() => eslint.lintText('\n', { filePath: 'src/x.js' }), 60_000)

const ruleIds = async (filePath, code) => {
  const [result] = await eslint.lintText(`${code}\n`, { filePath })
  return result.messages.map(message => message.ruleId)
}

describe('import rules', () => {
  it.each([
    // A relative path that leaves its folder, however it is written
    ['src/features/notes/x.js', "import '../health/useHealth'", 'local/relative-within-folder'],
    ['src/auth/x.js', "import '../routes'", 'local/relative-within-folder'],
    ['src/auth/x.js', "export * from '../features/notes/useNotes'", 'local/relative-within-folder'],
    ['src/utils/x.js', "import('../pages/HomePage')", 'local/relative-within-folder'],
    ['src/routes.jsx', "import './pages/HomePage'", 'local/relative-within-folder'],
    ['src/components/layout/x.js', "import '../../features/notes/useNotes'", 'no-restricted-imports'],
    // The one-way rules on the @/ alias
    ['src/utils/x.js', "import '@/features/notes/useNotes'", 'no-restricted-imports'],
    ['src/auth/x.js', "import '@/routes'", 'no-restricted-imports'],
    ['src/components/x.js', "import '@/pages/HomePage'", 'no-restricted-imports'],
    ['src/features/notes/x.js', "import '@/features/health/useHealth'", 'no-restricted-imports'],
    ['src/features/notes/x.js', "import '@/pages/HomePage'", 'no-restricted-imports'],
    ['src/features/notes/x.js', "import '@/routes'", 'no-restricted-imports'],
    ['src/features/notes/__tests__/x.js', "import '@/features/health/useHealth'", 'no-restricted-imports'],
  ])('refuses %s: %s', async (filePath, code, ruleId) => {
    expect(await ruleIds(filePath, code)).toContain(ruleId)
  })

  it.each([
    ['src/features/notes/x.js', "import './useNotes'"],
    ['src/features/notes/x.js', "import '@/auth/useAuth'"],
    ['src/features/notes/__tests__/x.js', "import '../useNotes'"],
    ['src/features/notes/__tests__/x.js', "import '@/routes'"],
    ['src/components/layout/x.js', "import '../forms/FormField'"],
    ['src/test/integration/x.js', "import '../fixtures'"],
    ['src/__tests__/x.js', "import '../routes'"],
    ['src/pages/x.js', "import '@/features/notes/NotesPage'"],
  ])('allows %s: %s', async (filePath, code) => {
    expect(await ruleIds(filePath, code)).toEqual([])
  })
})

describe('code rules', () => {
  it.each([
    // Form controls go through FormField, in .js files as in .jsx
    ['src/pages/x.jsx', 'export const X = () => <input />', 'no-restricted-syntax'],
    ['src/features/notes/x.js', 'export const X = () => <textarea />', 'no-restricted-syntax'],
    ['src/pages/__tests__/x.test.jsx', 'render(<select />)', 'no-restricted-syntax'],
    // Markup rules hold everywhere, FormField's folder and tests included
    ['src/pages/x.jsx', 'export const X = () => <p dangerouslySetInnerHTML={{ __html: x }} />', 'no-restricted-syntax'],
    ['src/pages/x.jsx', 'export const X = () => <p data-testid="x" />', 'no-restricted-syntax'],
    ['src/pages/x.jsx', 'export const X = () => <button disabled />', 'no-restricted-syntax'],
    ['src/components/forms/x.jsx', 'export const X = () => <input disabled />', 'no-restricted-syntax'],
    ['src/pages/__tests__/x.test.jsx', "screen.getByTestId('x')", 'no-restricted-syntax'],
    ['src/pages/__tests__/x.test.jsx', "expect(x).toHaveClass('x')", 'no-restricted-syntax'],
    ['e2e/x.spec.js', "page.getByTestId('x')", 'no-restricted-syntax'],
    ['e2e/x.spec.js', "expect(x).toHaveClass('x')", 'no-restricted-syntax'],
    ['src/pages/__tests__/x.test.jsx', "vi.mock('@/auth/storage')", 'no-restricted-syntax'],
    ['src/auth/__tests__/x.test.jsx', "vi.mock('../storage')", 'no-restricted-syntax'],
    // The session is read and written in auth/storage.js alone
    ['src/features/notes/x.js', "localStorage.getItem('x')", 'no-restricted-globals'],
    ['src/auth/x.js', 'sessionStorage.clear()', 'no-restricted-globals'],
    ['src/pages/x.jsx', 'window.localStorage.clear()', 'no-restricted-properties'],
    // Leftovers and strings run as code
    ['src/utils/x.js', "console.log('x')", 'no-console'],
    ['src/utils/x.js', '// TODO: x', 'no-warning-comments'],
    ['src/utils/x.js', "eval('x')", 'no-eval'],
    ['src/utils/x.js', "setTimeout('x()')", 'no-implied-eval'],
    ['src/utils/x.js', "new Function('x')", 'no-new-func'],
  ])('refuses %s: %s', async (filePath, code, ruleId) => {
    expect(await ruleIds(filePath, code)).toContain(ruleId)
  })

  it.each([
    ['src/components/forms/x.jsx', 'export const X = () => <input />'],
    ['src/pages/x.jsx', 'export const X = () => <button aria-disabled="true" />'],
    ['src/pages/__tests__/x.test.jsx', "import { vi } from 'vitest'; vi.mock('@/api/api')"],
    ['src/auth/storage.js', "localStorage.getItem('x')"],
    ['src/test/x.js', 'window.localStorage.clear()'],
    ['src/auth/__tests__/x.test.js', 'localStorage.clear()'],
    ['e2e/x.js', "console.log('x')"],
  ])('allows %s: %s', async (filePath, code) => {
    expect(await ruleIds(filePath, code)).toEqual([])
  })
})

describe('test rules', () => {
  it.each([
    // Unit tests, named .test or .spec, as Vitest runs both
    ['src/x/__tests__/a.test.jsx', "it('a', () => { if (x) expect(x).toBe(1) })", 'vitest/no-conditional-expect'],
    ['src/x/__tests__/a.spec.jsx', "it('a', () => { if (x) expect(x).toBe(1) })", 'vitest/no-conditional-expect'],
    ['src/x/__tests__/a.test.js', "it('a', () => { if (x) run(); expect(y).toBe(1) })", 'vitest/no-conditional-in-test'],
    ['src/x/__tests__/a.test.js', "it('a', () => { run() })", 'vitest/expect-expect'],
    ['src/x/__tests__/a.test.js', "it.skip('a', () => { expect(x).toBe(1) })", 'vitest/no-disabled-tests'],
    ['src/x/__tests__/a.test.js', "it.only('a', () => { expect(x).toBe(1) })", 'vitest/no-focused-tests'],
    ['src/x/__tests__/a.test.js', "// it('a', () => { expect(x).toBe(1) })", 'vitest/no-commented-out-tests'],
    ['src/x/__tests__/a.test.js', "it('a', () => { expect(x).toBeDefined() })", 'vitest/no-restricted-matchers'],
    ['src/x/__tests__/a.test.js', "it('a', () => { expect(x).toBeTruthy() })", 'vitest/no-restricted-matchers'],
    ['src/x/__tests__/a.test.js', "it('a', () => { expect(x).not.toBeNull() })", 'vitest/no-restricted-matchers'],
    ['src/x/__tests__/a.test.js', "it('a', () => { expect(x).toBeOneOf([1, 2]) })", 'vitest/no-restricted-matchers'],
    ['src/x/__tests__/a.test.js', "it('a', () => { expect([400, 422]).toContain(x) })", 'no-restricted-syntax'],
    ['src/x/__tests__/a.test.js', "it('a', () => { expect(x === 1 || x === 2).toBe(true) })", 'no-restricted-syntax'],
    ['src/components/forms/__tests__/a.test.js', "it('a', () => { expect([1, 2]).toContainEqual(x) })", 'no-restricted-syntax'],
    // Shared helpers that assert
    ['src/test/x.js', 'export const check = x => expect([400, 422]).toContain(x)', 'no-restricted-syntax'],
    ['src/test/x.js', 'export const check = x => expect(x.a || x.b).toBe(true)', 'no-restricted-syntax'],
    ['e2e/helpers.js', 'export const check = x => expect([400, 422]).toContain(x)', 'no-restricted-syntax'],
    // An assertion that may not run, outside a test's callback
    ['src/test/x.js', 'export const check = x => { if (x.ok) expect(x.status).toBe(1) }', 'no-restricted-syntax'],
    ['src/test/x.js', 'export const check = x => { try { run() } catch { expect(x).toBe(1) } }', 'no-restricted-syntax'],
    ['e2e/helpers.js', 'export const check = x => { if (x.ok) expect(x.status).toBe(1) }', 'no-restricted-syntax'],
    ['e2e/helpers.js', 'export const check = x => { try { expect(x).toBe(1) } catch { run() } }', 'no-restricted-syntax'],
    ['e2e/helpers.js', 'export const check = x => (x.ok ? expect(x).toBe(1) : run())', 'no-restricted-syntax'],
    ['src/x/__tests__/a.test.js', 'const check = x => x.ok && expect(x.status).toBe(1)', 'no-restricted-syntax'],
    ['e2e/x.spec.js', 'function check(x) { switch (x) { case 1: expect(x).toBe(1) } }', 'no-restricted-syntax'],
    // End-to-end tests
    ['e2e/x.spec.js', "test('a', async ({ page }) => { await page.goto('/') })", 'playwright/expect-expect'],
    ['e2e/x.spec.js', "test('a', async ({ page }) => { if (x) await expect(page).toHaveURL('/') })", 'playwright/no-conditional-in-test'],
    ['e2e/x.spec.js', "test.skip('a', async ({ page }) => { await expect(page).toHaveURL('/') })", 'playwright/no-skipped-test'],
    ['e2e/x.spec.js', "test.only('a', async ({ page }) => { await expect(page).toHaveURL('/') })", 'playwright/no-focused-test'],
    ['e2e/x.spec.js', "test('a', async ({ page }) => { await page.waitForTimeout(1); await expect(page).toHaveURL('/') })", 'playwright/no-wait-for-timeout'],
    ['e2e/x.spec.js', "test('a', async () => { expect([400, 422]).toContain(x.status()) })", 'no-restricted-syntax'],
    ['e2e/x.spec.js', "test('a', async () => { expect(x.a || x.b).toBe(true) })", 'no-restricted-syntax'],
    ['e2e/x.spec.js', "test('a', async ({ page }) => { expect(await page.title()).toBeTruthy() })", 'playwright/no-restricted-matchers'],
    ['e2e/x.spec.js', "test('a', async ({ page }) => { expect(await page.title()).not.toBeNull() })", 'playwright/no-restricted-matchers'],
  ])('refuses %s: %s', async (filePath, code, ruleId) => {
    expect(await ruleIds(filePath, code)).toContain(ruleId)
  })

  it.each([
    ['src/x/__tests__/a.test.js', "import { it, expect } from 'vitest'; const x = 1; it('a', () => { expect(x).toBe(1) })"],
    ['src/x/__tests__/a.test.js', "import { it, expect } from 'vitest'; const x = [1]; it('a', () => { expect([1]).toEqual(x) })"],
    ['src/components/forms/__tests__/a.test.jsx', "import { it, expect } from 'vitest'; const x = <input />; it('a', () => { expect(x).toBe(x) })"],
    ['e2e/x.spec.js', "import { test, expect } from '@playwright/test'\n\ntest('a', async ({ page }) => { await expect(page).toHaveURL('/') })"],
    // A loop's assert runs on every pass; a finally's failure still fails
    ['e2e/helpers.js', "import { expect } from '@playwright/test'\n\nexport const check = xs => { for (const x of xs) expect(x).toBe(1) }"],
    ['e2e/helpers.js', "import { expect } from '@playwright/test'\n\nexport const check = (x, done) => { try { expect(x).toBe(1) } finally { done() } }"],
  ])('allows %s: %s', async (filePath, code) => {
    expect(await ruleIds(filePath, code)).toEqual([])
  })
})
