import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tanstackQuery from '@tanstack/eslint-plugin-query'
import vitest from '@vitest/eslint-plugin'
import playwright from 'eslint-plugin-playwright'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'
import path from 'path'

// Each block below that restricts imports repeats this, since a later block
// replaces an earlier one's options for the same rule rather than adding to
// them: ./ within a folder, the @/ alias across folders
const NO_CLIMBING = {
  group: ['../../*'],
  message: 'Import from another folder with the @/ alias, not ../../',
}
const restrictImports = (...patterns) =>
  ({ 'no-restricted-imports': ['error', { patterns: [...patterns, NO_CLIMBING] }] })

// The same holds for no-restricted-syntax. These apply to every file in
// src/, and FORM_CONTROL to all but FormField's own folder.
const NO_TEXT_AS_HTML = {
  selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']",
  message: 'Render text, which React escapes. User markup must be sanitized first (CLAUDE.md).',
}
// Tests find and check what the user sees; E2E specs take these too
const NO_TEST_IDS = [
  {
    selector: "JSXAttribute[name.name='data-testid'], Identifier[name=/ByTestId$/]",
    message: 'Find elements by role, label or text: production markup has no data-testid.',
  },
  {
    selector: "MemberExpression[property.name='toHaveClass']",
    message: 'Assert what the user sees, not a class name.',
  },
]
const NO_DISABLED = {
  selector: "JSXAttribute[name.name='disabled']",
  message: 'disabled drops keyboard focus: mark a busy control aria-disabled or readOnly and guard its handler.',
}
const NO_MOCKED_STORAGE = {
  selector: "CallExpression[callee.object.name='vi'][callee.property.name=/^(mock|doMock)$/][arguments.0.value=/(^|[^a-zA-Z])storage$/]",
  message: 'Tests use the real localStorage (signIn() for a session), never a mocked storage.',
}
const FORM_CONTROL = {
  selector: 'JSXOpeningElement[name.name=/^(input|textarea|select)$/]',
  message: 'Use FormField (src/components/forms) instead of a raw form control.',
}
const NO_NATIVE_VALIDATION = {
  selector: "JSXOpeningElement[name.name='form']:not(:has(JSXAttribute[name.name='noValidate']))",
  message: "Forms are noValidate, so the app's own messages show.",
}
const restrictSyntax = (...selectors) => ({
  'no-restricted-syntax': ['error', NO_TEXT_AS_HTML, ...NO_TEST_IDS, NO_DISABLED, NO_MOCKED_STORAGE, NO_NATIVE_VALIDATION, ...selectors],
})

// Assertions that accept several answers, in unit and E2E tests alike
// (backend: tests/unit/test_assertions.py)
const NO_HEDGES = [
  {
    selector: "MemberExpression[property.name=/^toContain/] > CallExpression.object[callee.name='expect'][arguments.0.type='ArrayExpression']",
    message: 'Pin the one answer the code gives.',
  },
  {
    selector: "CallExpression[callee.name='expect'][arguments.0.type='LogicalExpression'][arguments.0.operator='||']",
    message: 'Pin the one answer the code gives.',
  },
  {
    selector: "CallExpression[callee.name='expect'][arguments.0.type='ConditionalExpression']",
    message: 'Pin the one answer the code gives.',
  },
  {
    // expect(true).toBe(true) passes whatever the code does
    selector: "CallExpression[callee.name='expect'][arguments.0.type='Literal']",
    message: 'Assert on what the code returns, not on a constant.',
  },
]

// An assertion that may not run, in a shared helper or a spec's own function,
// which vitest/ and playwright/no-conditional-expect, looking only inside a
// test's callback, miss (backend: test_assertions.py scans conftest.py too).
// A try with only a finally is allowed: what fails in it still fails the test
const NO_CONDITIONAL_EXPECT = {
  selector: ":matches(IfStatement, ConditionalExpression, TryStatement[handler], SwitchCase, LogicalExpression, WhileStatement, DoWhileStatement) CallExpression[callee.name='expect']",
  message: 'Assert unconditionally: collect what to check, then assert once.',
}

// Matchers that almost any value passes, refused in unit and E2E tests alike
const WEAK_MATCHERS = {
  toBeDefined: 'Assert the value itself.',
  toBeTruthy: 'Assert the value itself.',
  toBeFalsy: 'Assert the value itself.',
  'not.toBeNull': 'Assert the value itself.',
  'not.toBeUndefined': 'Assert the value itself.',
  toBeOneOf: 'Pin the one answer the code gives.',
}

