"""The emails auth sends, and the job that sends sign-up's (routes.py
declares it on the blueprint).

Plain text (app/utils/mail.py). Each says what to do if the reader did not
ask for it, since anyone can type any address into the sign-up form.
"""
from datetime import timedelta

from sqlalchemy import select

from app import db
from app.auth.models import User
from app.utils.links import app_link, make_link_token
from app.utils.mail import send_email

# The purpose a sign-up link's token is minted for (app/utils/links.py)
REGISTRATION_LINK = 'registration'
# How long a sign-up link works: mail can arrive late, and people open it
# later; it can only create an account for an inbox its holder reads
REGISTRATION_LINK_LIFETIME = timedelta(hours=24)


def registration_email(link: str) -> tuple[str, str]:
    return 'Finish signing up', (
        'Someone, hopefully you, asked to sign up with this email address.\n'
        '\n'
        'To choose a password and finish, open this link within 24 hours:\n'
        '\n'
        f'{link}\n'
        '\n'
        "If it wasn't you, ignore this email: no account is created until\n"
        'the link is used.\n')


def already_registered_email(link: str) -> tuple[str, str]:
    return 'You already have an account', (
        'Someone, hopefully you, tried to sign up with this email address,\n'
        'but it already has an account. Log in here:\n'
        '\n'
        f'{link}\n'
        '\n'
        "If it wasn't you, ignore this email: nothing has changed.\n")


def send_registration_email(email: str) -> None:
    """Send email the link to finish signing up, or, if it has an account,
    a note saying so: the sign-up form answers both alike, so only the
    inbox's owner learns which it was"""
    if db.session.execute(select(User.id).where(User.email == email)).first():
        subject, body = already_registered_email(app_link('/login'))
    else:
        token = make_link_token(REGISTRATION_LINK, email)
        subject, body = registration_email(
            app_link('/register/complete', email=email, token=token))
    send_email(email, subject, body)
