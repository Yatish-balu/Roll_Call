"""Authentication package initialization."""

from app.auth.jwt import (
    AuthenticationError,
    decode_and_verify_token,
    create_access_token,
    get_jwt_secret,
)
from app.auth.roles import (
    Role,
    ROLE_HIERARCHY,
    normalize_role,
    role_satisfies,
)
from app.auth.dependencies import (
    get_current_user,
    require_roles,
    require_admin,
    require_faculty,
    require_viewer,
)
from app.auth.rate_limiter import (
    rate_limiter,
    rate_limit_chat,
    rate_limit_process_file,
    rate_limit_confirm,
    rate_limit_reports,
    reset_rate_limiter,
)

__all__ = [
    # JWT
    "AuthenticationError",
    "decode_and_verify_token",
    "create_access_token",
    "get_jwt_secret",
    # Roles
    "Role",
    "ROLE_HIERARCHY",
    "normalize_role",
    "role_satisfies",
    # Dependencies
    "get_current_user",
    "require_roles",
    "require_admin",
    "require_faculty",
    "require_viewer",
    # Rate Limiting
    "rate_limiter",
    "rate_limit_chat",
    "rate_limit_process_file",
    "rate_limit_confirm",
    "rate_limit_reports",
    "reset_rate_limiter",
]

