---
name: audit-legal
description: Review legal exposure - the template's own license and its dependencies' licenses, privacy law (GDPR/UK GDPR, CCPA/CPRA and other US state laws, COPPA), terms and consumer protection, user-generated content, the legal side of accessibility, and required notices. Flags risks to take to a lawyer; it is not legal advice.
argument-hint: "[license|privacy|terms|content|a11y|notices ...]"
disable-model-invocation: true
context: fork
---

# /audit-legal

First read `.claude/skills/_audit-shared/RULES.md` and follow it throughout.
Then read `CLAUDE.md`, `README.md`, and `DECISIONS.md` from the same folder
as RULES.md.

**Scope:** `$ARGUMENTS`, one or more part names. If empty, run all six parts.

## Ground rules

- **This is not legal advice, and the report says so in its first line.**
  Each finding names the risk, the law and article or section it rests on,
  and what to ask a lawyer. Never state that the app *is* compliant with
  anything; "no findings" means only that this check saw nothing.
- **Laws change.** Confirm every law, threshold and deadline you cite against
  a source in SOURCES.md's Legal section (WebFetch or WebSearch), and give the
  URL in the Evidence column. If you could not confirm it, the finding goes
  under *Unverified*.
- **Baseline jurisdictions:** EU GDPR and ePrivacy, UK GDPR and PECR, US
  federal law (FTC Act section 5, COPPA, CAN-SPAM, DMCA, Section 230, ADA),
  California (CCPA/CPRA, CalOPPA) and the other US state privacy laws as a
  group. Mention another jurisdiction only where its rule is stricter in a
  way that changes the fix (for example, Germany's imprint rule).
- **Two audiences.** Tag every finding with one of:
  - **template:** the repository as published (its license, its notices,
    what it ships). Fix in the template now.
  - **derived app:** a gap every app built from the template inherits. Real
    legal text can't live in a template, so the fix is a placeholder (a route,
    a page, a config value) plus a step in README's "Starting a New App" that
    tells the developer what to fill in, and why.
- **Rate by what's true today, then say what would raise it.** Notes are
  private, there is no email, payment or analytics yet; a risk that only
  arrives with such a feature is **low** with its trigger named in the Fix.
  Known gaps in DECISIONS.md (data export, no deployment and so no
  centralized logging) are
  not new findings, but say when the law makes one more urgent than recorded.

### Severity for legal findings

| Severity | Meaning here |
|---|---|
| **blocker** | Publishing the template as it is would stop others from using it lawfully (no license, a dependency whose license forbids the use), or the template ships something unlawful by default (tracking without consent, a hidden third-party data transfer). |
| **high** | Every derived app inherits a gap that a privacy, consumer or accessibility law requires closed at launch, and nothing in README tells the developer. |
| **medium** | A gap a law requires once a common condition holds (users in the EU, a California business over the CCPA thresholds, public content), or a required notice that is missing but cheap to add. |
| **low** | Hardening against a claim, a gap tied to a feature that doesn't exist yet, or documentation that would help a lawyer's review. |
| **nit** | Wording. |

## 1. license

- **The template's own license.** Is a `LICENSE` file tracked, does README
  name it, and does `package.json` (`license`) agree with the license
  DECISIONS.md records? Without one, nobody may reuse the code.
- **Dependency licenses.** Inventory every runtime and dev dependency with
  its SPDX license:
  - Python: install `pip-licenses` into a throwaway venv in your scratch
    directory along with `backend/requirements.txt` (then, separately,
    `requirements-dev.txt`), never into the project venv, and run
    `pip-licenses --format=markdown --with-urls`.
  - JavaScript: `npx --yes license-checker-rseidelsohn --summary` and
    `--production --csv` in `frontend/` (it only reads `node_modules`).
  - Flag anything copyleft (GPL, AGPL, LGPL in shipped code), source-available
    (SSPL, BSL, RSAL), unknown, or missing. Separate what ships (runtime deps,
    the built bundle, the images) from what only developers run.
- **Notices that must ship.** MIT, BSD and Apache-2.0 require their copyright
  and license notice to go with copies. Build the frontend
  (`npm run build -- --outDir <scratch>/dist`) and check whether the bundle or
  the served site carries the notices of what it bundles (Vite's
  `build.license` option, or a third-party notices file), and whether the
  backend image does.
- **Container images.** The licenses of the images the stack runs (MySQL,
  Redis, nginx, Python, Node) and what they require of someone who runs them
  unmodified, versus modifies or offers them as a service. Read the license
  terms of the exact version pinned.
- **Copied material.** Code with a source link or attribution comment
  (Stack Overflow is CC BY-SA), fonts, icons, images and other assets: is
  each one's license known and honored?

## 2. privacy

- **Data inventory first.** List every piece of personal data the app and
  its infrastructure collect or derive: account fields, note content, IP
  addresses and user agents (nginx access logs, rate-limit keys, app logs),
  tokens and their claims, Redis keys, MySQL rows, backups (when they exist),
  browser storage (`localStorage`, cookies). For each: where it is stored,
  for how long, who can read it, and whether anything ever deletes it. Read
  the code and config for each answer (log formats and rotation in compose
  files and `nginx.conf`, TTLs in `redis_service.py`). Put the inventory in
  the report as a table; it is the basis of every privacy finding and of a
  derived app's records of processing (GDPR Art. 30).