// The session lives in one place, auth/storage.ts
const NO_STORAGE = {
  'no-restricted-globals': ['error', ...['localStorage', 'sessionStorage'].map(name =>
    ({ name, message: 'Read and write the session through @/auth/storage.' }))],
  'no-restricted-properties': ['error', ...['localStorage', 'sessionStorage'].map(property =>
    ({ object: 'window', property, message: 'Read and write the session through @/auth/storage.' }))],
}
const ALLOW_STORAGE = { 'no-restricted-globals': 'off', 'no-restricted-properties': 'off' }

// The folder a file belongs to: a feature (features/notes), a top-level
// folder of src/ (auth, pages, ...), or src/ itself for its root files.
// A __tests__ folder belongs to the folder it sits in.
const SRC = path.join(import.meta.dirname, 'src')
const folderOf = file => {
  const parts = path.relative(SRC, file).split(path.sep).filter(part => part !== '__tests__')
  if (parts[0] === '..') return null
  if (parts.length === 1) return '.'
  return parts[0] === 'features' ? parts.slice(0, 2).join('/') : parts[0]
}

// no-restricted-imports only matches the text of a path, so a relative one
// such as ../health/useHealth or ../routes could reach another folder
// unseen. This resolves it instead: a relative import must stay in its
// folder, which leaves the @/ alias, and the rules on it below, as the only
// way across.
const relativeWithinFolder = {
  meta: { type: 'problem', schema: [] },
  create(context) {
    const from = folderOf(context.filename)
    const check = source => {
      if (from === null || typeof source?.value !== 'string' || !source.value.startsWith('.')) return
      const target = path.resolve(path.dirname(context.filename), source.value)
      if (folderOf(target) !== from) {
        context.report({ node: source, message: 'Import from another folder with the @/ alias.' })
      }
    }
    return {
      ImportDeclaration: node => check(node.source),
      ExportNamedDeclaration: node => check(node.source),
      ExportAllDeclaration: node => check(node.source),
      ImportExpression: node => check(node.source),
    }
  },
}

