---
name: audit-code
description: Review code hygiene across the repo - comments (stale, redundant, change-history, author-specific, missing where needed), dead code and orphaned files, debug leftovers, naming and pattern consistency against CLAUDE.md's conventions, imports a built-in or a common library could replace, and the lint setup itself.
argument-hint: "[comments|dead|naming|imports|lint ...]"
disable-model-invocation: true
context: fork
---

# /audit-code

First read `.claude/skills/_audit-shared/RULES.md` and follow it throughout.
Then read `CLAUDE.md` (its **Naming Conventions** and the folder rules under
**Architecture** are the spec here), plus `DECISIONS.md` from the same folder
as RULES.md.

**Scope:** `$ARGUMENTS`, one or more part names. If empty, run all five parts.

**Files:** every tracked file (`git ls-files`) except lockfiles,
`backend/migrations/{README,alembic.ini,script.py.mako}` (Alembic's
generated files), and `.claude/` (part 5 reads the audit prompts, but only to
find manual checks lint could take over). Tests are in scope, but for test
comments report only stale or wrong ones, not redundant narration.

Whitespace and formatting (trailing spaces, final newlines) are out of scope:
`.editorconfig` and CI's Whitespace step cover them.

## 1. comments

Comments should explain *why* (a constraint, a trade-off, a non-obvious
consequence) to a developer who has just cloned the template. Read every
comment and flag:

- **Stale:** it names a file, function, variable, setting, version or behavior
  that no longer exists or no longer works that way. Check each reference.
- **Change history:** it explains what used to be there or why something
  changed ("now", "no longer", "used to", "was moved", "instead of the old",
  "after the fix"). Git holds history; the comment should state the current
  reason or go.
- **Author- or machine-specific:** it mentions a person, a local path, a
  particular machine or OS setup, a ticket, a chat or audit, or a date, where
  the general template reader has no use for it.
- **Redundant:** it restates what the code says (`# Initialize extensions`
  above `init_app`).
- **Too long:** a paragraph where a sentence would do, or the same explanation
  repeated in several files (keep it in one place and point there, or keep it
  only where a reader needs it).
- **Missing:** non-obvious code with no reason given: security-sensitive
  logic, magic numbers, workarounds, ordering that matters, anything a
  maintainer might "simplify" into a bug.
- **Temporary markers:** `TODO`, `FIXME`, `HACK`, `XXX`, `NOCOMMIT`. Each one
  is a finding: resolve it, or move it to the project's issue list. Lint
  refuses them in TypeScript (`no-warning-comments`) and, all but `NOCOMMIT`,
  in Python (ruff `FIX`), so look for `NOCOMMIT` in Python and for all of
  them in files no linter reads: CSS, YAML, shell, Dockerfiles, nginx config
  and docs.
- **Inconsistent style:** comment tone, capitalization and punctuation
  differ from the file's neighbors.

For each comment finding, give the replacement text (or "delete").
Comment findings are rated **low** or **nit** unless the comment is wrong in a
way that would mislead someone into a bug (then **medium**).

## 2. dead: dead code and leftovers

- Python: unused functions, classes, constants and parameters in
  `backend/app/` and the backend scripts (ruff already catches unused imports).
  Grep for each definition's uses; remember Flask registers routes and loaders
  by decorator.
- TypeScript: exports nothing imports, components and hooks nothing renders,
  CSS selectors no markup uses (check `frontend/src/styles/` and feature CSS
  against the JSX), and fixtures or test helpers no test uses.
- Routes the frontend never calls that are not documented as API-only.
- Files: anything tracked that nothing references (scripts, configs, assets),
  and test files whose subject is gone.
- Config: settings, env vars, compose keys and CI steps that have no effect.
- Code only tests use (a method, parameter or return value no app code
  reads) counts as dead, unless a comment marks it as a deliberate test seam.
- Debug leftovers that lint can't see. Lint already enforces `print` (ruff
  T20), commented-out Python (ruff ERA), `console.*` in app code (ESLint
  `no-console`), skipped and focused tests on every side (ruff `TID251`, the
  Vitest and Playwright presets), and commented-out tests. Look only for
  other commented-out JS, and debug-level logging or `FLASK_DEBUG` reaching
  production config.

## 3. naming: consistency

Check names and patterns against CLAUDE.md's conventions and against each other:

- Singular vs plural (model, table, schema, component, hook, test file names).
- Route and schema modules named after the API resource; test files after the
  module they test.
- The same concept spelled the same way everywhere (for example, error codes,
  env var prefixes, compose service and volume names, CSS custom properties,
  and UI wording such as "Log out" vs "Logout").
- The same job done the same way everywhere: error responses through
  `error_response`, backend calls through a service module, forms through
  `FormField`, imports through `@/`, React or React Router built-ins instead of
  hand-written equivalents. One file doing it differently is a finding.
