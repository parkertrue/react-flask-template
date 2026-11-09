"""The worker service: runs the jobs the app queues (app/utils/jobs.py).

`python worker.py`, after entrypoint.sh's wait for MySQL and Redis, in the
worker container; run_dev.sh starts one beside the dev server. One process,
not Dramatiq's own command: its log lines would carry each job's arguments,
email addresses included, as plain text.
"""
from app import create_app
from app.utils.jobs import run_worker

app = create_app()

if __name__ == '__main__':
    # Checked at start, not on the first email: a missing setting stops the
    # worker at once, where a deploy notices it. APP_URL starts every link.
    for setting, variable in (('EMAIL_SERVER', 'EMAIL_URL'), ('EMAIL_FROM', 'EMAIL_FROM'),
                              ('APP_URL', 'APP_URL')):
        if app.config[setting] is None:
            raise SystemExit(f'{variable} must be set for the worker to send email')
    run_worker(app)
