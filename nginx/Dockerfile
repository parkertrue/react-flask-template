# ---------- Stage 1: build frontend ----------
FROM node:24-alpine AS build
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
# Compress once here so nginx serves the .gz (gzip_static) instead of
# compressing the same bundle on every request. Tiny files aren't worth it.
RUN npm run build \
    && find dist -type f -size +1k \
      \( -name '*.js' -o -name '*.css' -o -name '*.html' -o -name '*.svg' \) \
      -exec gzip -9 -k {} +

# ---------- Stage 2: nginx ----------
# Pinned so a rebuild never silently changes the web server version
FROM nginx:1.31-alpine
RUN rm /etc/nginx/nginx.conf /etc/nginx/conf.d/default.conf
COPY nginx/nginx.conf /etc/nginx/nginx.conf
COPY nginx/proxy_params.conf /etc/nginx/proxy_params.conf
COPY nginx/security_headers.conf /etc/nginx/security_headers.conf
COPY nginx/resource_headers.conf /etc/nginx/resource_headers.conf
COPY nginx/app_server.conf /etc/nginx/app_server.conf
COPY nginx/templates /etc/nginx/templates
COPY nginx/servers /etc/nginx/servers
# After the image's own 20-envsubst-on-templates.sh; picks the servers for
# NGINX_MODE and trusts NGINX_TRUSTED_PROXIES' X-Forwarded-For (see the script)
COPY --chmod=755 nginx/server-mode.sh /docker-entrypoint.d/25-server-mode.sh
# tls: nginx is the edge and serves HTTPS with nginx/certs/. behind-proxy: a
# load balancer terminates TLS and NGINX_TRUSTED_PROXIES must name it (README,
# Deploying to a Platform).
ENV NGINX_MODE=tls
# Production rate limits, per client IP; see templates/
# The auth rate covers login and register together. Flask's own limits are
# tighter per account; this one only has to stop a single address flooding.
# The page rate is far above what a person loading pages needs.
ENV NGINX_AUTH_RATE=20r/m NGINX_API_RATE=30r/s NGINX_PAGE_RATE=10r/s
# docker-compose.yml sets the real domain; localhost serves the test stack.
ENV NGINX_SERVER_NAME=localhost
# Only NGINX_* variables are substituted into templates/, so no other
# environment variable can leak into the config.
ENV NGINX_ENVSUBST_FILTER=^NGINX_
# nginx.conf's "worker_processes auto" means one worker per host CPU, however
# few CPUs the container may use (20 workers under a 0.5-CPU limit and a
# 64-process cap). The image's start-up script resizes it to the container's
# CPU limit when this is set.
ENV NGINX_ENTRYPOINT_WORKER_PROCESSES_AUTOTUNE=1
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80 443
CMD ["nginx", "-g", "daemon off;"]
