from pydantic import BaseModel, ConfigDict, JsonValue

from app.auth.schemas import Password
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


class DataExportResponse(BaseModel):
    """GET /api/account/export: everything the app keeps on the signed-in
    user. data holds each feature's rows under its name (utils/exports.py)."""
    exported_at: UtcDatetime
    account: AccountExport
    data: dict[str, list[dict[str, JsonValue]]]


class AccountDeleteRequest(BaseModel):
    """POST /api/account/delete: the account's password, typed again"""
    password: Password

    model_config = ConfigDict(extra='forbid')
