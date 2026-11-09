import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

USERNAME_PATTERN = re.compile(r"^[a-z0-9_.-]{3,32}$")
PASSWORD_MIN_CHARS = 10
PASSWORD_MAX_CHARS = 128


def normalize_username(value: str) -> str:
    """Usernames are compared and stored lower-case, without surrounding spaces."""
    return value.strip().lower()


def validate_username(value: str) -> str:
    """The normalized username, or ValueError if it breaks the account rules."""
    username = normalize_username(value)
    if not USERNAME_PATTERN.fullmatch(username):
        raise ValueError("username must be 3-32 characters of a-z, 0-9, _ . -")
    return username


def validate_password(password: str, username: str) -> str:
    """The password unchanged, or ValueError if too short/long or equal to the username."""
    if not PASSWORD_MIN_CHARS <= len(password) <= PASSWORD_MAX_CHARS:
        raise ValueError(
            f"password must be {PASSWORD_MIN_CHARS}-{PASSWORD_MAX_CHARS} characters"
        )
    if normalize_username(password) == username:
        raise ValueError("password must not be the username")
    return password


class RegisterRequest(BaseModel):
    """Unknown fields such as "role" are rejected (422): nobody can pick their own role."""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(description="3-32 characters: a-z, 0-9, _ . - (stored lower-case).")
    password: str = Field(min_length=PASSWORD_MIN_CHARS, max_length=PASSWORD_MAX_CHARS)

    @field_validator("username")
    @classmethod
    def check_username(cls, value: str) -> str:
        return validate_username(value)

    @model_validator(mode="after")
    def check_password(self) -> "RegisterRequest":
        validate_password(self.password, self.username)
        return self


class LoginRequest(BaseModel):
    """Loose limits only, so a malformed username gets the same 401 as a wrong one."""

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=PASSWORD_MAX_CHARS)


class UserRead(BaseModel):
    """Public account fields; the password hash is never part of a response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: str
