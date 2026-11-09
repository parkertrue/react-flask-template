#!/bin/bash
# Deploys one commit of main, or rolls back to the one before
# (docs/deployment.md, Redeploying):
#
#   ./deploy.sh <commit>     build that commit's images and deploy them
#   ./deploy.sh --latest     deploy the newest commit of main, unless it is
#                            deployed already or failed last (for a timer)
#   ./deploy.sh --rollback   deploy the previously deployed commit again,
#                            recording the current one as failed
#
# Run it as a user who can run Docker, in a clone that user owns, beside
# .env.prod. The images are built here, from the commit, and tagged with it
# (<project>-backend:<commit>, <project>-nginx:<commit>; the worker runs the
# backend's); the deployed and previous commits' images are kept, so a
# rollback builds nothing.
#
# The checkout moves to the commit, so the compose file and db/init match its
# images. The bundled db and redis that are enabled come up first, on the
# commit's settings: one that changed restarts under the running app, and one
# that fails to start is put back on the previous commit's. migrate runs
# before the app is replaced, so a failed migration leaves it serving; and if
# the new app does not come up healthy, the previous commit is brought back.
# A db or redis that came up healthy stays, and migrations are never undone:
# each must keep the code before it working. .env.deploy records the
# deployed, previous and last failed commit; pass it to every docker compose
# command after .env.prod, so a hand-typed one runs the deployed images.
set -euo pipefail

cd "$(dirname "$0")"

BRANCH=main
STATE=.env.deploy
LOCK=.deploy.lock
WAIT_SECONDS=300

log() { echo "deploy: $*"; }
die() { echo "deploy: $*" >&2; exit 1; }

state() { if [ -f "$STATE" ]; then sed -n "s/^$1=//p" "$STATE" | tail -n 1; fi; }

write_state() {
    printf 'IMAGE_TAG=%s\nPREVIOUS_IMAGE_TAG=%s\nFAILED_IMAGE_TAG=%s\n' "$1" "$2" "$3" > "$STATE.tmp"
    mv "$STATE.tmp" "$STATE"
}

# Every compose command runs one commit's images: IMAGE_TAG from the shell
# wins over the env file
compose() { IMAGE_TAG="$tag" docker compose --env-file .env.prod "$@"; }

checkout() { git -c advice.detachedHead=false checkout --quiet --detach "$1"; }

# The app's two images, without their tag
repositories() {
    local project
    project=$(compose config | sed -n 's/^name: //p')
    echo "$project-backend" "$project-nginx"
}

# Builds the checked-out commit's images, unless they are still here from
# an earlier deploy
build() {
    local repository
    for repository in $(repositories); do
        if ! docker image inspect "$repository:$tag" > /dev/null 2>&1; then
            log "building $tag"
            # --pull, or the base images stay as first pulled, without
            # their upstream fixes
            compose build --pull backend nginx
            return
        fi
    done
    log "using the images already built for $tag"
}

# Removes every tag of the app's images but the two commits kept
prune() {
    local repository image
    for repository in $(repositories); do
        for image in $(docker image ls --format '{{.Repository}}:{{.Tag}}' "$repository"); do
            case "$image" in
                "$repository:$1" | "$repository:$2") ;;
                *) docker image rm "$image" > /dev/null || log "could not remove $image" ;;
            esac
        done
    done
}

# The app's long-running services that the checked-out commit defines, in
# the order start replaces them. An earlier commit may lack one (one from
# before the worker), which a rollback to it must not ask for.
app_services() {
    local defined service
    defined=$(compose config --services)
    for service in backend worker nginx; do
        if grep -qx "$service" <<< "$defined"; then echo "$service"; fi
    done
}

# Whether every app service is running the checked-out commit's images
running() {
    local services containers images repository
    services=$(app_services)
    # shellcheck disable=SC2086 # one word per service
    containers=$(compose ps -q $services)
    [ "$(wc -w <<< "$containers")" -eq "$(wc -w <<< "$services")" ] || return 1
    # shellcheck disable=SC2086 # one word per container
    images=$(docker inspect --format '{{.Config.Image}}' $containers)
    for repository in $(repositories); do
        grep -qx "$repository:$tag" <<< "$images" || return 1
    done
}

# Through nginx, as a browser arrives, at the first name it serves, as
# Compose reads it from .env.prod (which may quote it)
healthy() {
    local host
    host=$(compose config nginx | sed -n 's/^ *NGINX_SERVER_NAME: //p' | tr -d "\"'" | cut -d ' ' -f 1)
    for _ in $(seq 10); do
        if curl -fsS -k --max-time 5 --resolve "$host:443:127.0.0.1" \
            "https://$host/api/health" > /dev/null; then
            return 0
        fi
        sleep 2
    done
    return 1
}

# Replaces the running containers with the checked-out commit's, the backend
# first, while the old nginx keeps serving the page (and the API's JSON 502
# or 504 until the new backend listens), then the worker, then nginx.
# --no-deps: migrate has already run, and would otherwise run again with the
# app stopped.
replace() { compose up -d --no-build --no-deps --wait --wait-timeout "$WAIT_SECONDS" "$1"; }
start() {
    local service
    for service in $(app_services); do
        replace "$service" || return 1
    done
    healthy
}

