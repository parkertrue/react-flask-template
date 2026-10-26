#!/bin/sh
# Run by the nginx image's entrypoint before nginx starts (/docker-entrypoint.d/),
# after it has rendered templates/. A non-zero exit stops the container.
#
# Writes into /etc/nginx/conf.d/:
# - default.conf, the servers for NGINX_MODE: tls (nginx is the edge) or
#   behind-proxy (a load balancer terminates TLS), from servers/;
# - real-ip.conf, which takes the client's address from X-Forwarded-For when
#   the request comes from one of NGINX_TRUSTED_PROXIES (CIDRs, separated by
#   spaces or commas). behind-proxy requires it, or every client would share
#   the balancer's address and its rate limits; tls mode takes it for a CDN
#   in front.
set -eu

fail() {
    echo "$0: $1" >&2
    exit 1
}

mode="${NGINX_MODE:-}"
case "$mode" in
    tls | behind-proxy) ;;
    *) fail "NGINX_MODE must be tls or behind-proxy, not '$mode'" ;;
esac

proxies=$(printf '%s' "${NGINX_TRUSTED_PROXIES:-}" | tr ',' ' ')
real_ip=/etc/nginx/conf.d/real-ip.conf
: > "$real_ip"
for cidr in $proxies; do
    # Only an address and prefix length reach the config: nothing that could
    # end the directive or name a host. nginx checks the address itself.
    case "$cidr" in
        *[!0-9a-fA-F:./]* | /* | */*/*) fail "NGINX_TRUSTED_PROXIES: '$cidr' is not a CIDR" ;;
        */[0-9] | */[0-9][0-9] | */[0-9][0-9][0-9]) ;;
        *) fail "NGINX_TRUSTED_PROXIES: '$cidr' is not a CIDR" ;;
    esac
    # Trusting every address lets any client name its own
    case "$cidr" in
        */0 | */00 | */000) fail "NGINX_TRUSTED_PROXIES: '$cidr' trusts every address" ;;
    esac
    echo "set_real_ip_from $cidr;" >> "$real_ip"
done
if [ -s "$real_ip" ]; then
    {
        echo 'real_ip_header X-Forwarded-For;'
        # The rightmost address not in the list: whatever a client put before
        # it in the header is ignored
        echo 'real_ip_recursive on;'
    } >> "$real_ip"
elif [ "$mode" = behind-proxy ]; then
    fail "NGINX_MODE=behind-proxy needs NGINX_TRUSTED_PROXIES, the load balancer's addresses"
fi

envsubst '${NGINX_SERVER_NAME}' < "/etc/nginx/servers/$mode.conf.template" \
    > /etc/nginx/conf.d/default.conf
