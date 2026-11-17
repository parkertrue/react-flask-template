"""The emails auth sends, and the jobs that send them (routes.py declares
them on the blueprint).

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

# The purpose a password reset link's token is minted for
PASSWORD_RESET_LINK = 'password-reset'
# Short: the link sets the account's password, so a leaked one must stop
# working soon, though mail can arrive late. frontend/src/auth/authService.ts
# mirrors it.
PASSWORD_RESET_LINK_HOURS = 1
PASSWORD_RESET_LINK_LIFETIME = timedelta(hours=PASSWORD_RESET_LINK_HOURS)


def _hours(count: int) -> str:
    return f"{count} hour{'' if count == 1 else 's'}"


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
        f'{_hours(REGISTRATION_LINK_HOURS)}:',
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


def password_reset_message(link: str) -> tuple[str, str]:
    app_name = current_app.config['APP_NAME']
    return f'Reset your {app_name} password', _body(
        f'Someone, hopefully you, asked to reset the password of your {app_name} account.',
        'To choose a new password, open this link within '
        f'{_hours(PASSWORD_RESET_LINK_HOURS)}:',
        link,
        "If it wasn't you, ignore this email: your password has not changed.")


def password_changed_message(link: str) -> tuple[str, str]:
    app_name = current_app.config['APP_NAME']
    return f'Your {app_name} password was changed', _body(
        f'The password of your {app_name} account was just reset with a link sent to this '
        'address, and every device signed in to the account was logged out.',
        "If it wasn't you, someone else can read your email: secure your email account, "
        'then reset your password here:',
        link)


def send_password_reset_email(email: str) -> None:
    """Send email a link to reset its account's password; nothing when the
    address has no account. The reset form answers both alike, so only the
    inbox's owner learns which it was.

    The link carries the account's password_state, so it works only until
    the password changes: once, as a reset changes it.
    """
    if not is_normalized_email(email):
        raise PermanentJobFailure('Not an address the reset form accepts')
    user = db.session.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None:
        return
    token = make_link_token(PASSWORD_RESET_LINK, email, user.password_state)
    subject, body = password_reset_message(app_link('/password-reset/complete', token=token))
    send_email(email, subject, body)


def send_password_changed_email(email: str) -> None:
    """Tell email its account's password was just reset (ASVS 6.3.7), so an
    owner who did not ask for it learns at once"""
    if not is_normalized_email(email):
        raise PermanentJobFailure('Not an address an account can have')
    subject, body = password_changed_message(app_link('/password-reset'))
    send_email(email, subject, body)
