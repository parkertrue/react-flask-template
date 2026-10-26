#!/bin/bash
set -e

ENV_FILE="../.env.dev"
if [ ! -f "$ENV_FILE" ]; then
    echo "Error: $ENV_FILE not found!"
    exit 1
fi

# Load environment variables from .env.dev. A FLASK_DEBUG already set in the
# shell wins over the file: FLASK_DEBUG=0 ./run_dev.sh
echo "Loading environment variables from .env.dev"
SHELL_FLASK_DEBUG="${FLASK_DEBUG-}"
set -a
source "$ENV_FILE"
set +a
if [ -n "$SHELL_FLASK_DEBUG" ]; then
    FLASK_DEBUG="$SHELL_FLASK_DEBUG"
fi

# Activate virtual environment (cross-platform)
if [ -z "${VIRTUAL_ENV}" ]; then
    echo "Activating virtual environment..."
    if [ -f ".venv/Scripts/activate" ]; then
        source .venv/Scripts/activate  # Windows (Git Bash)
    elif [ -f ".venv/bin/activate" ]; then
        source .venv/bin/activate      # Linux/macOS
    else
        echo "Error: Virtual environment not found. Please run:"
        echo "  python -m venv .venv"
        exit 1
    fi
fi

python wait_for_services.py

echo "Running database migrations..."
flask db upgrade

# As in production, the app itself runs as the user that cannot change the
# schema: without the migration URL, it connects with DATABASE_URL
unset MIGRATION_DATABASE_URL MIGRATION_DATABASE_PASSWORD

echo "Starting Flask app..."
exec python wsgi.py