export default defineConfig([
  globalIgnores(['dist', 'coverage', 'playwright-report', 'test-results']),
  {
    // This file stays JavaScript: ESLint loads a TypeScript config only
    // through an extra loader
    files: ['eslint.config.js'],
    extends: [js.configs.recommended],
    languageOptions: { globals: globals.node },
  },
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      // Type-aware, and the strictest preset, as mypy runs strict on the
      // backend: no any, no unhandled promise, no ! assertion, no
      // @ts-ignore, no condition the types say is always the same
      tseslint.configs.strictTypeChecked,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
      // Query keys that miss a value the fetch uses, a client made on every
      // render, and the like
      tanstackQuery.configs['flat/recommended'],
    ],
    languageOptions: {
      globals: globals.browser,
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    // Debug output and temporary markers stay out of shipped code
    // (`debugger` is already an error in js.configs.recommended), and so
    // does running a string as code
    rules: {
      'no-console': 'error',
      'no-warning-comments': ['error', { terms: ['todo', 'fixme', 'hack', 'xxx', 'nocommit'] }],
      'no-eval': 'error',
      'no-implied-eval': 'error',
      'no-new-func': 'error',
      // A count or a length in a message is fine; an object or undefined
      // there is still a bug
      '@typescript-eslint/restrict-template-expressions': ['error', { allowNumber: true }],
      // onClick={() => setOpen(false)} is how React code reads
      '@typescript-eslint/no-confusing-void-expression': ['error', { ignoreArrowShorthand: true }],
    },
  },
  {
    files: ['src/**'],
    plugins: { local: { rules: { 'relative-within-folder': relativeWithinFolder } } },
    rules: {
      ...restrictImports(),
      ...restrictSyntax(FORM_CONTROL),
      ...NO_STORAGE,
      'local/relative-within-folder': 'error',
    },
  },
  {
    files: ['src/auth/storage.ts'],
    rules: ALLOW_STORAGE,
  },
  {
    // Fields go through FormField, which ties the label, hint and message to
    // the input for screen readers. Only it renders a raw form control
    files: ['src/components/forms/**'],
    rules: restrictSyntax(),
  },
  {
    // Shared code never depends on a feature or a page, so deleting a
    // feature folder cannot break it
    files: ['src/{api,auth,components,utils,styles}/**', 'src/{appName,legal}.ts'],
    rules: restrictImports({
      group: ['@/features/*', '@/pages/*', '@/routes'],
      message: 'Shared code must not import a feature or a page.',
    }),
  },
  {
    // Nor do the shared test helpers and tests, which may render the whole
    // app through the routes (src/test/integration/)
    files: ['src/test/**'],
    rules: restrictImports({
      group: ['@/features/*', '@/pages/*'],
      message: 'Shared tests must not import a feature or a page.',
    }),
  },
  {
    // Nor does one feature depend on another, so each can be deleted alone.
    // Its own files it imports with ./
    files: ['src/features/**'],
    rules: restrictImports({
      group: ['@/features/*', '@/pages/*', '@/routes'],
      message: 'A feature must not import another feature, a page or the routes.',
    }),
  },
  {
    // A feature's tests may render the whole app around it
    files: ['src/features/**/__tests__/**'],
    rules: restrictImports({
      group: ['@/features/*', '@/pages/*'],
      message: 'A feature must not import another feature or a page.',
    }),
  },
  {
    // Build and test tooling runs under Node, not in the browser
    files: ['*.config.ts', 'e2e/**'],
    languageOptions: {
      globals: globals.node,
    },
    rules: {
      'no-console': 'off',
    },
  },
  {
    // Tests use the real localStorage, and clear it after each one
    files: ['src/**/__tests__/**', 'src/test/**', '**/*.{test,spec}.{ts,tsx}'],
    languageOptions: {
      globals: globals.node,
    },
    rules: {
      'no-console': 'off',
      ...ALLOW_STORAGE,
    },
  },
  {
    // Shared test helpers assert too, so they take the same hedge rules as
    // the tests that call them (e2e/helpers.ts below)
    files: ['src/test/**'],
    rules: restrictSyntax(FORM_CONTROL, ...NO_HEDGES, NO_CONDITIONAL_EXPECT),
  },
  {
    // Every assertion must be able to fail: none behind an if or in a catch,
    // none that almost any value passes, and no test without one, skipped
    // or focused (backend: tests/unit/test_assertions.py). The presets ship
    // some rules as warnings, which `npm run lint` fails on too
    files: ['src/**/*.{test,spec}.{ts,tsx}'],
    extends: [vitest.configs.recommended],
    rules: {
      ...restrictSyntax(FORM_CONTROL, ...NO_HEDGES, NO_CONDITIONAL_EXPECT),
      'vitest/no-restricted-matchers': ['error', WEAK_MATCHERS],
      // A run checks one branch only, even when the assert comes after it
      'vitest/no-conditional-in-test': 'error',
      'vitest/no-large-snapshots': 'error',
      // act(async () => ...) waits for what the callback set off, awaiting
      // nothing itself
      '@typescript-eslint/require-await': 'off',
      // expect(api.post) passes a method without calling it, which is fine;
      // Vitest's own version of the rule knows that
      '@typescript-eslint/unbound-method': 'off',
      'vitest/unbound-method': 'error',
    },
  },
  {
    // FormField's own tests keep its folder's raw form controls
    files: ['src/components/forms/**/*.{test,spec}.{ts,tsx}'],
    rules: restrictSyntax(...NO_HEDGES, NO_CONDITIONAL_EXPECT),
  },
  {
    files: ['e2e/**'],
    rules: {
      'no-restricted-syntax': ['error', ...NO_TEST_IDS, ...NO_HEDGES, NO_CONDITIONAL_EXPECT],
    },
  },
  {
    files: ['e2e/**/*.spec.ts'],
    extends: [playwright.configs['flat/recommended']],
    rules: {
      // e2e/helpers.ts's expect* helpers (expectNoViolations, ...) assert too
      'playwright/expect-expect': ['error', { assertFunctionPatterns: ['^expect[A-Z]'] }],
      'playwright/no-restricted-matchers': ['error', WEAK_MATCHERS],
    },
  },
  {
    // The app, its tests and its tooling are TypeScript, checked by tsc
    // (npm run typecheck), which a .js file would slip past. Last, since a
    // later block's no-restricted-syntax would replace this one's
    files: ['src/**/*.{js,jsx,mjs,cjs}', 'e2e/**/*.{js,jsx,mjs,cjs}', '*.config.{js,mjs,cjs}'],
    ignores: ['eslint.config.js'],
    languageOptions: { parserOptions: { ecmaFeatures: { jsx: true } } },
    rules: {
      'no-restricted-syntax': ['error', { selector: 'Program', message: 'Write TypeScript (.ts, .tsx), which tsc checks.' }],
    },
  },
])
