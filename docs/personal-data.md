# Personal Data and Legal Pages

Every app built from the template collects personal data from its first sign-up, so it ships placeholder legal pages that each app must write for itself. None of this is legal advice: have a lawyer review the pages before launch.

**What ships:**
- `/privacy`, `/terms` and `/contact` (`frontend/src/pages/`), linked from the footer of every page. Each opens with a placeholder notice and gives one heading per topic, with what to write in brackets.
- `frontend/src/legal.js`: the operator's name, address and contact email, which the pages show, and `TERMS_VERSION`.
- A required checkbox on the register form, "I accept the Terms and the Privacy notice". The form sends the version it showed, the backend refuses any but the current `TERMS_VERSION` (`backend/app/auth/models.py`) with a 409 `TERMS_OUTDATED`, and `users` records `terms_version` and `terms_accepted_at`.
- `frontend/public/.well-known/security.txt` (RFC 9116), where to report a security problem.

**What the template keeps about people:**

| Data | Where | How long |
|---|---|---|
| Email, password hash, when registered, terms version and when accepted | MySQL `users` | Until the user deletes the account (Account page) |
| Users' content (the notes example) | The feature's tables | Until the user deletes it or the account |
| Every write, deleted rows included | MySQL's binary log | 30 days (MySQL's default) |
| Refresh-token ids, at most 10 per user | Redis | Until the session expires (7 days idle, 30 at most), logs out or deletes the account |
| Rate-limit counters: per IP, per keyed hash of an email, per user | Redis | A minute to an hour |
| Access log: IP, path (no query string), status, timings, User-Agent, Referer | nginx's stdout, kept by Docker | Until Docker's 3 × 10 MB rotate out |
| Security events: IP, user id; a keyed hash of the typed email on a failed login | The backend's stdout, kept by Docker | The same |
| Access token, refresh CSRF value, email | The browser's `localStorage` | Until logout or the session ends |
| Refresh token | Cookie `__Secure-refresh_token` (HttpOnly) | Up to 30 days |

Deleting an account (the Account page asks for the password) deletes its `users` row, every feature's rows that reference it, and its sessions in Redis, at once. What the logs and MySQL's binary log hold about it goes as they age out, and so would its copies in backups, by their own retention: state that in the privacy notice.

No analytics, no third-party requests and no email: the template itself sends nothing to a third party, though your host and any managed service you add are processors. The cookie and `localStorage` are strictly necessary for the login the user asked for, so no consent banner is needed.

**Before launch:**
1. Fill in `legal.js`, then write the three pages for your app from the table above and your own features.
2. Choose how long to keep logs (France's CNIL suggests 6 to 12 months for security logs), state it in the privacy notice, and enforce it by age once logs are shipped ([Logs](deployment.md#logs)). Decide the MySQL binary log together with backups: keep it for point-in-time recovery, or turn it off.
3. Name every provider that processes personal data for you (the host, a log service, a CDN, an email service) in the privacy notice, and sign each one's data processing agreement. If one processes EU or UK users' data outside the EU/EEA or UK, note the transfer safeguard in the notice (an adequacy decision, or the standard contractual clauses in its agreement), or choose a region inside.
4. Set `security.txt`'s `Contact` to the email in `legal.js` (a test checks they match) and `Expires` to under a year away, and renew `Expires` every year (the same test fails from 30 days before it lapses).
5. Ask the lawyer whether your markets need a checkbox or whether a sentence beside the button would do, and whether a German audience needs the contact page labelled "Impressum" with more details on it.
6. Check whether the European Accessibility Act covers your service (e-commerce, banking and a few other sectors; microenterprises are exempt).
7. When the terms change, raise `TERMS_VERSION` in both `legal.js` and `backend/app/auth/models.py`. Asking existing users to accept the new terms is your app's job.

**Duties that start with a feature:**
- **Content other users can see** (sharing, profiles, comments, uploads): a way to report illegal content (EU Digital Services Act, Art. 16), and in the US a DMCA agent and a repeat-infringer policy.
- **Children:** an audience under 13, or knowing that a user is, brings COPPA, and consent-based processing the GDPR's age of consent.
- **Email** (verification, password reset, newsletters): CAN-SPAM, PECR and CASL.
