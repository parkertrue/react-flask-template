"""The emails auth sends, and the job that sends sign-up's (routes.py
declares it on the blueprint).

Plain text (app/utils/mail.py), one line per paragraph, so the reader's
mail app wraps it to the screen. Each names the app, says what to do if the
reader did not ask for it, since anyone can type any address into the
sign-up form, and ends with the privacy notice, which says who sent it.
"""
from datetime import timedelta

from flask import current_app
from sqlalchemy import select

from app import db
from app.auth.models import User
from app.auth.schemas import is_normalized_email
from app.utils.jobs import PermanentJobFailure
from app.utils.links import app_link, make_link_token
from app.utils.mail import send_email

# The purpose a sign-up link's token is minted for (app/utils/links.py)
REGISTRATION_LINK = 'registration'
# How long a sign-up link works: mail can arrive late, and people open it
# later; it can only create an account for an inbox its holder reads.
# frontend/src/auth/authService.ts mirrors it, for the page that says so.
REGISTRATION_LINK_HOURS = 24
REGISTRATION_LINK_LIFETIME = timedelta(hours=REGISTRATION_LINK_HOURS)


def _body(*paragraphs: str) -> str:
    """A plain-text body: one line per paragraph, a blank line between them,
    then where the privacy notice is"""
    privacy = (f"Who runs {current_app.config['APP_NAME']}, and what it keeps: "
               f"{app_link('/privacy')}")
    return '\n\n'.join([*paragraphs, privacy]) + '\n'


def registration_message(link: str) -> tuple[str, str]:
    app_name = current_app.config['APP_NAME']
    return f'Finish signing up for {app_name}', _body(
        f'Someone, hopefully you, asked to sign up for {app_name} with this email address.',
        'To choose a password and finish, open this link within '
        f'{REGISTRATION_LINK_HOURS} hours:',
        link,
        "If it wasn't you, ignore this email: no account is created until the link is used.")


def already_registered_message(link: str) -> tuple[str, str]:
    app_name = current_app.config['APP_NAME']
    return f'You already have a {app_name} account', _body(
        f'Someone, hopefully you, tried to sign up for {app_name} with this email address, '
        'but it already has an account. Log in here:',
        link,
        "If it wasn't you, ignore this email: nothing has changed.")


def send_registration_email(email: str) -> None:
    """Send email the link to finish signing up, or, if it has an account,
    a note saying so: the sign-up form answers both alike, so only the
    inbox's owner learns which it was.

    Only an address the sign-up form would have queued: whoever can write to
    the queue must not be able to mail a list of addresses, or a display
    name's, through the app.
    """
    if not is_normalized_email(email):
        raise PermanentJobFailure('Not an address the sign-up form accepts')
    if db.session.execute(select(User.id).where(User.email == email)).first():
        subject, body = already_registered_message(app_link('/login'))
    else:
        token = make_link_token(REGISTRATION_LINK, email)
        subject, body = registration_message(
            app_link('/signup/complete', token=token))
    send_email(email, subject, body)
