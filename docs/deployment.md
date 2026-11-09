# Deploying to Production

The details behind the production quick start in the [README](../README.md#production): how the stack is laid out, its secrets and database users, TLS, sending email, safe redeploys, external MySQL and Redis, container platforms, logs, and operating it: what is not included, restarts, backups and restoring, and secrets.

**Architecture (Prod)**

* MySQL → Docker, or external ([External Database or Redis](#external-database-or-redis))
* Redis → Docker, or external
* Flask (Gunicorn) → Docker
* Worker (background jobs such as email) → Docker, from Flask's image
* React → Built & served by Nginx

Only Nginx is published (ports 80 and 443). Nginx reaches only Flask; the bundled MySQL and Redis sit on an internal network with no outbound access, reachable only from Flask and the worker. Every container runs with `no-new-privileges`; Flask, the worker and Nginx run on read-only filesystems, Flask and the worker with no Linux capabilities. Redis's `default` user is disabled; the app connects as an ACL user limited to its own keys, with dangerous commands (FLUSHALL, CONFIG, KEYS, ...) refused, and the worker as one limited to the job queue's keys, which may run KEYS alone of them. Only the worker holds the mail server's password.

---

## Environment File

`.env.prod` holds only the twelve values that differ per deployment (including `SERVER_NAME`, the domain nginx serves, and the mail server and sender, [Sending Email](#sending-email)), plus `COMPOSE_PROFILES`, which runs the bundled MySQL and Redis ([External Database or Redis](#external-database-or-redis) replaces either); hosts, ports and `APP_ENV` are fixed in `docker-compose.yml`. Set strong, unique values for every password and `SECRET_KEY`. Production refuses to start with a `SECRET_KEY` shorter than 32 characters or with the example file's placeholder passwords. Generate values with:

```bash
openssl rand -hex 32
```

nginx reaches the backend at a fixed address, `10.217.0.10`, on a network of its own (`10.217.0.0/24`), so a redeployed backend is reached the moment it starts. If that range is already in use on the server, add `EDGE_SUBNET_PREFIX=10.x.y` (three numbers) to `.env.prod`.

**Database users.** The database has two users. The app's (`DB_USER`) may read and write rows but never change the schema, so a compromised backend cannot drop or alter a table. The migration user (`DB_MIGRATION_USER`) owns the schema, and only the one-off `migrate` service gets its password; the root password reaches only the `db` container. The bundled MySQL creates both when its volume is first created (`db/init/01-app-user.sh`), in every environment; for an external database, you create them ([External Database or Redis](#external-database-or-redis)). In production, the backend refuses to start if the app's user can do more than read and write rows.

**What the app reads.** The backend reads one URL per service: `DATABASE_URL` (the app's user), `REDIS_URL`, and, for `migrate` alone, `MIGRATION_DATABASE_URL`. `docker-compose.yml` builds them from the values above, and `.env.dev` and `.env.test` spell them out. The worker reads the same, with its own Redis user's URL as `REDIS_URL` (`REDIS_WORKER_URL` in `.env.prod` replaces the one built from `REDIS_WORKER_PASSWORD`), plus `EMAIL_URL` and `EMAIL_FROM`, and `SERVER_NAME`, whose first name starts every emailed link (`APP_URL` in `.env.prod`, such as `https://www.yourdomain.com`, names another). On a container platform, each password may instead come from a variable of its own (`DATABASE_PASSWORD`, `MIGRATION_DATABASE_PASSWORD`, `REDIS_PASSWORD`, `EMAIL_PASSWORD`), which replaces the one in its URL, so a secrets store can supply just the password ([Deploying to a Platform](#deploying-to-a-platform)). `docker-compose.yml` passes none of them to its containers, so with Compose the password stays in the URL. A password written inside a URL must be percent-encoded; the generator above only produces characters that need none.

### Changing a Value Later

The database keeps its own copy of its users and passwords; `.env.prod` only tells the app what they are. Editing one in `.env.prod` alone therefore breaks something: a new `DB_PASSWORD` makes the next deploy fail at `migrate` within seconds (it logs in as the app's user to check its grants): with `deploy.sh` the old backend keeps serving, while after a hand-typed `up -d`, which has already replaced the backend, the app is down, answering 502 or 504, until the password is fixed; a new `DB_MIGRATION_PASSWORD` makes the next deploy fail at `migrate` too, and the running app keeps serving only if that deploy changes nothing else (see [Redeploying](#redeploying) for a deploy that keeps it serving whatever fails). Renaming `DB_USER`, `DB_MIGRATION_USER` or `DB_NAME` on an existing database needs more than this and is not covered here. Change it in the database first, then in `.env.prod`, then run `docker compose --env-file .env.prod up -d` (with `--env-file .env.deploy` after `.env.prod` on a server that deploys [with `deploy.sh`](#redeploying)). With the bundled MySQL, which reads the `DB_*` values only when its volume is first created, for `DB_USER` or `DB_MIGRATION_USER`:

```bash
docker compose --env-file .env.prod exec db mysql -uroot -p -e "ALTER USER '<user>'@'%' IDENTIFIED BY '<new password>'"
```

For a new `DB_ROOT_PASSWORD`, change both `'root'@'%'` and `'root'@'localhost'`; nothing outside the `db` container holds it. A new `REDIS_PASSWORD` or `REDIS_WORKER_PASSWORD` (with the bundled Redis, which reads them at each start) needs only `up -d`, and so does a new `EMAIL_URL` or `EMAIL_FROM`. A new `SECRET_KEY` signs every user out.

---

## TLS Certificates

Nginx serves the app over HTTPS only (port 80 redirects to 443), so it needs a certificate in `nginx/certs/` before it will start: `fullchain.pem` and `privkey.pem`. The production and test stacks mount that folder into the container. The README shows how to [make a self-signed one](../README.md#https-certificate) for local testing and E2E; on a server, keep its key private: `chmod 600 nginx/certs/privkey.pem` (openssl already creates it that way). The nginx container can still read it, whoever owns it on the host.

### Real Domain (Let's Encrypt)

```bash
# 1. Install Certbot on your server
sudo apt install certbot  # Ubuntu/Debian

# 2. Obtain a certificate (port 80 must be free, so stop the stack first)
sudo certbot certonly --standalone -d yourdomain.com -d www.yourdomain.com
```

These steps edit tracked files, so on a server that deploys with `deploy.sh` the clone is then dirty and every later deploy refuses to start; certificate renewal without editing tracked files is not yet provided.

3. In `docker-compose.yml`, replace the nginx volume `./nginx/certs:/etc/nginx/certs:ro` with the whole Certbot directory. Its `live/` files are relative symlinks into `archive/`, so mounting only `live/` breaks them.

   ```yaml
   volumes:
     - /etc/letsencrypt:/etc/letsencrypt:ro
   ```

4. In `.env.prod`, set `SERVER_NAME=yourdomain.com www.yourdomain.com`. In `nginx/servers/tls.conf.template`, point the certificate at Certbot's paths:

   ```nginx
   ssl_certificate      /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
   ssl_certificate_key  /etc/letsencrypt/live/yourdomain.com/privkey.pem;
   ```

5. Rebuild and restart: `docker compose --env-file .env.prod build --pull --provenance=false`, then `docker compose --env-file .env.prod up -d` (on a server that deploys with `deploy.sh`, see the warning above)

Let's Encrypt certificates expire after 90 days. Renew with `certbot renew` (the standalone method needs port 80 free, so stop nginx first), then restart nginx.

---

## Sending Email

Sign-up emails a link before it makes an account, so the app takes no new users until email works. The worker sends the app's email (`backend/app/utils/mail.py`) over SMTP, through a mail provider: Amazon SES, Postmark, SendGrid, Mailgun, Resend or any other that offers SMTP, as they all do. Email sent straight from the server would mostly land in spam or nowhere: a new server's address has no sending reputation, many hosts block outbound port 25, and the large mailbox providers require the sending domain to be set up with SPF, DKIM and DMARC.

1. Sign up with a provider and add your sending domain. A subdomain such as `mail.yourdomain.com` keeps its reputation apart from your own mail.
2. Add the DNS records it gives you: SPF and DKIM, and a DMARC record (`_dmarc`), starting at `p=none` while you read its reports.
3. Create SMTP credentials and set them in `.env.prod`, in one of two forms:

   ```bash
   EMAIL_URL=smtps://<user>:<password>@<smtp host>           # TLS from the start, port 465 unless the URL names one
   EMAIL_URL=smtp+starttls://<user>:<password>@<smtp host>   # upgraded to TLS, port 587 unless the URL names one
   EMAIL_FROM="App <no-reply@mail.yourdomain.com>"
   ```

   Percent-encode any `@`, `:` or `/` in the user or password (a provider's user is often an API key or an address). Production refuses plain `smtp://`, the example file's placeholder password and its `example.com` sender. The worker reads both at start and refuses to start without them, so a deploy with a missing or refused value fails there and is rolled back.
4. Deploy, then send one email end to end. A new provider account usually starts in a sandbox that delivers only to addresses you have verified: ask for production access before launch.

The provider is a processor of your users' data: name it in the privacy notice ([Personal Data and Legal Pages](personal-data.md), "Before launch", step 3).

A failed send is retried, backing off from 15 seconds to an hour, for about three hours; one the mail server refuses for good (the address does not exist) is not. The worker's log shows each outcome: `email_sent` with the email's Message-ID, which the provider's own log shows too, or Dramatiq's line about a failed job, naming its message by id. The provider's bounce and complaint reports are yours to read: the app does not act on them, and a provider suspends an account whose bounces or complaints run high.

## Redeploying

A one-shot `migrate` container applies migrations as the migration user and exits. The backend then starts Gunicorn as the app's user, whose credentials cannot change the schema (see [Database users](#environment-file)), the worker starts beside it, and nginx starts once the backend passes its health check.

Frontend and backend code are both copied into their images, so a code change needs new images. `deploy.sh`, at the repository root, builds them on the server from the commit you name and deploys them, on any host that runs Docker:

```bash
./deploy.sh <commit>     # a commit of main; origin/main deploys the newest (the script fetches first)
./deploy.sh --latest     # the newest commit of main, unless it is deployed or failed last (for a timer)
./deploy.sh --rollback   # the commit deployed before the current one, recording the current one as failed
```

1. It refuses to start with uncommitted changes to tracked files in the clone, while another deploy runs, for a commit that isn't on `origin/main`, or for a local branch name such as `main`, which nothing keeps up to date (pass `origin/main`).
2. It checks the clone out at the commit (detached), so the compose file and `db/init` match its code, and builds the backend and nginx images, tagged with the commit: `<project>-backend:<commit>` and `<project>-nginx:<commit>`, the full commit hash. The build pulls its base images afresh, so their upstream fixes arrive with each new commit. The running app keeps serving while it builds. If the build fails, it switches back and nothing has changed.
3. It brings the bundled `db` and `redis` whose profiles are on up to the commit's settings: one whose image, command or values changed is recreated, so MySQL or Redis restarts under the running app (an external one is left alone). If one does not come up, it puts them back on the previous commit's settings, and the previous commit keeps serving. Then it runs `migrate`. If that fails, it switches back; the backend and nginx were never touched.
4. It replaces the backend, waits for it to pass its health check, then does the same for the worker (which runs the backend's image), then replaces nginx, and checks `/api/health` through nginx at the first name in `SERVER_NAME`. If any of that fails, it brings the previous commit back up the same way, from that commit's images, still on the server, and exits with an error. On a server's first deploy there is no previous commit: it leaves the failed containers as they are, so read their logs, fix the cause and deploy again.
5. Once a deploy succeeds, it removes the app's images of every other commit but the one before, so a rollback builds nothing.

A migration must keep the code before it working: the old backend serves after it runs, and a rollback brings the old code back without undoing it (add a column in one release, and drop the old one in a later release). A `db` or `redis` that came up healthy in step 3 stays too, through a failed `migrate` or a rollback, so MySQL is never downgraded; the previous code must run on it, and a MySQL upgrade that crashes partway can leave its data to repair by hand, which no rollback undoes. Take a backup ([Backups and Restoring](#backups-and-restoring)) before a commit that changes `db`'s image.

`.env.deploy`, which the script writes beside `.env.prod` (gitignored), records the deployed commit (`IMAGE_TAG`), the one before it, and the last one that failed or was rolled back from (cleared once that commit deploys by name). Pass it after `.env.prod` to every other `docker compose` command on that server, or Compose looks for images tagged `local` and builds its own: `docker compose --env-file .env.prod --env-file .env.deploy ps`. While the new backend starts, the old nginx keeps serving the page, and API requests get a JSON 502 or 504 (about 10 seconds on a small server); then connections are refused for about a second while nginx is replaced. A commit that changes `db` or `redis` adds a gap of its own in step 3: the running backend answers 503 until MySQL or Redis is back.

**An interrupted deploy.** Run the script under `nohup` or `tmux`, so a dropped SSH session cannot cut it off. One that is cut off anyway (killed, or the server rebooted) leaves `.deploy.lock` beside the script, holding its process ID, and `.env.deploy` still names the commit before it, while the clone, `db` and `redis` may be on the new commit's settings, and its backend may already run. The next deploy finds that process gone and takes the lock over. Deploy the commit you want, even the one `.env.deploy` names: the script checks what is running and what is checked out, not only what it recorded, and puts the checkout, `db` and `redis` back on that commit. Not `--rollback`, which counts back from the recorded commit, one further than you mean. If the script still says another deploy is running and none is (another process has taken the ID since a reboot, or the deploy died before writing it), remove the lock by the full path it names, as the user that deploys: `sudo -u deploy rm -r /home/deploy/app/.deploy.lock`.

**What the server needs.** Internet access while it builds (base images, Python and npm packages), and enough memory: the running stack holds about 1.2 GB (MySQL alone about 1 GB once its buffer pool fills), and building the frontend needs more on top, so start at 2 GB and add swap for the build, or pick a larger server. Docker's build cache grows with each deploy; `docker builder prune` clears it.

**Building by hand** (the README's Build and Start, without `deploy.sh`): `build --pull` checks for newer base images, so a rebuild picks up their upstream fixes (an image whose base hasn't changed keeps its ID), and `--provenance=false` keeps an unchanged image's ID. Under Docker's containerd image store (Docker Desktop, and Docker Engine 29 by default) the build's default provenance attestation records its build times, so without the flag every rebuild gets a new ID and `up -d` replaces every app container even when nothing changed. The images never leave the host, so nothing reads the attestation. (It stays a flag, not `provenance: false` under the compose file's `build:`: some Compose versions ignore that key and others refuse the whole file over it. Compose versions older than the flag lack it, so drop it there.) `deploy.sh` doesn't need it: each commit's images get new tags, so a deploy replaces the app containers anyway.

**Setting a server up.**

1. Choose who deploys. The script runs `git` and `docker`, in a clone that user owns. Anyone who can run Docker can control the whole host (a container can mount `/`), so the `docker` group is as good as root:
   * **A dedicated deploy user** (recommended): in the `docker` group, with no password and no SSH login, owning the clone. People deploy with `sudo -u deploy /home/deploy/app/deploy.sh <commit>` (by its full path: the deploy user's home is usually closed to other users, so they cannot `cd` into the clone first), so their own accounts still need `sudo`'s password for root.
   * **root**, with a clone root owns: `sudo ./deploy.sh <commit>`.
   * **Your own account in the `docker` group**: the simplest, but anyone who gets your login gets root without a password.

   For a deploy user on Linux:

   ```bash
   sudo useradd --create-home --shell /usr/sbin/nologin deploy
   sudo usermod -aG docker deploy
   ```

   Not `--system`: it hands out the highest free system uid, often 999, which the MySQL and Redis containers run as. Without [user namespaces](#the-host) a container's uid is the host's, so a process breaking out of either would own the clone and `deploy.sh`, which the deploy user runs. `id deploy` should show none of the containers' uids: 999, 101 (nginx's workers) or 10001 (the backend).

2. Clone the repository as that user. A public one:

   ```bash
   sudo -u deploy git clone https://github.com/<owner>/<repo>.git /home/deploy/app
   ```

   A private one needs a key the server keeps without a passphrase, since nobody is there to type it, added to the repository read-only (its Settings, "Deploy keys", "Allow write access" left off). Then clone over SSH:

   ```bash
   sudo -u deploy mkdir -m 700 /home/deploy/.ssh
   sudo -u deploy ssh-keygen -t ed25519 -N '' -f /home/deploy/.ssh/id_ed25519
   sudo -u deploy cat /home/deploy/.ssh/id_ed25519.pub   # add this as the deploy key
   sudo -u deploy git clone git@github.com:<owner>/<repo>.git /home/deploy/app
   ```

3. Put `.env.prod` and `nginx/certs/` in the clone, owned by that user, with `chmod 600` on `.env.prod` and the key.

On a container platform such as ECS, the platform pulls the images from a registry instead ([Deploying to a Platform](#deploying-to-a-platform)).

CI's Deploy smoke job (`.github/scripts/smoke_deploy.py`, whose docstring lists its cases) runs the script on the runner through each step above failing, its refusals, `--rollback`, `--latest` and an interrupted deploy.

### Deploying Automatically

`deploy.sh --latest`, run on a schedule, deploys every new commit of `main` within minutes of its merge. The server connects out to fetch it, so nothing has to reach the server from outside. Each run fetches `origin/main` and then:

* does nothing when its newest commit is already deployed;
* leaves it alone when it is the last commit that failed (a failed deploy, or one rolled back from with `--rollback`), until a newer commit lands on `main` or someone deploys it by name;
* otherwise deploys it as `deploy.sh <commit>` would, with the same rollback. A build that fails is not recorded, so the next run tries again (a registry or the network may have been down).

Every merge to `main` then reaches the server: the required status checks are the gate, Deploy smoke included, and anyone who can push to `main` runs code on the server as the deploy user, which can control the whole host (the `docker` group). Protect `main` accordingly.

Any scheduler works. With systemd, as the deploy user from [Setting a server up](#redeploying), these two units check every 5 minutes, starting 5 minutes after boot so the stack can come up first:

```ini
# /etc/systemd/system/app-deploy.service
[Unit]
Description=Deploy the newest commit of main
Wants=network-online.target
After=network-online.target docker.service

[Service]
Type=oneshot
User=deploy
ExecStart=/home/deploy/app/deploy.sh --latest
```

```ini
# /etc/systemd/system/app-deploy.timer
[Unit]
Description=Check main for a new commit every 5 minutes

[Timer]
OnBootSec=5min
OnUnitActiveSec=5min
RandomizedDelaySec=1min

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now app-deploy.timer
systemctl list-timers app-deploy.timer   # when it runs next
journalctl -u app-deploy.service         # what each run did
sudo systemctl start app-deploy.service  # run it now
```

With cron instead, in the deploy user's crontab (`sudo crontab -u deploy -e`), keeping the output, which grows until rotated: `*/5 * * * * /home/deploy/app/deploy.sh --latest >> /home/deploy/deploy.log 2>&1`.

* **Pausing it.** `sudo systemctl disable --now app-deploy.timer` (or comment out the cron line). Do this before deploying an older commit by name: the next run would deploy the newest one again. `--rollback` needs no pause, since it records the commit it leaves as failed.
* **A run that overlaps another deploy** is refused ("another deploy is running") and the next run tries again; systemd never starts a second run of the same unit while one is going.
* **An interrupted deploy** leaves `.deploy.lock`, which the next run takes over once the deploy's process is gone; in the rare case it cannot tell, every run fails until the lock is removed ([Redeploying](#redeploying), "An interrupted deploy"). A failed run shows as a failed unit (`systemctl --failed`) or in the log; nothing alerts you to it.

---

## External Database or Redis

The bundled MySQL and Redis containers are optional: production can use a MySQL 8 database and a Redis (or Valkey) server that run elsewhere, such as Amazon RDS and ElastiCache. Each one is switched on its own, with no code change:

1. Remove its profile from `COMPOSE_PROFILES` in `.env.prod` (`bundled-db`, `bundled-redis`), so its container no longer runs.
2. Set its URLs in `.env.prod`: `DATABASE_URL` and `MIGRATION_DATABASE_URL` for the database, `REDIS_URL` and `REDIS_WORKER_URL` for Redis (the example file's last lines show their shape). They replace the URLs `docker-compose.yml` would build. The bundled values it no longer uses can stay; Compose warns about each one you remove.

Each managed service is a processor of your users' data: see [Personal Data and Legal Pages](personal-data.md), "Before launch", step 3.

`migrate`, the backend and the worker reach an external service through the `edge` network, the one with a route out of the host.

**TLS is required.** Production treats any host other than the bundled services' names, `db` and `redis`, as outside the server, and refuses to start unless the connection is encrypted and checks the server's certificate and name. Keep those two names if you rename the services.

* The database URL needs `?ssl_ca=<path>`, a CA bundle inside the container. A database whose certificate comes from a public CA can use the image's own bundle, `/etc/ssl/certs/ca-certificates.crt`. Amazon RDS's CAs are not in it: download RDS's bundle (`https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem`) and mount it, read-only since the image is, in a `docker-compose.override.yml` beside `docker-compose.yml`, which Compose reads automatically:

  ```yaml
  services:
    migrate:
      volumes: ["./certs/rds-global-bundle.pem:/etc/ssl/rds.pem:ro"]
    backend:
      volumes: ["./certs/rds-global-bundle.pem:/etc/ssl/rds.pem:ro"]
    worker:
      volumes: ["./certs/rds-global-bundle.pem:/etc/ssl/rds.pem:ro"]
  ```

  and end both database URLs with `?ssl_ca=/etc/ssl/rds.pem`.
* The Redis URL must start with `rediss://`. ElastiCache's certificates chain to Amazon's public roots, which the image's bundle holds, so it needs nothing more; for another CA, add `?ssl_ca_certs=<path>`.
* Options that could switch either check off (`ssl_check_hostname`, `ssl_verify_cert`, `ssl_verify_identity` and `ssl_disabled` in the database URL; `ssl_cert_reqs` and `ssl_check_hostname` in the Redis URL) are refused.

**Two database users.** Create them as the provider's admin user, as the MySQL image and `db/init/01-app-user.sh` do for the bundled MySQL:

```sql
CREATE DATABASE appdb;
CREATE USER 'app_migrate'@'%' IDENTIFIED BY '<migration password>' REQUIRE SSL;
GRANT ALL PRIVILEGES ON `appdb`.* TO 'app_migrate'@'%';
CREATE USER 'app'@'%' IDENTIFIED BY '<app password>' REQUIRE SSL;
GRANT SELECT, INSERT, UPDATE, DELETE ON `appdb`.* TO 'app'@'%';
```

The database name may hold only letters, digits and `_`, and `_` is a wildcard in `GRANT`: write `app\_db` for `app_db`, since the start check refuses the unescaped form, which covers other databases too. On start-up in production, the backend and `migrate` read the grants of `DATABASE_URL`'s user and refuse to start if it holds anything beyond `SELECT`, `INSERT`, `UPDATE` and `DELETE` on its database (`USAGE` on `*.*`, MySQL's name for none, is fine): no schema rights, no rights on every database or on any other one (MySQL's own grant tables, another app's), no role and no `WITH GRANT OPTION`. There is no opt-out: a provider that offers a single database user is not supported. The admin user stays with you; neither container ever gets it.

**Redis settings the app cannot check.** Its ACL user may not read the server's configuration, so set these yourself:

* `maxmemory-policy noeviction`. Every refresh token carries an expiry, so a policy that evicts keys with one (ElastiCache's default, `volatile-lru`) silently signs users out once memory fills. On ElastiCache, use a custom parameter group.
* A user named in `REDIS_URL` (required), with the bundled ACL's rules (the `redis` service in `docker-compose.yml`): its own keys, `+@all -@dangerous`, and minus the command category of each module the server loads (`-@search -@json -@timeseries -@bloom -@cuckoo -@cms -@topk -@tdigest`), which `@dangerous` doesn't cover. On ElastiCache, an RBAC user with the access string `on ~refresh_tokens:* ~LIMITS:* ~dramatiq ~dramatiq:* +@all -@dangerous`, plus a `-@<category>` for each module your engine version offers (not yet checked against ElastiCache). An AUTH token alone, on the `default` user, is refused.
* A second user for the worker, named in `REDIS_WORKER_URL`, with the bundled ACL's `worker` rules: the job queue's keys alone, and `KEYS`, which the queue's upkeep calls, as its one dangerous command. On ElastiCache, the access string `on ~dramatiq ~dramatiq:* +@all -@dangerous +keys`, minus the same module categories.
* Cluster mode disabled: the app's Redis client is not cluster-aware. That rules out ElastiCache Serverless, which is always clustered and whose eviction policy is fixed at `volatile-lru`; use a node-based cluster.

**Network access.** Let only the server reach the database and Redis (security groups, a private network, or the provider's allowlist), never the internet.

**Passwords in URLs** must be percent-encoded; the generator in [Environment File](#environment-file) only produces characters that need none. With Compose the password must be in the URL; on a platform it can come from its own variable instead (`DATABASE_PASSWORD`, `MIGRATION_DATABASE_PASSWORD`, `REDIS_PASSWORD`), which needs no encoding.

The backend gives up on a DNS lookup after one try of 1 second (`dns_opt`, so a stopped bundled service fails fast). Pooled connections are reused, so an external host is looked up rarely, but a slow resolver can fail a request that needs a new connection.

---

## Deploying to a Platform

The Compose stack is one way to run the app. The same two images also run on a container platform (Amazon ECS on Fargate, Kubernetes, Google Cloud Run with sidecars), with managed MySQL and Redis ([External Database or Redis](#external-database-or-redis)). Nothing in the images depends on Compose: what they read from the environment is the whole contract, and `.env.prod` is only Compose's way of supplying it. The platform and each managed service it adds (a database, Redis, a log service, a CDN) are processors of your users' data: see [Personal Data and Legal Pages](personal-data.md), "Before launch", step 3.

### The Contract

**Images.** Build both for the platform's CPU (`linux/amd64`, or `linux/arm64` for Graviton), tag them with the commit, and push them to a private registry the platform pulls from (Amazon ECR on ECS):

```bash
docker build --platform linux/amd64 -t <registry>/<repo>/backend:<sha> backend
docker build --platform linux/amd64 -f nginx/Dockerfile -t <registry>/<repo>/nginx:<sha> .
```

| | backend | nginx |
|---|---|---|
| Port | 5000 (gunicorn) | 80 (`behind-proxy`) |
| Environment | `APP_ENV=production`, `SECRET_KEY`, `DATABASE_URL`, `REDIS_URL`; optionally `DATABASE_PASSWORD`, `REDIS_PASSWORD`, `WEB_CONCURRENCY` (about one per vCPU), `TRUSTED_PROXY_COUNT` | `NGINX_MODE=behind-proxy`, `NGINX_SERVER_NAME` (your domain), `NGINX_TRUSTED_PROXIES` (the load balancer's subnets), `NGINX_BACKEND_ADDRESS=127.0.0.1` |
| Filesystem | read-only root, plus a writable `/tmp` (gunicorn's worker heartbeats) | read-only root, plus writable `/etc/nginx/conf.d` (the config it renders at start), `/var/cache/nginx` and `/run` |
| Health | `GET /api/health` on 5000. Allow 60 s to start: it waits up to 60 s for MySQL and Redis, then checks its database user's grants | none of its own; the load balancer checks `/api/health` through it |

**The worker** runs from the backend image too, with the command `python worker.py`, as a service of its own with no port and no load balancer. Its environment is the backend's, except that `REDIS_URL` names the worker's Redis user (and `REDIS_PASSWORD`, if used, holds that user's password), plus `EMAIL_URL` (its password inline or in `EMAIL_PASSWORD`), `EMAIL_FROM` and `APP_URL`, your domain's origin (`https://www.yourdomain.com`), where emailed links point. It needs a writable `/tmp`, where it writes its ready file: its health check is `test -f /tmp/worker-ready`, with 60 s to start. It needs outbound access to the mail server (port 465 or 587), and nothing reaches it. On SIGTERM it lets running jobs finish for up to 25 s: give it a stop timeout of 30 s.

**Secrets.** Keep each URL without its password in plain configuration, and inject `DATABASE_PASSWORD`, `REDIS_PASSWORD`, `EMAIL_PASSWORD` and `SECRET_KEY` from the platform's secret store. Each password variable replaces its URL's password.

**Migrations** run once per deploy, before the new backend starts: the backend image with the command `flask db upgrade`, plus `MIGRATION_DATABASE_URL` (its password inline or in `MIGRATION_DATABASE_PASSWORD`; the variable alone does nothing) and `DB_QUERY_TIMEOUT=0`. Give that job its own task or job definition, so the long-running backend never holds the migration user's credentials. Rolling deploys run old and new backends side by side for a while, so a migration must keep the old code working: add a column in one release, and drop the old one in a later release.

**The client's address.** The load balancer terminates TLS and sends nginx plain HTTP with `X-Forwarded-For`. nginx trusts that header only from `NGINX_TRUSTED_PROXIES` and forwards the result to the backend, whose `TRUSTED_PROXY_COUNT` stays 1. Get the range wrong, and either every user shares the balancer's address (one rate-limit bucket, so one user can lock everyone out), or a client can choose its own address. Set `TRUSTED_PROXY_COUNT` only if you leave nginx out: 1 behind a load balancer, 2 with a CDN in front of it.

**Keep nginx in front of the backend.** It's the layer the E2E suite and the audits test: security headers and CSP, the 16 KB body cap, per-IP rate limits, JSON error bodies and unknown-host refusal. It costs about 10-20 MB per task. Replacing it means rebuilding all of that in the load balancer or CDN. Its per-IP limits count per task, so three tasks give one client three times the budget. The backend's own limits (login, register, refresh, account deletion) count in Redis and stay exact. For exact limits at the edge, use the load balancer's WAF.

CI's Platform smoke job runs this layout (the backend and a `behind-proxy` nginx sharing one network namespace, and the worker on its own) and checks health, headers, the body cap, the HTTPS redirect, the client's address and that the worker starts. Only the Compose stack gets the full E2E suite.

### What Replaces Each Compose Piece

| Compose | On a platform |
|---|---|
| `.env.prod` | the task definition's environment, plus the secret store |
| `db`, `redis` (bundled profiles) | managed MySQL and Redis: [External Database or Redis](#external-database-or-redis) |
| `migrate` and `depends_on` | a one-off task run by the deploy before the service updates |
| nginx in `tls` mode, `nginx/certs/` | a load balancer with a managed certificate, and nginx in `behind-proxy` mode |
| the backend's fixed `edge` address, `dns_opt` | `127.0.0.1`: containers in one task share a network namespace. Both are Compose-only |
| the `edge` and `internal` networks | private subnets and security groups |
| healthchecks, `restart` | the platform's container health checks and service scheduler |
| `deploy.resources` | the task's CPU and memory |
| `x-logging` rotation | the platform's log service and its retention |
| `cap_drop`, `read_only`, `no-new-privileges`, `pids_limit` | the task definition's equivalents, where the platform has them |

### Example: Amazon ECS on Fargate

A sketch of one working layout, not infrastructure code. Translate it into your own tooling (console, CloudFormation, Terraform, CDK).

1. **Images:** push both to ECR.
2. **Database and Redis:** RDS for MySQL 8 and ElastiCache for Redis OSS or Valkey (node-based, cluster mode off), set up as [External Database or Redis](#external-database-or-redis) describes. On Fargate there's no host to mount the RDS CA bundle from. It's public, so copy it into your app's backend image (`COPY certs/rds-global-bundle.pem /etc/ssl/rds.pem`).
3. **Secrets:** `SECRET_KEY`, `DATABASE_PASSWORD`, `MIGRATION_DATABASE_PASSWORD`, `REDIS_PASSWORD` (the app's user's, and the worker's for the worker), and `EMAIL_PASSWORD` in Secrets Manager, referenced from the task definitions' `secrets`.
4. **The service's task definition** (`awsvpc`; start at 1 vCPU and 2 GB):
   - `backend`: port 5000, `readonlyRootFilesystem: true` with a volume at `/tmp`, `linuxParameters.capabilities.drop: ["ALL"]`, and a health check running the same command as `docker-compose.yml`'s with `startPeriod: 60`.
   - `nginx`: port 80, `readonlyRootFilesystem: true` with volumes at `/etc/nginx/conf.d`, `/var/cache/nginx` and `/run`, `dependsOn` backend `HEALTHY`, with the `behind-proxy` variables above (`NGINX_TRUSTED_PROXIES` set to the ALB's subnets). Fargate can't add capabilities, so leave nginx's default set rather than dropping them all.
   - Both log through `awslogs` to CloudWatch Logs groups with a retention you choose ([Logs](#logs)).
5. **The worker:** a service of its own, from a task definition holding one container, the backend image with the command `python worker.py` and the variables from "The worker" above, `readonlyRootFilesystem: true` with a volume at `/tmp`, capabilities dropped, and no load balancer.
6. **Migrations:** another task definition, the backend image only, with the command and variables from "Migrations" above. The deploy runs it (`aws ecs run-task`), waits for exit code 0, then updates the service.
7. **Load balancer:** an ALB with an ACM certificate. The HTTPS listener forwards to the service's port 80, and the HTTP listener redirects to HTTPS. The target group's health check is `/api/health`, and the service's health-check grace period is at least 60 s.
8. **Security groups:** the ALB accepts 80 and 443 from the internet. The tasks accept port 80 from the ALB only, never 5000 (gunicorn listens on every interface inside the task); the worker's tasks accept nothing, and reach out to the mail server. RDS and ElastiCache accept connections from the tasks only.

**Optional: the frontend on S3 and CloudFront.** Upload `frontend/dist` to a private S3 bucket behind CloudFront, and add a CloudFront behavior that sends `/api/*` to the ALB, so the browser still calls a same-origin `/api`. Set that behavior to:

- no caching (`CachingDisabled`);
- forwarding the viewer's `Host` (`AllViewer`), or nginx drops the request.

Then:

- Copy nginx's page headers into a response headers policy (the CSP and `Permissions-Policy` from the `/` location in `nginx/app_server.conf`; HSTS, `X-Frame-Options`, `X-Content-Type-Options` and `Referrer-Policy` from `nginx/security_headers.conf`), and its caching too: `index.html` `no-cache`, `/assets/*` cached for a year.
- Route unknown paths to `index.html` with a CloudFront Function on the S3 behavior, not with custom error responses: those apply to the whole distribution and would turn the API's 404s into the page.
- Let only CloudFront reach the ALB, and add CloudFront's origin-facing ranges (AWS's `ip-ranges.json`, `CLOUDFRONT_ORIGIN_FACING`) to `NGINX_TRUSTED_PROXIES`, or every client gets a CloudFront edge's address.
- Add AWS WAF on CloudFront for exact edge rate limits.

---

## Logs

Every container logs to stdout, which Docker keeps, rotated at three files of 10 MB each (`x-logging` in `docker-compose.yml`):

```bash
docker compose --env-file .env.prod logs -f nginx backend worker
```

The backend's lines (the app's, gunicorn's, the start-up wait's, the worker's and the one-shot `migrate` service's) and nginx's access log are one JSON object per line. nginx's error log (an unreachable backend, an oversized body) is plain text, and so is the second copy of the exception gunicorn prints when a worker fails to boot.

nginx logs one request in 100 that it refuses for a client's rate (a 429), and every other request. A client flooding the API writes a few sampled lines a second instead of thousands, which would push every earlier line out of Docker's 30 MB in seconds; multiply the sampled lines by 100 for the flood's size. A single 429 a real user got is likely not in the log.

nginx's access log is the one record of each request: the client's address, the request's path, its status and how long it took. The path is logged without its query string, where a link's token would sit, and cut at 512 characters; the User-Agent and Referer are cut at 256. Each line has a `request_id`, which nginx also hands the backend: every backend line written during that request carries the same one, which joins the two.

The backend logs errors, and security events on the `app.security` logger: `login_succeeded`, `login_failed`, `registration_requested` (a sign-up link asked for, naming the address by the same keyed hash as a failed login), `registered`, `refresh_refused` (an old refresh token used again, as a stolen cookie would be), `token_invalid` (a token the app never issued, a refresh token sent as an access token, a refresh cookie without its CSRF value, or a token of a deleted or replaced account), `logout`, `logout_all`, `wrong_password` (a wrong password when deleting the account), `account_deleted` and `rate_limited`. Each names the client by address, and the user by id where there is one (`rate_limited` gives the path and the limit instead). The worker logs `email_sent` (on `app.mail`) with each email's Message-ID, and Dramatiq's lines about each job (`dramatiq.*`), which name a job's message by id: neither holds an address. A failed login names the account by `account`, a keyed hash of its email, so one guessed-at address can be followed across IPs without the log holding it. No line holds a password, token or email.

Two of these events have innocent causes too. `refresh_refused` is a lead, not proof: a refresh whose answer never reached the client (a 504 on `/api/auth/refresh` from the same address just before) has already rotated its token, so the client's next refresh is refused the same way. And after a `SECRET_KEY` rotation, every token signed with the old key logs `token_invalid` once.

Shipping logs off the server, and how long to keep them, is up to the deployment ([Not Included](#not-included)). Until they are shipped, Docker's three files per container are all there is, and they go with their container: every deploy (and rollback) replaces the backend, worker and nginx containers, so their lines reach back to the last deploy at most. Save them before a deploy if you need them (`logs --no-log-prefix nginx backend worker > <file>`). Their lines pair IP addresses with user ids, which is personal data: choose how long to keep them, say so in the privacy notice, and enforce it by age where the logs are shipped ([Personal Data and Legal Pages](personal-data.md)). nginx caps each line and how fast one address can add them, pages and API alike, which makes pushing older lines out slow for one client but not impossible for many.

---

## Operating in Production

What depends on how this template is built is covered here; what any Docker host needs is left to the tools made for it.

### Not Included

The template sets none of these up. Choose them before the server holds real data:

* **Alerts.** Nothing tells you the app is down, a deploy failed, or the disk is filling. Point an uptime checker (Uptime Kuma, healthchecks.io, a cloud provider's) at `https://<SERVER_NAME>/api/health`, which answers `{"status":"ok"}`, and watch the host's free disk and memory (Netdata, Prometheus's node exporter, the provider's agent).
* **Log shipping.** Docker keeps each container's last 30 MB and deletes them with the container, so every deploy erases the backend's and nginx's ([Logs](#logs)). Keep them past a deploy with another [Docker logging driver](https://docs.docker.com/engine/logging/configure/), set in a `docker-compose.override.yml` (untracked, so `deploy.sh` still deploys; on a systemd host, `journald` keeps them in the host's journal, which can delete them by age), and ship them off the server with an agent (Loki, Fluent Bit, CloudWatch).
* **Scheduled, off-host backups.** [Backups and Restoring](#backups-and-restoring) gives the dump and restore commands; run the dump on a schedule and copy it off the server with a backup tool (restic, borg).
* **Point-in-time recovery.** A nightly dump can lose up to a day of writes. To lose less, use a managed database ([External Database or Redis](#external-database-or-redis)), which keeps its binary log for you; the bundled MySQL keeps none.
* **Host hardening.** SSH, firewall, automatic security updates, Docker's daemon settings: follow your distribution's guide or the CIS benchmark, and check the result with Lynis and Docker Bench for Security. [The Host](#the-host) lists what this stack changes about it.
* **Encryption at rest.** Encrypt the disk that holds the MySQL volume and the dumps (LUKS or the OS's equivalent; a cloud disk's or managed database's default encryption). [Restarts](#restarts) says what it costs.
* **Certificate renewal** is not provided yet: renew by hand as [TLS Certificates](#tls-certificates) says.

### Restarts

Every long-running service has `restart: unless-stopped`, so after a reboot, a power cut or a restart of Docker itself the stack comes back by itself. Docker starts the containers in no particular order, but the backend waits for MySQL and Redis before it serves, and `migrate`, which ran at the last deploy, does not run again. With [automatic deploys](#deploying-automatically), a deploy may run a few minutes after boot.

Docker does not restart a container that runs but fails its health check; only [an alert](#not-included) tells you. With full-disk encryption, every boot waits for the passphrase at the console, so automatic updates that reboot leave the app down until someone types it; and take a virtual machine's snapshots with it powered off, since a running one's snapshot saves its memory, unlocked disk key included.

### Backups and Restoring

The bundled MySQL's volume holds everything worth keeping. Redis holds only sessions and rate-limit counters: it is not backed up, and losing it signs everyone out. Each command below runs from the clone; on a server that deploys with `deploy.sh`, add `--env-file .env.deploy` after `.env.prod` once its first deploy has written it.

**Back up** as the migration user, which owns the database. Its password is already in the `db` container, so it never appears on a command line:

```bash
(umask 077; docker compose --env-file .env.prod exec -T db sh -c \
  'MYSQL_PWD="$MYSQL_PASSWORD" mysqldump -u"$MYSQL_USER" --single-transaction --no-tablespaces "$MYSQL_DATABASE"' \
  > backup-$(date -u +%Y%m%dT%H%M%SZ).sql)
```

`--single-transaction` takes a consistent copy while the app keeps serving, of the data as it stood when the dump started. The file is named after that time, in UTC: the shell builds the name before `mysqldump` runs, so it is never later than the copy. The file holds every email and password hash: `umask 077` creates it readable by its owner alone, as private as `.env.prod`; keep it encrypted wherever it is copied, and only as long as the privacy notice says ([Personal Data and Legal Pages](personal-data.md)). Restoring it brings back accounts deleted since it was taken ([Deleted accounts come back](#deleted-accounts-come-back)). The dump holds no database users.

**Restore into the running stack** (bad data: a broken migration, a bug that deleted rows). First pause [automatic deploys](#deploying-automatically) and list the deleted accounts ([Deleted accounts come back](#deleted-accounts-come-back)), and delete them again before the last command:

```bash
docker compose --env-file .env.prod stop backend
docker compose --env-file .env.prod exec -T db sh -c \
  'MYSQL_PWD="$MYSQL_PASSWORD" mysql -u"$MYSQL_USER" -e "DROP DATABASE $MYSQL_DATABASE; CREATE DATABASE $MYSQL_DATABASE"'
docker compose --env-file .env.prod exec -T db sh -c \
  'MYSQL_PWD="$MYSQL_PASSWORD" mysql -u"$MYSQL_USER" "$MYSQL_DATABASE"' < backup-<time>.sql
docker compose --env-file .env.prod start backend
```

The second command empties the database: a dump drops and recreates only the tables it holds, so a table a later migration added would stay, and `migrate` would then fail to create it. The users' grants are on the database's name and survive. `start backend` runs `migrate` first, since the backend waits for it, and the dump brings back `alembic_version`, so a dump from before a migration is brought up to the deployed code. If `migrate` fails, the backend stays stopped: read `logs migrate`.

**Restore onto a new server** (the old one is gone or untrusted): set the server up as for a first deploy ([Redeploying](#redeploying)), then start the database alone, load the dump and deploy. First list the deleted accounts ([Deleted accounts come back](#deleted-accounts-come-back)), and delete them again before the last command:

```bash
docker compose --env-file .env.prod up -d --wait db
docker compose --env-file .env.prod exec -T db sh -c \
  'MYSQL_PWD="$MYSQL_PASSWORD" mysql -u"$MYSQL_USER" "$MYSQL_DATABASE"' < backup-<time>.sql
./deploy.sh <commit>
```

The new volume creates both database users from `.env.prod`, so this works with new passwords too.

**Accounts created after the backup are gone**, and MySQL hands their ids out again from where the dump left off. Their devices still look signed in, but their next request is refused: every token names its account by id and creation time, so it never works as the account that takes the id next. Losing those accounts and every write since the backup is a personal data breach: record it ([Personal Data and Legal Pages](personal-data.md)).

**Watch free disk.** When the disk fills, writes that need new space fail at once with 503s while every health check stays green; they succeed again as soon as space is freed.

#### Deleted accounts come back

Any restore, a managed database's snapshot included, brings back the accounts deleted since the backup was taken, with everything they owned, and their owners can log in again. Delete them again before the app serves:

1. Before restoring, list the `account_deleted` events logged since the backup's time. Docker's own logs reach back only to the last deploy, and are gone on a new server, so read the shipped logs where you have them ([Logs](#logs)):

   ```bash
   docker compose --env-file .env.prod logs --no-log-prefix backend | grep '"message": "account_deleted"' \
     | sed -E 's/.*"time": "([^"]+)".*"user_id": ([0-9]+).*/\1 \2/'
   ```

   Each line is one deletion's time and user id. Keep the ids deleted after the backup's start time: for a dump, the time in its file name, in UTC as the log is. `--single-transaction` copies the data as it stood then, so an account deleted while the dump ran is still in it. An id deleted before that time is not in the dump, so deleting it again does nothing.

2. After loading the dump, and before `start backend` (or `deploy.sh` on a new server), delete them as the migration user. A restored row keeps its id, and the database deletes the rest of each account's rows:

   ```bash
   docker compose --env-file .env.prod exec -T db sh -c \
     'MYSQL_PWD="$MYSQL_PASSWORD" mysql -u"$MYSQL_USER" "$MYSQL_DATABASE" -e "DELETE FROM users WHERE id IN (<ids>)"'
   ```

### Secrets Off the Host

`.env.prod` and the TLS certificate and key in `nginx/certs/` exist only on the server. Keep a copy in a password manager or a secrets store, so a new server can start with the same values.

**After a compromise**, issue new secrets rather than restoring the old ones: a new `SECRET_KEY`, new database and Redis passwords ([Changing a Value Later](#changing-a-value-later)), and a new TLS key and certificate. For a private repository, remove the old server's deploy key in the repository's settings and make a new one on the new server. Treat any dump that was on the old server as exposed: every email and password hash in it. Restore onto a new server rather than cleaning the old one.

### The Host

* Ports Docker publishes (nginx's 80 and 443) bypass host firewalls such as `ufw`, so `ufw status` does not show what is reachable. Check from another machine: nginx's ports answer over IPv4 only, and IPv6 should be refused on them; check SSH over both.
* Publish an A record for `SERVER_NAME`, not an AAAA record: nginx listens on IPv4 only, since Docker would otherwise relay every IPv6 visitor from one address, sharing one rate-limit bucket. A visitor whose browser tries IPv6 falls back to IPv4. Serving IPv6 would need IPv6 on the `edge` network and rate limits keyed on each visitor's /64, which the template does not do.
* Anyone in the `docker` group can control the whole host; without it, Docker commands need `sudo` ([Redeploying](#redeploying), "Setting a server up").
* Docker's daemon settings from the CIS benchmark, `"live-restore": true`, `"icc": false`, `"no-new-privileges": true` and `"userland-proxy": false` in `/etc/docker/daemon.json`, need no change to the stack. `live-restore` also keeps the site up while Docker itself restarts or upgrades.
* User namespaces (`"userns-remap": "default"`) run each container's users as unprivileged host uids, so none owns anything on the host. The stack runs under them with two changes:
  * nginx reads the TLS key as the remapped root, which its `DAC_READ_SEARCH` no longer covers: give the key the first id of `dockremap`'s range in `/etc/subgid` as its group, `sudo chgrp <id> nginx/certs/privkey.pem && sudo chmod 640 nginx/certs/privkey.pem`.
  * Docker keeps a separate store under them, without the images or the database volume. Take a dump ([Backups and Restoring](#backups-and-restoring)), stop the stack with `down`, not `stop`, turn them on and restart Docker, deploy, then restore the dump. A stopped stack's networks stay on the host, and the host then routes the `edge` subnet to the old, empty bridge instead of the new one: the site times out. Switching back works the same way.
* Docker Bench for Security warns about choices the stack makes on purpose: the `db` and `redis` images start as root (their entrypoints then run MySQL and Redis as their own users), nginx keeps `DAC_READ_SEARCH` (to read the key whoever owns it) and publishes the privileged ports 80 and 443 on every IPv4 address, health checks live in the compose file rather than the images, and Docker Content Trust is off (the images are built on the server).
* An installer may leave the root volume much smaller than the disk. Check free space before the first deploy: builds and images take several GB.
* A `docker compose up -d` that fails can wait about a minute and a quarter (the health checks' retries) before it reports anything. Let it finish: one stopped partway through replacing a container can leave the old one renamed `<id>_app-backend-1`, and the next `up` then fails with a name conflict while the API answers 504. Remove the backend's containers, which hold no data, and start it again (`<project>` is `name:` in `docker-compose.yml`, `app` in the template; never do this to `db` or `redis`; add `--env-file .env.deploy` on a server that deploys with `deploy.sh`):

  ```bash
  docker ps -aq --filter label=com.docker.compose.project=<project> --filter label=com.docker.compose.service=backend | xargs -r docker rm -f
  docker compose --env-file .env.prod up -d --wait
  ```
