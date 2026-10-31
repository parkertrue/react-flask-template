---
name: audit-a11y
description: Accessibility audit against WCAG 2.2 AA and CLAUDE.md's accessibility rules, covering what axe cannot - keyboard flow, focus management, announcements, error handling, reflow, target size and contrast in every state.
disable-model-invocation: true
context: fork
---

# /audit-a11y

First read `.claude/skills/_audit-shared/RULES.md` and follow it throughout.
Then read `CLAUDE.md` (its **Accessibility (WCAG 2.2 AA)** paragraph is the
spec), plus `SOURCES.md` (React / frontend, Accessibility) and `DECISIONS.md`
from the same folder as RULES.md. This check runs Docker: record all four
Timings (RULES.md, Report).

axe already runs on every shared page in `frontend/e2e/accessibility.spec.js`,
and each feature's spec runs it on its own pages, but axe covers only about a
third of WCAG. This check covers the rest.

## 1. Read the code

Read every page, layout and form component in `frontend/src/` (`pages/`,
`components/`, `features/*/`), plus `styles/tokens.css` and the shared styles.

- Every page: one `h1`, a `<PageTitle>`, a sensible heading order, landmarks
  (`header`, `nav`, `main`), and a skip link or equivalent.
- Forms: every field through `FormField` (label, hint and message tied by
  `aria-describedby`, `autoComplete` set), `noValidate`, focus on the first
  invalid field after a failed submit, errors announced (`role="alert"`),
  success announced (`role="status"`), `aria-invalid` on invalid fields.
- Busy states: `aria-disabled` or `readOnly` rather than `disabled`, with
  handlers guarded; the busy state visible (and its label still legible).
- Navigation: focus moves to the new page's `h1` on route change (CLAUDE.md's design);
  back and forward work.
- Dynamic content: "Load more" moves or keeps focus sensibly and announces new
  items; the API status demo announces changes without being noisy.
- Contrast: `styles/__tests__/tokens.test.js` computes every ratio (4.5:1
  text, 3:1 large text and UI components, including focus rings, borders of
  inputs, and disabled-looking states). Check that it lists every pairing the
  CSS actually uses. Motion needs no check: `stylesheets.test.js` refuses a
  transition or animation outside `prefers-reduced-motion: no-preference`.
- Also: `lang` on `<html>`; forced-colors mode (Windows High Contrast) keeps
  focus rings, borders and states visible; `autoComplete` on every field
  where a purpose applies; input limits (such as the note length) tell the
  user rather than silently stop typing.

## 2. Check it in a browser

Bring up the E2E stack (follow the Docker rules in RULES.md) and drive it
with Playwright from a script in the scratch directory. Setup that works:

- Import from `<repo>/frontend/node_modules/@playwright/test` (there is no
  top-level `playwright` package); axe from `@axe-core/playwright` in the same
  folder.
- Launch Chromium with `args: ['--host-resolver-rules=MAP localhost 127.0.0.1']`
  and `ignoreHTTPSErrors: true`, against `https://localhost:8443`.
- Reach busy states by delaying API responses with `page.route(...)`; force
  the page-level error page by returning malformed `/api/notes` data (a
  layout-level crash can't be forced in a production build: review that one
  in code); reach the expired-session state with `expireAccessToken` from
  `frontend/e2e/helpers.js`, or by corrupting `access_token` in
  localStorage and clearing cookies.
- After navigation (including back and forward), wait for the focus change
  before reading `document.activeElement`; read straight after `waitForURL`
  and it is too early.

Check on every page, logged out and logged in:

- **Keyboard only:** Tab through everything. Order matches the visual order,
  focus is always visible and never hidden behind anything (2.4.11), nothing
  traps focus, every control works with Enter or Space.
- **Reflow and zoom:** at 320 CSS px width (1.4.10) and with text-only zoom
  at 200% (set the root font size to 200%; 1.4.4), no horizontal scrolling
  and no clipped content. Text spacing overrides (1.4.12) don't break layout.
- **Target size:** interactive targets at least 24×24 CSS px or spaced
  (2.5.8). Measure with `getBoundingClientRect`.
- **States:** read `accessibility.spec.js` and each feature's spec first:
  they run axe on most states (form errors, busy and failed actions, a
  failed load, the error page, a session that ended, edit mode, the open
  delete dialog). Run axe (`@axe-core/playwright`, as they do) on any state
  they miss. Check every dialog (`ConfirmDialog` deleting a note,
  `FormDialog` deleting the account): its initial focus, the focus
  returned after Cancel, the focus after confirming (for the account, the
  login page's `h1`, with the message that the account is gone), and, for
  `FormDialog`, a failed submit's message inside the dialog.
- **Accessibility tree:** take `page.locator('body').ariaSnapshot()` for
  each page and check names, roles and states read sensibly.

Anything only a real screen reader can settle (how an announcement actually
sounds) goes under *Unverified* as a manual item.

Tear the stack down when done.

## 3. Test coverage of the rules

Which of the rules above are pinned by tests (unit tests asserting focus and
roles; E2E)? Report all untested rules as **one** medium finding listing
each rule and its proposed test, since the next change can silently break
any of them.

## Out of scope
Visual design taste. Anything WCAG AAA.

Write the report as RULES.md describes, with ID prefix `A11Y`. Give the WCAG
success criterion number for each finding. A real usability problem that no
AA criterion covers is reported as "no SC (usability)", rated low, rather
than stretched to fit a criterion.
