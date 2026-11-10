"""Request DTOs for the users module.

Every free-text field is sanitised here, at the trust boundary, so services
and repositories only ever receive clean values.
"""

from pydantic import BaseModel, EmailStr, Field, field_validator

from src.common.constants.enums import UserRole
from src.utils.sanitize import clean_text

USERNAME_PATTERN = r"^[a-zA-Z0-9_.-]+$"


class UserRegisterDTO(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=64, pattern=USERNAME_PATTERN)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("username")
    @classmethod
    def _clean_username(cls, value: str) -> str:
        cleaned = clean_text(value, max_length=64)
        if not cleaned:
            raise ValueError("username must not be blank")
        return cleaned

    @field_validator("password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        # Never sanitise a password: it must be hashed byte-for-byte.
        if value.strip() != value:
            raise ValueError("password must not start or end with whitespace")
        return value


class UserLoginDTO(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserUpdateRoleDTO(BaseModel):
    role: UserRole


class PasswordChangeDTO(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        if value.strip() != value:
            raise ValueError("password must not start or end with whitespace")
        return value
