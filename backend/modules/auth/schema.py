import re
import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator


# Minimum password length enforced at the schema layer. The DB layer
# happily accepts anything; we draw the line here so register/reset
# share one source of truth.
MIN_PASSWORD_LENGTH = 8
# bcrypt hashes only the first 72 bytes of input; anything longer is
# silently truncated. We reject upfront so users don't end up with a
# password where only the prefix actually matters.
MAX_PASSWORD_LENGTH = 72


def _validate_password(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("password must be a string")
    encoded = value.encode("utf-8")
    if len(encoded) < MIN_PASSWORD_LENGTH:
        raise ValueError(
            f"password must be at least {MIN_PASSWORD_LENGTH} characters"
        )
    if len(encoded) > MAX_PASSWORD_LENGTH:
        raise ValueError(
            f"password must be at most {MAX_PASSWORD_LENGTH} bytes "
            "(bcrypt silently truncates beyond this)"
        )
    # At least one letter + one digit/symbol — modest but effective
    # against the worst trivially-guessable passwords ("aaaaaaaa").
    if not re.search(r"[A-Za-z]", value) or not re.search(r"[^A-Za-z]", value):
        raise ValueError(
            "password must contain at least one letter and one digit or symbol"
        )
    return value


class RegisterInput(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str
    organization: str = Field(min_length=1, max_length=120)

    @field_validator("password")
    @classmethod
    def _password(cls, v: str) -> str:
        return _validate_password(v)


class LoginInput(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)


class RefreshInput(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=4096)


class LogoutInput(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=4096)


class ForgotPasswordInput(BaseModel):
    email: EmailStr


class ResetPasswordInput(BaseModel):
    token: str = Field(min_length=1, max_length=128)
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _new_password(cls, v: str) -> str:
        return _validate_password(v)


# ---------------------------------------------------------------------------
# Audit log response model (org-scoped, paginated)
# ---------------------------------------------------------------------------


class AuditEntry(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None
    action: str
    details: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditListResponse(BaseModel):
    entries: list[AuditEntry]
    total: int
    limit: int
    offset: int