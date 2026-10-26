#!/bin/bash
# Regenerate requirements.txt and requirements-dev.txt from the .in files.
# Pass --upgrade to move every package to its newest release.
#
# Runs pip-compile inside the production base image, so the locks resolve for
# Linux and Python 3.14 whatever machine this is run on.
set -e
cd "$(dirname "$0")"

MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd):/src" -w /src python:3.14-slim sh -c "
  pip install -q --root-user-action=ignore 'pip-tools>=7.6.2' &&
  pip-compile -q --strip-extras $* -o requirements.txt requirements.in &&
  pip-compile -q --strip-extras $* -o requirements-dev.txt requirements-dev.in"

echo "Locks updated; reinstall with: pip install -r requirements-dev.txt"
