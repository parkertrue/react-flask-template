# Open issues

What is still open in this app: audit findings, problems noticed during
work, and work asked for, all as issues alike. The template ships two
groups, getting started and the production to-dos every deployment works
through; add groups as the work needs them (a feature, dependencies
waiting on a release, discussions). **Keep it current:**
- Delete an issue once it is done. Git history and the PRs hold the rest.
- Add an issue the moment it comes up, in the group where it fits. Merge it
  into an existing issue when the two should be fixed together.
- Discuss before acting on one: decide what to fix, what to record in
  `DECISIONS.md` (next to this file) as a deliberate trade-off, and what to
  leave.

Every audit checks its findings against this file and `DECISIONS.md`
(`RULES.md`): a finding already listed here is tagged `(open: <issue>)`,
and the report's recording plan says which issue each new finding joins or
starts. Severity, where an audit gave one: blocker > high > medium > low >
nit.

## Getting started

- **Set up your handoff doc.** Create `temp/HANDOFF.md` (`temp/` is
  gitignored) for what is yours alone and would mean nothing to anyone
  else: how your machine differs (OS, shell quirks, tool versions), your
  servers and how to reach them, the current state (branch, last merge,
  test counts on `main`), and how you like to work. Issues never go there:
  every open issue is in this file. A start:

  ```markdown
  # Handoff

  Read this, then `.claude/skills/_audit-shared/OPEN-ISSUES.md`, before
  starting.

  ## State
  ## How I work
  ## This machine
  ## Servers
  ```

  A new chat then starts with *"Read temp/HANDOFF.md and let's continue."*
  Bring its State up to date before ending a session. Delete this issue
  once the doc exists.
- **Plan the app.** Decide what it does, who uses it and its first
  feature, and add an issue here for each piece of work that comes out of
  it. Then follow README's "Starting a New App From This Template", which
  replaces the notes example with that first feature.

## Dependencies

Upgrades waiting on a release or a date; Dependabot proposes the rest
(`.github/dependabot.yml`).

- **minimatch's glob DoS (low, dev only).** GHSA-g3hv-75wg-m249 is fixed
  only in minimatch 11.0.1, which eslint, `@eslint/config-array` and
  `@typescript-eslint/typescript-estree` (through `@vitest/eslint-plugin`
  and `@tanstack/eslint-plugin-query`)
  don't accept yet (`^10`). Only the patterns in `eslint.config.js` reach
  it, and an attack needs its own pattern. Keep the Dependabot alert open:
  it closes by itself once an eslint bump brings minimatch 11. If it is
  still open in mid-December 2026, try forcing 11 with an npm `overrides`
  entry, with `src/__tests__/eslintRules.test.ts` (which plants a
  violation of every glob-scoped rule) as the guard.

## Production to-dos

What every deployment works through once it has a server that will hold
real users' data. `docs/deployment.md` has the detail of each.

- **Certificates that renew themselves (medium).** "Real Domain (Let's
  Encrypt)" uses Certbot's standalone method: renewal stops nginx and is
  done by hand, and its steps edit tracked files, so on a server that
  deploys with `deploy.sh` every later deploy refuses the dirty clone. Set
  up renewal without downtime that keeps the clone clean, for example
  Certbot's DNS-01 challenge with your DNS host's plugin and a deploy hook
  that copies the certificate into `nginx/certs/` and reloads nginx. Use
  Let's Encrypt's staging server while trying it. `DECISIONS.md` records
  that this waits for a server.
- **Email.** Sign up with a mail provider, set up the sending domain
  (SPF, DKIM, DMARC) and set `EMAIL_URL` and `EMAIL_FROM` ("Sending
  Email"). Send one email end to end, ask for the provider's production
  access, and read its bounce and complaint reports, which the app does
  not act on (`DECISIONS.md`, "Email").
- **The password hash's cost (low).** Hashes use scrypt N=2^15,
  Werkzeug's default, below OWASP's 2^17, which costs about 4× the CPU and
  memory (~128 MB per hash). Time a login on the production hardware and
  raise `PASSWORD_HASH_METHOD` (`backend/app/utils/passwords.py`) as far
  as its CPU, memory limit and `PASSWORD_HASH_CONCURRENCY` allow; then
  delete the scrypt entry in `DECISIONS.md`.
- **Deploys and backups.** Deploy with `deploy.sh` ("Redeploying"), on a
  timer if you want ("Deploying Automatically"). Dump the database on a
  schedule, copy the dumps off the server with a backup tool, and run one
  restore end to end ("Backups and Restoring").
- **The host.** Work through "The Host" (what reaches the server, the
  DNS record, Docker's daemon settings, user namespaces) and "Secrets Off
  the Host", then run Docker Bench for Security: the warnings it lists
  there are expected, anything else is a finding.
- **On a container platform, check what the docs could not.** "Deploying
  to a Platform" and "External Database or Redis" were written without a
  real deployment. Check them against yours and fix what it contradicts,
  in particular:
  - which module command categories your ElastiCache engine version has,
    so the access string excludes them as the bundled Redis ACL does;
  - that an IPv6 visitor's own address reaches nginx and Flask through
    `X-Forwarded-For` behind a dual-stack load balancer, how far rotating
    addresses within a /64 dodges the per-address limits (`DECISIONS.md`,
    "No IPv6 at the edge"), and whether a network load balancer forwarding
    IPv6 visitors over IPv4 hides their addresses;
  - that the load balancer overwrites `X-Forwarded-Proto`, which
    `behind-proxy` trusts for its redirect, and sends the target's address
    as `Host` on health checks, which `behind-proxy`'s catch-all answers;
  - nginx's memory per task (the docs say about 10-20 MB) and the
    capabilities the platform adds (believed to be `SYS_PTRACE` alone on
    Fargate, so nginx keeps the default set).
- **Behind a CDN.** Set `NGINX_TRUSTED_PROXIES` to its origin-facing
  ranges (`TRUSTED_PROXY_COUNT` stays 1). CloudFront has dozens of them:
  check whether listing them is workable or whether it wants another
  header.
- **Before launch.** The legal pages and the "Before launch" list in
  `docs/personal-data.md`.
