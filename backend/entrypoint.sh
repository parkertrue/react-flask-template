#!/bin/sh
set -e

python wait_for_services.py

# Migrations are not run here: the compose files' one-shot migrate service
# runs them as the migration user, whose credentials the app's container never holds.
exec "$@"
