from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.api.auth_deps import (
    CurrentUser,
    limit_register_rate,
    login_failure_key,
    login_failure_limiter,
    require_csrf_safe_request,
)
from app.api.deps import DbSession
from app.core.config import settings
from app.schemas.auth import LoginRequest, RegisterRequest, UserRead, normalize_username
from app.services.auth import (
    UsernameTakenError,
    authenticate,
    create_session,
    register_user,
    revoke_session,
)

router = APIRouter(prefix="/auth", tags=["auth"])

INVALID_CREDENTIALS = "Invalid username or password"


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limit_register_rate)],
)
def register(payload: RegisterRequest, db: DbSession) -> UserRead:
    """Create an account with the "user" role."""
    try:
        user = register_user(db, payload.username, payload.password)
    except UsernameTakenError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Username already exists") from exc
    return UserRead.model_validate(user)


@router.post("/login", response_model=UserRead)
def login(payload: LoginRequest, request: Request, response: Response, db: DbSession) -> UserRead:
    """Check the credentials and set the HttpOnly session cookie."""
    username = normalize_username(payload.username)
    failure_key = login_failure_key(request, username)
    limit = settings.auth_login_max_failures
    retry_after = login_failure_limiter.blocked_for(failure_key, limit)
    if retry_after is not None:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed logins. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )
    user = authenticate(db, username, payload.password)
    if user is None:
        login_failure_limiter.hit(failure_key, limit)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=INVALID_CREDENTIALS)
    login_failure_limiter.forget(failure_key)
    _set_session_cookie(response, create_session(db, user))
    return UserRead.model_validate(user)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf_safe_request)],
)
def logout(request: Request, db: DbSession) -> Response:
    """End the session (if any) and clear the cookie; always 204."""
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        revoke_session(db, token)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(
        settings.session_cookie_name,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="strict",
    )
    return response


@router.get("/me", response_model=UserRead)
def me(user: CurrentUser) -> UserRead:
    """The signed-in user."""
    return UserRead.model_validate(user)


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=settings.session_ttl_hours * 3600,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="strict",
    )