- Import direction rules (shared code never imports a feature or page;
  features never import each other). ESLint enforces part of this; check what
  it misses.

## 4. imports: what a built-in or a common library could replace

Work in both directions. Every suggestion must clear RULES.md's **lean** bar:
name the lines it removes or simplifies, and what it costs (install size,
transitive dependencies, maintenance and release cadence, license; a
copyleft or unclear license is a finding tagged `(also /audit-legal)`). Read
the package's own docs or changelog for what it currently offers; don't rely
on memory. Do not re-report a library choice recorded in DECISIONS.md unless
its *Revisit when* has come true.

- **A dependency a built-in could replace.** For each third-party import in
  `backend/` (app, scripts, tests) and `frontend/` (src, e2e, config files):
  does the Python standard library (the version in `backend/Dockerfile`),
  Node (the version CI pins), the browsers' platform APIs (`fetch`,
  `AbortController`, `Intl`, `URLSearchParams`, `structuredClone`, the
  `<dialog>` element), or a library already installed (Flask, Pydantic,
  SQLAlchemy, React, React Router, Vitest) now do the same job? Weigh what
  the dependency does that the built-in would need hand-written code for
  (for example, axios's interceptors). Keeping a dependency is a valid
  conclusion; propose a DECISIONS.md entry so the next run doesn't redo the
  weighing.
- **Hand-written code a common library or tool could replace.** Look for
  code that re-implements what a widely used, maintained package does: custom
  lint rules or AST-scanning tests that an existing plugin or tool covers
  (for example, `import-linter` for Python import contracts), hand-rolled
  retry, backoff, debounce, date or number formatting, parsing, validation
  that duplicates a Pydantic or library feature, effect-based data loading
  where a React Router or React built-in fits. Prefer what is already
  installed, then the platform, then a new dependency.
- **Standard-library and internal imports:** a module imported for one
  trivial use that a builtin covers (`fileURLToPath(import.meta.url)` where
  `import.meta.dirname` works), or a helper re-implemented in several places
  instead of imported from one.

Unused or misplaced packages belong to `/audit-security` (part 2): cite its
latest report's ID instead of repeating them.

## 5. lint: the lint setup itself

Files: `backend/ruff.toml`, `backend/mypy.ini`, `backend/pytest.ini`, `backend/.coveragerc`,
`frontend/eslint.config.js`, `frontend/tsconfig*.json`, the coverage thresholds in
`frontend/vite.config.ts`, and the tests that act as lint
(`backend/tests/unit/test_import_rules.py`,
`backend/tests/unit/test_assertions.py`,
`frontend/src/__tests__/eslintRules.test.ts`,
`frontend/src/__tests__/typescriptRules.test.ts`), plus the lint jobs in
`.github/workflows/`. Run `ruff check .`, `mypy`, `npm run lint` and
`npm run typecheck` first; a red run is a blocker.

- **Redundant config:** options set to their default (check the tool's docs
  for the installed version), rules repeated across blocks, blocks that could
  merge, ignores that match nothing.
- **Custom code a maintained rule now covers:** each custom ESLint rule,
  `no-restricted-syntax` selector and AST-scanning test: does a plugin rule,
  a ruff rule, a preset (`vitest.configs.recommended`,
  `playwright.configs['flat/recommended']`, a ruff rule set) or a tool do the
  same? Weigh the lines saved against the dependency added, as in part 4.
- **Rules worth turning on:** a ruff rule set or plugin rule that would catch
  a class of problem this repo has had (check `temp/audits/` for repeats) or
  that CLAUDE.md forbids in prose (for example, ruff `TID251` banned-api for
  an API CLAUDE.md says never to call). Name the rules and run them once to
  show what they would flag today; a rule that would need many suppressions
  is not worth it.
- **Manual checks lint could take over:** read the other `/audit-*` prompts
  for steps that scan for a mechanical pattern (`.skip` and `.only`,
  commented-out code). Each one a rule could catch is a finding whose fix
  adds the rule and deletes the step from the prompt.
- **Suppressions:** every `eslint-disable`, `noqa` and per-file ignore needs
  a reason next to it and must still be necessary (remove it and run lint).
- **Guards that can fail silently:** every structural rule (import
  direction, raw form controls, assertion hedges) needs a test that plants a
  violation and sees it caught. A rule with none is a finding.
- **Consistency between the two sides:** where the backend and frontend
  enforce the same CLAUDE.md rule (one-way imports, assertion hedges), do
  they cover the same cases?

## Out of scope
README and CLAUDE.md prose (`/audit-docs`); behavior (other checks).

Write the report as RULES.md describes, with ID prefix `CODE`. Group comment
problems into findings by kind (for example, "CODE-3: 7 change-history
comments"), and put every individual edit in a separate *Comment edits* table
(file:line, current text, proposed text), since applying them is the point of
part 1. The table's rows are not findings: they don't count toward the
severity counts or the cap on nits.
