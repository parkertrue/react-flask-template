from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.auth.schemas import LINK_TOKEN_MAX_LENGTH, Email, Password
from app.utils.schemas import UtcDatetime


class AccountResponse(BaseModel):
    """GET /api/account: the signed-in user's own account"""
    email: str
    created_at: UtcDatetime

    model_config = ConfigDict(from_attributes=True)


class AccountExport(BaseModel):
    """The account's own row in an export, without its password hash"""
    email: str
    created_at: UtcDatetime
    terms_version: int
    terms_accepted_at: UtcDatetime

    model_config = ConfigDict(from_attributes=True)


class SessionExport(BaseModel):
    """A session in an export: what it says about the user, without the ids
    that name it to the app"""
    device: str
    signed_in_at: UtcDatetime
    last_active_at: UtcDatetime


class DataExportResponse(BaseModel):
    """GET /api/account/export: everything the app keeps on the signed-in
    user. sessions are its live sign-ins (Redis), most recently active first;
    data holds each feature's rows under its name (utils/exports.py)."""
    exported_at: UtcDatetime
    account: AccountExport
    sessions: list[SessionExport]
    data: dict[str, list[dict[str, JsonValue]]]


class AccountDeleteRequest(BaseModel):
    """POST /api/account/delete: the account's password, typed again"""
    password: Password

    model_config = ConfigDict(extra='forbid')


class EmailChangeRequest(BaseModel):
    """POST /api/account/email: the address to move the account to, and the
    account's password, typed again"""
    email: Email
    password: Password

    model_config = ConfigDict(extra='forbid')


class LinkTokenRequest(BaseModel):
    """An email change's emailed link, posted by its page: the one that moves
    the account to the new address, or the one that moves it back"""
    token: str = Field(max_length=LINK_TOKEN_MAX_LENGTH)

    model_config = ConfigDict(extra='forbid')


class EmailChangedResponse(BaseModel):
    """The account's address once a link has moved it"""
    email: str


class PasswordChangeRequest(BaseModel):
    """POST /api/account/password: the account's password, typed again, and
    the one to replace it"""
    current_password: Password
    new_password: Password

    model_config = ConfigDict(extra='forbid')


class SessionResponse(BaseModel):
    """One of the account's live sessions: a sign-in on some device"""
    id: str
    # A name for the device, from its User-Agent (app/utils/devices.py)
    device: str
    signed_in_at: UtcDatetime
    last_active_at: UtcDatetime
    # The session of the request's own token
    current: bool


class SessionsResponse(BaseModel):
    """GET /api/account/sessions: the live sessions, most recently active first"""
    sessions: list[SessionResponse]