- **Notice:** is there a privacy notice, linked where data is collected (the
  registration form) and from every page? What must it say (GDPR Art. 13,
  CCPA notice at collection, CalOPPA)? For a template: a placeholder page and
  route, and a README step.
- **Lawful basis and minimization** (GDPR Art. 5, 6): is each item needed,
  and kept no longer than needed? Unbounded retention (logs never rotated,
  rows never deleted) is a finding.
- **Rights:** access and portability (export), rectification, erasure,
  objection (GDPR Art. 15-21; CCPA's know, delete, correct). Can a user do
  each, or is there at least a documented way to ask? Deleting an account
  must also reach logs, Redis and backups, or say why not.
- **Cookies and storage** (ePrivacy Art. 5(3), PECR reg. 6): every cookie
  and storage key, and whether it is strictly necessary. Strictly necessary
  needs no consent banner; anything else (analytics, third-party embeds)
  does. Check for any request the browser makes to a third party (fonts,
  CDNs, scripts, images in `index.html`, CSS and the built bundle): each one
  sends the visitor's IP abroad (LG München I, 3 O 17493/20, on Google
  Fonts).
- **Children:** is there an age statement or gate? COPPA applies to services
  directed at, or knowingly collecting from, under-13s; GDPR Art. 8 sets 13
  to 16 for consent by country.
- **Security and breaches** (GDPR Art. 32-34; state "reasonable security"
  duties): cite `/audit-security`'s latest report rather than re-auditing;
  report here only what bears on legal duties, such as whether a breach could
  be detected and scoped from the logs that exist (72-hour notification).
- **Processors and transfers:** third-party services the app or its docs
  send personal data to (hosting, email, error tracking), and what each needs
  (a data processing agreement, a transfer mechanism). None today is fine;
  say what README should warn about.

## 3. terms: terms of service and consumer protection

- **Terms of service:** is there a placeholder, and does registration show
  it with an affirmative act (clickwrap: a link beside the submit button or
  a checkbox), rather than a link in a footer (browsewrap, often
  unenforceable)? Is acceptance recorded (which version, when)?
- **Dark patterns** (FTC Act section 5, CPRA's consent rules, DSA Art. 25):
  is ending things as easy as starting them? Signing out everywhere,
  deleting the account, and later cancelling a subscription should take no
  more steps than signing up.
- **Email** (CAN-SPAM, CASL, PECR): when the app sends email (verification
  and password reset are planned), what each kind requires (transactional vs
  marketing, unsubscribe, sender identity). A low finding until email exists.

## 4. content: user-generated content

Notes are private to their author today. Rate against that, and name what
changes when content becomes visible to others (sharing, public profiles,
comments).

- **Copyright:** DMCA section 512 safe harbor needs a designated agent
  registered with the US Copyright Office and a takedown and repeat-infringer
  policy.
- **EU Digital Services Act:** hosting services need a point of contact
  (Art. 11-12) and, for content others can see, notice-and-action (Art. 16)
  and statements of reasons (Art. 17).
- **Section 230** and the platform's moderation rights belong in the terms.
- **Stored content:** anything that would oblige reporting (CSAM, 18 U.S.C.
  2258A) once content is shared; low until then.

## 5. a11y: the legal side of accessibility

Do not re-test WCAG; `/audit-a11y` does that. Read its latest report and
report here:

- Which laws reach a derived app (ADA Title III as courts apply it to
  websites, the European Accessibility Act for consumer e-commerce and
  services in the EU since 2025-06-28, Section 508 for US federal work, the
  UK Equality Act), and what each requires beyond conformance: an
  accessibility statement, a way to report a barrier, a contact.
- Open A11Y findings re-rated by litigation exposure (a sign-up or log-in
  barrier is worse than a cosmetic one), citing their A11Y IDs.

## 6. notices

- **`/.well-known/security.txt`** (RFC 9116): a contact for vulnerability
  reports and an `Expires` date. For a template: served by nginx from a
  file the README tells the developer to fill in.
- **Imprint and contact:** where a jurisdiction requires the operator's name
  and address on the site (Germany's DDG section 5, the EU e-Commerce
  Directive Art. 5), and a contact point the DSA requires.
- **The app's name and branding:** `APP_NAME` placeholders and any
  third-party trademark in the UI or docs.

## Out of scope

Security defects (`/audit-security`), WCAG conformance (`/audit-a11y`),
documentation accuracy (`/audit-docs`). Contracts the operator signs
(hosting, processors) beyond saying which ones a derived app will need.

Write the report as RULES.md describes, with ID prefix `LEGAL`, starting with
the line "Not legal advice: risks to review with a lawyer." Put the data
inventory (part 2) and the license inventory (part 1, summarized by license,
with every flagged package listed) in their own sections after the findings.
In the Fix column, say whether the fix is code, a placeholder plus README
step, or a question for a lawyer.
