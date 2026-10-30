# Deploying to Production

The details behind the production quick start in the [README](../README.md#production): how the stack is laid out, its secrets and database users, TLS, safe redeploys, external MySQL and Redis, container platforms, and logs.

**Architecture (Prod)**

* MySQL → Docker, or external ([External Database or Redis](#external-database-or-redis))
* Redis → Docker, or external
* Flask (Gunicorn) → Docker
* React → Built & served by Nginx

Only Nginx is published (ports 80 and 443). Nginx reaches only Flask; the bundled MySQL and Redis sit on an internal network with no outbound access, reachable only from Flask. Every container runs with `no-new-privileges`, Flask on a read-only filesystem with no Linux capabilities. Redis's `default` user is disabled; the app connects as an ACL user limited to its own keys, with dangerous commands (FLUSHALL, CONFIG, KEYS, ...) refused.

---

## Environment File

`.env.prod` holds only the nine values that differ per deployment (including `SERVER_NAME`, the domain nginx serves), plus `COMPOSE_PROFILES`, which runs the bundled MySQL and Redis ([External Database or Redis](#external-database-or-redis) replaces either); hosts, ports and `APP_ENV` are fixed in `docker-compose.yml`. Set strong, unique values for every password and `SECRET_KEY`. Production refuses to start with a `SECRET_KEY` shorter than 32 characters or with the example file's placeholder passwords. Generate values with:

```bash
openssl rand -hex 32
```

nginx reaches the backend at a fixed address, `10.217.0.10`, on a network of its own (`10.217.0.0/24`), so a redeployed backend is reached the moment it starts. If that range is already in use on the server, add `EDGE_SUBNET_PREFIX=10.x.y` (three numbers) to `.env.prod`.

**Database users.** The database has two users. The app's (`DB_USER`) may read and write rows but never change the schema, so a compromised backend cannot drop or alter a table. The migration user (`DB_MIGRATION_USER`) owns the schema, and only the one-off `migrate` service gets its password; the root password reaches only the `db` container. The bundled MySQL creates both when its volume is first created (`db/init/01-app-user.sh`), in every environment; for an external database, you create them ([External Database or Redis](#external-database-or-redis)). In production, the backend refuses to start if the app's user can do more than read and write rows.

**What the app reads.** The backend reads one URL per service: `DATABASE_URL` (the app's user), `REDIS_URL`, and, for `migrate` alone, `MIGRATION_DATABASE_URL`. `docker-compose.yml` builds them from the values above, and `.env.dev` and `.env.test` spell them out. On a container platform, each password may instead come from a variable of its own (`DATABASE_PASSWORD`, `MIGRATION_DATABASE_PASSWORD`, `REDIS_PASSWORD`), which replaces the one in its URL, so a secrets store can supply just the password ([Deploying to a Platform](#deploying-to-a-platform)). `docker-compose.yml` passes none of them to its containers, so with Compose the password stays in the URL. A password written inside a URL must be percent-encoded; the generator above only produces characters that need none.

### Changing a Value Later

The database keeps its own copy of its users and passwords; `.env.prod` only tells the app what they are. Editing one in `.env.prod` alone therefore breaks something: a new `DB_PASSWORD` makes the next deploy fail at `migrate` within seconds (it logs in as the app's user to check its grants), and the app is down, answering 502 or 504, until the password is fixed; a new `DB_MIGRATION_PASSWORD` makes the next deploy fail at `migrate` too, and the running app keeps serving only if that deploy changes nothing else (see [Redeploying](#redeploying) for a deploy that keeps it serving whatever fails). Renaming `DB_USER`, `DB_MIGRATION_USER` or `DB_NAME` on an existing database needs more than this and is not covered here. Change it in the database first, then in `.env.prod`, then run `docker compose --env-file .env.prod up -d`. With the bundled MySQL, which reads the `DB_*` values only when its volume is first created, for `DB_USER` or `DB_MIGRATION_USER`:

```bash
docker compose --env-file .env.prod exec db mysql -uroot -p -e "ALTER USER '<user>'@'%' IDENTIFIED BY '<new password>'"
```

For a new `DB_ROOT_PASSWORD`, change both `'root'@'%'` and `'root'@'localhost'`; nothing outside the `db` container holds it. A new `REDIS_PASSWORD` needs only `up -d`. A new `SECRET_KEY` signs every user out.

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

5. Rebuild and restart: `docker compose --env-file .env.prod up -d --build`

Let's Encrypt certificates expire after 90 days. Renew with `certbot renew` (the standalone method needs port 80 free, so stop nginx first), then restart nginx.

---

## Redeploying

A one-shot `migrate` container applies migrations as the migration user and exits. The backend then starts Gunicorn as the app's user, whose credentials cannot change the schema (see [Database users](#environment-file)), and nginx starts once the backend passes its health check.

Frontend and backend code are both copied into their images, so rebuild after any code change. A single `up -d --build` replaces the backend before `migrate` runs, so if `migrate` fails (a bad migration, a wrong password, an unreachable database), the app is down until it is fixed. Build and migrate first instead; the running app keeps serving through both, and each command stops the deploy if it fails:

```bash
docker compose --env-file .env.prod build --provenance=false \
  && docker compose --env-file .env.prod up --exit-code-from migrate migrate \
  && docker compose --env-file .env.prod up -d --wait
```

`--provenance=false` keeps an unchanged image's ID: under Docker's containerd image store (Docker Desktop, and Docker Engine 29 by default) the build's default provenance attestation records its build times, so without the flag every rebuild gets a new ID and `up -d` replaces every app container even when nothing changed. The images never leave the host, so nothing reads the attestation. (Compose 5.0 ignores `provenance: false` under the compose file's `build:`, so it stays a flag.) When the build changed an image, the last command replaces the backend and nginx, so requests get a 502 or 504, or a refused connection, for a few seconds. A migration must keep the old code working, since the old backend serves after it runs ([Deploying to a Platform](#deploying-to-a-platform), Migrations).

---

## External Database or Redis

The bundled MySQL and Redis containers are optional: production can use a MySQL 8 database and a Redis (or Valkey) server that run elsewhere, such as Amazon RDS and ElastiCache. Each one is switched on its own, with no code change:

1. Remove its profile from `COMPOSE_PROFILES` in `.env.prod` (`bundled-db`, `bundled-redis`), so its container no longer runs.
2. Set its URLs in `.env.prod`: `DATABASE_URL` and `MIGRATION_DATABASE_URL` for the database, `REDIS_URL` for Redis (the example file's last lines show their shape). They replace the URLs `docker-compose.yml` would build. The bundled values it no longer uses can stay; Compose warns about each one you remove.

Each managed service is a processor of your users' data: see [Personal Data and Legal Pages](personal-data.md), "Before launch", step 3.

`migrate` and the backend reach an external service through the `edge` network, the one with a route out of the host.

**TLS is required.** Production treats any host other than the bundled services' names, `db` and `redis`, as outside the server, and refuses to start unless the connection is encrypted and checks the server's certificate and name. Keep those two names if you rename the services.

* The database URL needs `?ssl_ca=<path>`, a CA bundle inside the container. A database whose certificate comes from a public CA can use the image's own bundle, `/etc/ssl/certs/ca-certificates.crt`. Amazon RDS's CAs are not in it: download RDS's bundle (`https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem`) and mount it, read-only since the image is, in a `docker-compose.override.yml` beside `docker-compose.yml`, which Compose reads automatically:

  ```yaml
  services:
    migrate:
      volumes: ["./certs/rds-global-bundle.pem:/etc/ssl/rds.pem:ro"]
    backend:
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
* A user named in `REDIS_URL` (required), with the bundled ACL's rules: on ElastiCache, an RBAC user with the access string `on ~refresh_tokens:* ~LIMITS:* +@all -@dangerous`. An AUTH token alone, on the `default` user, is refused.
* Cluster mode disabled: the app's Redis client is not cluster-aware. That rules out ElastiCache Serverless, which is always clustered and whose eviction policy is fixed at `volatile-lru`; use a node-based cluster.

**Network access.** Let only the server reach the database and Redis (security groups, a private network, or the provider's allowlist), never the internet.

**Passwords in URLs** must be percent-encoded; the generator in [Environment File](#environment-file) only produces characters that need none. With Compose the password must be in the URL; on a platform it can come from its own variable instead (`DATABASE_PASSWORD`, `MIGRATION_DATABASE_PASSWORD`, `REDIS_PASSWORD`), which needs no encoding.

The backend gives up on a DNS lookup after one try of 1 second (`dns_opt`, so a stopped bundled service fails fast). Pooled connections are reused, so an external host is looked up rarely, but a slow resolver can fail a request that needs a new connection.

---

## Deploying to a Platform

The Compose stack is one way to run the app. The same two images also run on a container platform (Amazon ECS on Fargate, Kubernetes, Google Cloud Run with sidecars), with managed MySQL and Redis ([External Database or Redis](#external-database-or-redis)). Nothing in the images depends on Compose: what they read from the environment is the whole contract, and `.env.prod` is only Compose's way of supplying it. The platform and each managed service it adds (a database, Redis, a log service, a CDN) are processors of your users' data: see [Personal Data and Legal Pages](personal-data.md), "Before launch", step 3.

### The Contract

**Images.** Build both for the platform's CPU (`--platform linux/amd64`, or `linux/arm64` for Graviton) and tag them with the commit:

```bash
docker build --platform linux/amd64 -t <registry>/app-backend:<sha> backend
docker build --platform linux/amd64 -f nginx/Dockerfile -t <registry>/app-nginx:<sha> .
```

| | backend | nginx |
|---|---|---|
| Port | 5000 (gunicorn) | 80 (`behind-proxy`) |
| Environment | `APP_ENV=production`, `SECRET_KEY`, `DATABASE_URL`, `REDIS_URL`; optionally `DATABASE_PASSWORD`, `REDIS_PASSWORD`, `WEB_CONCURRENCY` (about one per vCPU), `TRUSTED_PROXY_COUNT` | `NGINX_MODE=behind-proxy`, `NGINX_SERVER_NAME` (your domain), `NGINX_TRUSTED_PROXIES` (the load balancer's subnets), `NGINX_BACKEND_ADDRESS=127.0.0.1` |
| Filesystem | read-only root, plus a writable `/tmp` (gunicorn's worker heartbeats) | writable: it renders its config into `/etc/nginx/conf.d` at start |
| Health | `GET /api/health` on 5000. Allow 60 s to start: it waits up to 60 s for MySQL and Redis, then checks its database user's grants | none of its own; the load balancer checks `/api/health` through it |

**Secrets.** Keep each URL without its password in plain configuration, and inject `DATABASE_PASSWORD`, `REDIS_PASSWORD` and `SECRET_KEY` from the platform's secret store. Each password variable replaces its URL's password.

**Migrations** run once per deploy, before the new backend starts: the backend image with the command `flask db upgrade`, plus `MIGRATION_DATABASE_URL` (its password inline or in `MIGRATION_DATABASE_PASSWORD`; the variable alone does nothing) and `DB_QUERY_TIMEOUT=0`. Give that job its own task or job definition, so the long-running backend never holds the migration user's credentials. Rolling deploys run old and new backends side by side for a while, so a migration must keep the old code working: add a column in one release, and drop the old one in a later release.

**The client's address.** The load balancer terminates TLS and sends nginx plain HTTP with `X-Forwarded-For`. nginx trusts that header only from `NGINX_TRUSTED_PROXIES` and forwards the result to the backend, whose `TRUSTED_PROXY_COUNT` stays 1. Get the range wrong, and either every user shares the balancer's address (one rate-limit bucket, so one user can lock everyone out), or a client can choose its own address. Set `TRUSTED_PROXY_COUNT` only if you leave nginx out: 1 behind a load balancer, 2 with a CDN in front of it.

**Keep nginx in front of the backend.** It's the layer the E2E suite and the audits test: security headers and CSP, the 16 KB body cap, per-IP rate limits, JSON error bodies and unknown-host refusal. It costs about 10-20 MB per task. Replacing it means rebuilding all of that in the load balancer or CDN. Its per-IP limits count per task, so three tasks give one client three times the budget. The backend's own limits (login, register, refresh, account deletion) count in Redis and stay exact. For exact limits at the edge, use the load balancer's WAF.

CI's Platform smoke job runs this layout (the backend and a `behind-proxy` nginx sharing one network namespace) and checks health, headers, the body cap, the HTTPS redirect and the client's address. Only the Compose stack gets the full E2E suite.

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
3. **Secrets:** `SECRET_KEY`, `DATABASE_PASSWORD`, `MIGRATION_DATABASE_PASSWORD` and `REDIS_PASSWORD` in Secrets Manager, referenced from the task definitions' `secrets`.
4. **The service's task definition** (`awsvpc`; start at 1 vCPU and 2 GB):
   - `backend`: port 5000, `readonlyRootFilesystem: true` with a volume at `/tmp`, `linuxParameters.capabilities.drop: ["ALL"]`, and a health check running the same command as `docker-compose.yml`'s with `startPeriod: 60`.
   - `nginx`: port 80, `dependsOn` backend `HEALTHY`, with the `behind-proxy` variables above (`NGINX_TRUSTED_PROXIES` set to the ALB's subnets). Fargate can't add capabilities, so leave nginx's default set rather than dropping them all.
   - Both log through `awslogs` to CloudWatch Logs groups with a retention you choose ([Logs](#logs)).
5. **Migrations:** a second task definition, the backend image only, with the command and variables from "Migrations" above. The deploy runs it (`aws ecs run-task`), waits for exit code 0, then updates the service.
6. **Load balancer:** an ALB with an ACM certificate. The HTTPS listener forwards to the service's port 80, and the HTTP listener redirects to HTTPS. The target group's health check is `/api/health`, and the service's health-check grace period is at least 60 s.
7. **Security groups:** the ALB accepts 80 and 443 from the internet. The tasks accept port 80 from the ALB only, never 5000 (gunicorn listens on every interface inside the task). RDS and ElastiCache accept connections from the tasks only.

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
docker compose --env-file .env.prod logs -f nginx backend
```

The backend's lines (the app's, gunicorn's, the start-up wait's and the one-shot `migrate` service's) and nginx's access log are one JSON object per line. nginx's error log (an unreachable backend, an oversized body) is plain text, and so is the second copy of the exception gunicorn prints when a worker fails to boot.

nginx logs one request in 100 that it refuses for a client's rate (a 429), and every other request. A client flooding the API writes a few sampled lines a second instead of thousands, which would push every earlier line out of Docker's 30 MB in seconds; multiply the sampled lines by 100 for the flood's size. A single 429 a real user got is likely not in the log.

nginx's access log is the one record of each request: the client's address, the request's path, its status and how long it took. The path is logged without its query string, where a link's token would sit, and cut at 512 characters; the User-Agent and Referer are cut at 256. Each line has a `request_id`, which nginx also hands the backend: every backend line written during that request carries the same one, which joins the two.

The backend logs errors, and security events on the `app.security` logger: `login_succeeded`, `login_failed`, `registered`, `refresh_refused` (an old refresh token used again, as a stolen cookie would be), `token_invalid` (a token the app never issued, a refresh token sent as an access token, a refresh cookie without its CSRF value, or a deleted account's token), `logout`, `logout_all`, `wrong_password` (a wrong password when deleting the account), `account_deleted` and `rate_limited`. Each names the client by address, and the user by id where there is one (`rate_limited` gives the path and the limit instead). A failed login names the account by `account`, a keyed hash of its email, so one guessed-at address can be followed across IPs without the log holding it. No line holds a password, token or email.

Two of these events have innocent causes too. `refresh_refused` is a lead, not proof: a refresh whose answer never reached the client (a 504 on `/api/auth/refresh` from the same address just before) has already rotated its token, so the client's next refresh is refused the same way. And after a `SECRET_KEY` rotation, every token signed with the old key logs `token_invalid` once.

Shipping logs off the server, and how long to keep them, is up to the deployment. Until they are shipped, Docker's three files per container are all there is. Their lines pair IP addresses with user ids, which is personal data: choose how long to keep them, say so in the privacy notice, and enforce it by age where the logs are shipped ([Personal Data and Legal Pages](personal-data.md)). nginx caps each line and how fast one address can add them, pages and API alike, which makes pushing older lines out slow for one client but not impossible for many.
