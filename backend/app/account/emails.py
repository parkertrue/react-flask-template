"""The emails an email change sends, the jobs that send them (routes.py
declares them on the blueprint), and the states its links carry.

A change takes two links. The one to the new address moves the account
there; its state names the account and hashes its address and password as
they were when the change was asked for (the request passes it to the job),
so it stops working once either changes (another change, a reset, or the
undo below, which also replaces the password), and a job that runs after
such a change, late, retried or replayed, sends nothing. Then the old
address is told, with a link that moves the account back: its state names
the account alone, so it still works after whoever made the change resets
the password or changes the address again.
"""
import hmac
from datetime import timedelta

from flask import current_app
from sqlalchemy import select

from app import db
from app.auth.emails import email_body, hours
from app.auth.models import User, keyed_hash
from app.auth.schemas import is_normalized_email
from app.utils.jobs import PermanentJobFailure
from app.utils.links import app_link, make_link_token
from app.utils.mail import send_email

# The purpose of the link to the new address (app/utils/links.py)
EMAIL_CHANGE_LINK = 'email-change'
# As sign-up's: the link can only move the account to an inbox its holder
# reads, and asking for it took the password. frontend/src/auth/authService.ts
# mirrors it.
EMAIL_CHANGE_LINK_HOURS = 24
EMAIL_CHANGE_LINK_LIFETIME = timedelta(hours=EMAIL_CHANGE_LINK_HOURS)

# The purpose of the link to the old address, which moves the account back
EMAIL_UNDO_LINK = 'email-undo'
# Long enough for an owner who reads mail now and then to notice
EMAIL_UNDO_LINK_DAYS = 7
EMAIL_UNDO_LINK_LIFETIME = timedelta(days=EMAIL_UNDO_LINK_DAYS)


def change_state(user: User) -> str:
    """The account, and what must not change before the link is used: its
    address and its password. Keyed, since the link's token can be read."""
    return f'{user.id}:{keyed_hash(f"{user.email}\n{user.password_state}")}'


def undo_state(user: User) -> str:
    """The account alone, by id and creation time, as tokens name it (a
    restored backup hands ids out again)"""
    return f'{user.id}:{user.created_timestamp}'


def state_account(state: str) -> User | None:
    """The account a link's state names, if it names one"""
    user_id, _, _rest = state.partition(':')
    return db.session.get(User, int(user_id)) if user_id.isdigit() else None


def masked(email: str) -> str:
    """An address shown to its account's old one: enough to recognise, not
    the whole of someone else's address (n***@example.com)"""
    local, _, domain = email.partition('@')
    return f'{local[:1]}***@{domain}'


def email_change_message(link: str) -> tuple[str, str]:
    app_name = current_app.config['APP_NAME']
    return f'Confirm your new {app_name} email', email_body(
        f'Someone, hopefully you, asked to move a {app_name} account to this email address.',
        f'To confirm, open this link within {hours(EMAIL_CHANGE_LINK_HOURS)}:',
        link,
        "If it wasn't you, ignore this email: nothing changes until the link is used.")


def address_taken_message(link: str) -> tuple[str, str]:
    app_name = current_app.config['APP_NAME']
    return f'You already have a {app_name} account', email_body(
        f'Someone, hopefully you, tried to move a {app_name} account to this email address, '
        'but it already has an account of its own. Log in here:',
        link,
        "If it wasn't you, ignore this email: nothing has changed.")


def email_changed_message(new_email: str, link: str) -> tuple[str, str]:
    app_name = current_app.config['APP_NAME']
    return f'Your {app_name} email was changed', email_body(
        f'The email address of your {app_name} account was just changed to {masked(new_email)}.',
        f"If it wasn't you, open this link within {EMAIL_UNDO_LINK_DAYS} days to move the "
        'account back to this address, log out every device and turn off the password, '
        'then reset your password:',
        link)


def send_email_change_email(user_id: int, new_email: str, state: str) -> None:
    """Send new_email the link that moves the account there, or, if it has
    an account of its own, a note saying so: the form answers both alike,
    so only the inbox's owner learns which it was. state is the account's
    change_state when the change was asked for: nothing is sent once the
    password or the address has changed since, nor for an account deleted
    since."""
    if not is_normalized_email(new_email):
        raise PermanentJobFailure('Not an address the form accepts')
    user = db.session.get(User, user_id)
    if user is None or not hmac.compare_digest(change_state(user), state):
        return
    if user.email.lower() == new_email.lower():
        return
    if db.session.execute(select(User.id).where(User.email == new_email)).first():
        subject, body = address_taken_message(app_link('/login'))
    else:
        token = make_link_token(EMAIL_CHANGE_LINK, new_email, state)
        subject, body = email_change_message(app_link('/account/email/complete', token=token))
    send_email(new_email, subject, body)


def send_email_changed_email(user_id: int, old_email: str) -> None:
    """Tell old_email its account moved, with the link that moves it back
    (ASVS 6.3.7). Nothing for an account deleted since."""
    if not is_normalized_email(old_email):
        raise PermanentJobFailure('Not an address an account can have')
    user = db.session.get(User, user_id)
    if user is None:
        return
    token = make_link_token(EMAIL_UNDO_LINK, old_email, undo_state(user))
    subject, body = email_changed_message(user.email, app_link('/account/email/undo', token=token))
    send_email(old_email, subject, body)
