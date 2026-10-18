from pydantic import BaseModel, ConfigDict

from app.auth.schemas import Password
from app.utils.schemas import UtcDatetime


class AccountResponse(BaseModel):
    """GET /api/account: the signed-in user's own account"""
    email: str
    created_at: UtcDatetime

    model_config = ConfigDict(from_attributes=True)


class AccountDeleteRequest(BaseModel):
    """POST /api/account/delete: the account's password, typed again"""
    password: Password

    model_config = ConfigDict(extra='forbid')