# Brings the bundled db and redis up to the checked-out commit's settings,
# naming only those whose profile is on: a service named on the command line
# starts whatever its profile, and an external one has none here
services() {
    local bundled
    bundled=$(compose config --services | grep -x -e db -e redis) || return 0
    # shellcheck disable=SC2086 # one word per service
    compose up -d --no-build --wait --wait-timeout "$WAIT_SECONDS" $bundled
}

[ $# -eq 1 ] || die "usage: $0 <commit> | --latest | --rollback"
[ -f .env.prod ] || die ".env.prod not found"
[ -z "$(git status --porcelain --untracked-files=no)" ] \
    || die "the clone has uncommitted changes; deploy from a clean clone"

# The lock holds its deploy's PID, so a run takes over the lock of one that
# was killed outright (kill -9, a reboot), which leaves it behind. ps, not
# kill -0, which fails on another user's live process. Two runs taking over
# the same dead lock at the same moment could both proceed; a timer's runs
# never overlap, so that needs a deploy by hand at that very moment.
if ! mkdir "$LOCK" 2> /dev/null; then
    holder=$(cat "$LOCK/pid" 2> /dev/null) || holder=
    # No PID yet (its deploy is starting, or died before writing one)
    # counts as running
    if ! [[ "$holder" =~ ^[0-9]+$ ]] || ps -p "$holder" > /dev/null 2>&1; then
        die "another deploy is running${holder:+ (pid $holder)}; if none is, remove $PWD/$LOCK"
    fi
    log "taking over the lock of deploy $holder, which is no longer running"
    rm -r "$LOCK"
    mkdir "$LOCK" 2> /dev/null || die "another deploy is running"
fi
trap 'rm -r "$LOCK"' EXIT
echo $$ > "$LOCK/pid"

current=$(state IMAGE_TAG)
previous=$(state PREVIOUS_IMAGE_TAG)
failed=$(state FAILED_IMAGE_TAG)

if [ "$1" = --rollback ]; then
    [ -n "$previous" ] || die "no previous deploy to roll back to"
    target=$previous
    # Rolled back from, so --latest leaves it alone
    failed=$current
else
    ref=$1
    if [ "$1" = --latest ]; then
        ref=origin/$BRANCH
    else
        # A local branch is wherever the clone left it: git fetch moves only
        # origin's
        ! git show-ref --verify --quiet "refs/heads/$1" \
            || die "$1 is a local branch, which is not kept up to date; pass a commit, e.g. origin/$BRANCH"
    fi
    git fetch --quiet origin "$BRANCH"
    target=$(git rev-parse --verify --quiet "$ref^{commit}") || die "unknown commit: $ref"
    git merge-base --is-ancestor "$target" "origin/$BRANCH" \
        || die "$target is not on origin/$BRANCH"
    # A timer would otherwise deploy it, and roll it back, on every run
    if [ "$1" = --latest ] && [ "$target" = "$failed" ]; then
        log "$target failed last; waiting for a newer commit (or deploy it by name)"
        exit 0
    fi
fi

tag=$target
# .env.deploy is written only once a deploy ends, so after one that was cut
# off, the running containers may be another commit's than it records, and
# the checkout, db and redis another's than the running containers: then the
# whole deploy runs, which puts them back and rebuilds nothing
if [ "$target" = "$current" ] && [ "$(git rev-parse HEAD)" = "$target" ] && running; then
    log "$target is already deployed"
    exit 0
fi
# Redeploying the recorded commit keeps the one before it for a rollback
before=$current
[ "$target" != "$current" ] || before=$previous

was=$(git rev-parse HEAD)
log "deploying $tag"

checkout "$tag"
# Back to the deployed commit on failure: after a deploy that was cut off,
# the checkout this run started on may be another
if ! build; then
    checkout "${current:-$was}"
    die "could not build the images for $tag; nothing changed"
fi

if ! services; then
    if [ -z "$current" ]; then
        checkout "$was"
        write_state "" "" "$tag"
        die "db or redis did not come up for $tag, and there is no earlier deploy to restore"
    fi
    checkout "$current"
    tag=$current
    services || die "db or redis did not come up for $target, nor again for $current: the app is down"
    write_state "$current" "$previous" "$target"
    die "db or redis did not come up for $target; they are back on $current's settings, and $current is serving"
fi

# --no-deps: db and redis are up already, and an external one is not here
if ! compose up --no-build --no-deps --exit-code-from migrate migrate; then
    checkout "${current:-$was}"
    write_state "$current" "$previous" "$tag"
    die "migrate failed for $tag; the running app is unchanged"
fi

if start; then
    # A failed commit deployed by name has stopped failing
    [ "$failed" != "$tag" ] || failed=
    write_state "$tag" "$before" "$failed"
    # The deploy succeeded whatever the cleanup does
    prune "$tag" "$before" || log "could not remove the older images"
    log "deployed $tag"
    exit 0
fi

log "$tag did not come up healthy"
if [ -z "$current" ]; then
    checkout "$was"
    write_state "" "" "$tag"
    die "no earlier deploy to roll back to; the stack is left as it is"
fi

log "rolling back to $current"
checkout "$current"
tag=$current
if build && start; then
    write_state "$current" "$previous" "$target"
    die "$target failed and was rolled back; $current is serving"
fi
write_state "$current" "$previous" "$target"
die "$target failed, and so did the rollback to $current: the app is down"
