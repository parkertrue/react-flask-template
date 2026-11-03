#!/bin/bash
# Deploys one commit of main, or rolls back to the one before
# (docs/deployment.md, Redeploying):
#
#   ./deploy.sh <commit>     build that commit's images and deploy them
#   ./deploy.sh --rollback   deploy the previously deployed commit again
#
# Run it as a user who can run Docker, in a clone that user owns, beside
# .env.prod. The images are built here, from the commit, and tagged with it
# (<project>-backend:<commit>, <project>-nginx:<commit>); the deployed and
# previous commits' images are kept, so a rollback builds nothing.
#
# The checkout moves to the commit, so the compose file and db/init match its
# images; migrate runs before anything is replaced, so a failed migration
# leaves the running app serving; and if the new app does not come up
# healthy, the previous commit is brought back. Migrations are never undone:
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
            compose build --provenance=false backend nginx
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

# Through nginx, as a browser arrives, at the first name it serves
healthy() {
    local host
    host=$(sed -n 's/^SERVER_NAME=//p' .env.prod | tail -n 1 | cut -d ' ' -f 1)
    for _ in $(seq 10); do
        if curl -fsS -k --max-time 5 --resolve "$host:443:127.0.0.1" \
            "https://$host/api/health" > /dev/null; then
            return 0
        fi
        sleep 2
    done
    return 1
}

# Replaces the running containers with the checked-out commit's
start() { compose up -d --no-build --wait --wait-timeout "$WAIT_SECONDS" && healthy; }

[ $# -eq 1 ] || die "usage: $0 <commit> | --rollback"
[ -f .env.prod ] || die ".env.prod not found"
[ -z "$(git status --porcelain --untracked-files=no)" ] \
    || die "the clone has uncommitted changes; deploy from a clean clone"

mkdir "$LOCK" 2> /dev/null || die "another deploy is running (or one was killed: remove $LOCK)"
trap 'rmdir "$LOCK"' EXIT

current=$(state IMAGE_TAG)
previous=$(state PREVIOUS_IMAGE_TAG)
failed=$(state FAILED_IMAGE_TAG)

if [ "$1" = --rollback ]; then
    [ -n "$previous" ] || die "no previous deploy to roll back to"
    target=$previous
else
    git fetch --quiet origin "$BRANCH"
    target=$(git rev-parse --verify --quiet "$1^{commit}") || die "unknown commit: $1"
    git merge-base --is-ancestor "$target" "origin/$BRANCH" \
        || die "$target is not on origin/$BRANCH"
fi

if [ "$target" = "$current" ]; then
    log "$target is already deployed"
    exit 0
fi

was=$(git rev-parse HEAD)
tag=$target
log "deploying $tag"

checkout "$tag"
if ! build; then
    checkout "$was"
    die "could not build the images for $tag; nothing changed"
fi

if ! compose up --no-build --exit-code-from migrate migrate; then
    checkout "$was"
    write_state "$current" "$previous" "$tag"
    die "migrate failed for $tag; the running app is unchanged"
fi

if start; then
    write_state "$tag" "$current" "$failed"
    # The deploy succeeded whatever the cleanup does
    prune "$tag" "$current" || log "could not remove the older images"
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
