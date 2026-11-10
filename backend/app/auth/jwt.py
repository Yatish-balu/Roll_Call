"""JWT verification and token decoding utilities.

Supports:
1. HMAC shared secret verification (HS256) for Supabase Auth JWTs.
2. Configurable issuer, audience, and expiration verification.
3. Prepared interface for future Supabase JWKS (RS256 / ES256) public key verification.
4. Strict cryptographic signature enforcement (no unverified decoding in production).
"""

from __future__ import annotations

import datetime
import logging
import os
from typing import Any, Dict, List, Optional

import jwt
from jwt.exceptions import (
    ExpiredSignatureError,
    ImmatureSignatureError,
    InvalidAudienceError,
    InvalidIssuerError,
    InvalidSignatureError,
    InvalidTokenError,
)

from app.auth.roles import normalize_role
from app.schemas.auth import AuthenticatedUser, Role

logger = logging.getLogger("rollcall.auth.jwt")


class AuthenticationError(Exception):
    """Custom exception raised when JWT authentication fails."""
    def __init__(self, message: str, status_code: int = 401):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def get_jwt_secret() -> str:
    """
    Retrieve configured JWT secret for signature verification.
    Reads JWT_SECRET_KEY or SUPABASE_JWT_SECRET from environment.
    Enforces strict security checks in production.
    """
    secret = os.getenv("JWT_SECRET_KEY") or os.getenv("SUPABASE_JWT_SECRET")
    env = os.getenv("APP_ENV", "development").lower()
    is_production = env == "production"

    if not secret:
        if not is_production:
            return "rollcall-dev-secret-key-change-in-production-32bytes-min"
        raise RuntimeError("Production security violation: JWT secret key is not configured. Set JWT_SECRET_KEY or SUPABASE_JWT_SECRET.")

    clean_secret = secret.strip()
    if is_production:
        if clean_secret == "rollcall-dev-secret-key-change-in-production-32bytes-min":
            raise RuntimeError("Production security violation: Insecure default development secret key cannot be used in production.")
        if len(clean_secret) < 32:
            raise RuntimeError("Production security violation: JWT secret key must be at least 32 characters long in production.")

    return clean_secret


def get_jwt_public_key() -> Optional[str]:
    """
    Retrieve configured public key for asymmetric JWT verification (RS256 / ES256).
    Reads JWT_PUBLIC_KEY or SUPABASE_PUBLIC_KEY from environment.
    """
    pk = os.getenv("JWT_PUBLIC_KEY") or os.getenv("SUPABASE_PUBLIC_KEY")
    return pk.strip() if pk and pk.strip() else None


def get_jwt_algorithms() -> List[str]:
    """
    Retrieve allowed JWT signing algorithms.
    Supports comma-separated list via JWT_ALGORITHMS or single JWT_ALGORITHM.
    Strictly forbids 'none' algorithm.
    """
    raw = os.getenv("JWT_ALGORITHMS") or os.getenv("JWT_ALGORITHM", "HS256")
    candidates = [alg.strip() for alg in raw.split(",") if alg.strip()]

    # Strictly reject 'none' algorithm (case-insensitive)
    allowed = [alg for alg in candidates if alg.lower() != "none"]
    if not allowed:
        raise RuntimeError("Invalid JWT algorithm configuration: 'none' is strictly forbidden.")
    return allowed


def get_jwt_issuer() -> Optional[str]:
    """Retrieve expected token issuer (e.g. Supabase Auth project URL)."""
    iss = os.getenv("JWT_ISSUER")
    return iss.strip() if iss and iss.strip() else None


def get_jwt_audience() -> Optional[str]:
    """Retrieve expected token audience (e.g. 'authenticated')."""
    aud = os.getenv("JWT_AUDIENCE")
    return aud.strip() if aud and aud.strip() else None


def decode_and_verify_token(
    token: str,
    secret: Optional[str] = None,
    public_key: Optional[str] = None,
) -> AuthenticatedUser:
    """
    Cryptographically verify a JWT and extract authenticated user identity and role.
    Never trusts client-supplied user parameters in request bodies.
    Supports symmetric (HS256) and asymmetric (RS256/ES256) algorithms.
    Strictly neutralizes privilege escalation via user_metadata.
    """
    if not token or not isinstance(token, str):
        raise AuthenticationError("Authentication token is missing or empty.")

    clean_token = token.strip()

    # 1. Inspect unverified header for algorithm and kid verification
    try:
        header = jwt.get_unverified_header(clean_token)
    except Exception as exc:
        raise AuthenticationError(f"Invalid token: malformed token header ({exc})")

    token_alg = str(header.get("alg", "")).strip()
    if token_alg.lower() == "none":
        raise AuthenticationError("Algorithm 'none' is strictly forbidden.")

    allowed_algorithms = get_jwt_algorithms()
    if not any(token_alg.upper() == a.upper() for a in allowed_algorithms):
        raise AuthenticationError(
            f"Token algorithm '{token_alg}' is not in allowed algorithms: {allowed_algorithms}."
        )

    # 2. Select appropriate verification key (asymmetric vs symmetric)
    if token_alg.upper().startswith(("RS", "ES", "PS")):
        signing_key = public_key or get_jwt_public_key()
        if not signing_key:
            # Fall back to secret parameter if supplied specifically in test scenarios
            signing_key = secret or get_jwt_secret()
    else:
        signing_key = secret or get_jwt_secret()

    issuer = get_jwt_issuer()
    audience = get_jwt_audience()

    options = {
        "verify_signature": True,
        "verify_exp": True,
        "verify_iat": True,
        "verify_iss": bool(issuer),
        "verify_aud": bool(audience),
        "require": ["exp", "sub"],
    }

    try:
        claims = jwt.decode(
            clean_token,
            signing_key,
            algorithms=allowed_algorithms,
            issuer=issuer,
            audience=audience,
            options=options,
        )
    except ExpiredSignatureError:
        raise AuthenticationError("Token has expired.")
    except ImmatureSignatureError:
        raise AuthenticationError("Token not yet valid.")
    except InvalidSignatureError:
        raise AuthenticationError("Token signature verification failed.")
    except InvalidIssuerError:
        raise AuthenticationError("Token issuer is invalid.")
    except InvalidAudienceError:
        raise AuthenticationError("Token audience is invalid.")
    except InvalidTokenError as exc:
        raise AuthenticationError(f"Invalid token: {exc}")
    except Exception as exc:
        logger.error("Unexpected error during JWT verification: %s", exc)
        raise AuthenticationError("Could not validate authentication token.")

    # 3. Subject extraction (user ID)
    sub = str(claims.get("sub", "")).strip()
    if not sub:
        raise AuthenticationError("Token subject (sub) is missing or empty.")

    # 4. Email extraction
    email = claims.get("email")
    if email and isinstance(email, str):
        email = email.strip()

    # 5. Role extraction with strict privilege escalation defense
    # Server-controlled claims:
    # a) app_metadata.role (Supabase custom claims managed strictly by service role)
    # b) claims["role"] (top-level custom role claim if not default 'authenticated' or 'anon')
    # c) user_metadata.role is user-editable and MUST NEVER grant ADMIN or FACULTY privileges!
    app_meta = claims.get("app_metadata", {})
    user_meta = claims.get("user_metadata", {})
    raw_role = None

    if isinstance(app_meta, dict) and app_meta.get("role"):
        raw_role = app_meta.get("role")
    elif claims.get("role") and str(claims.get("role")).lower() not in ("authenticated", "anon"):
        raw_role = claims.get("role")
    elif isinstance(user_meta, dict) and user_meta.get("role"):
        untrusted_role = normalize_role(user_meta.get("role"))
        if untrusted_role in (Role.ADMIN, Role.FACULTY):
            logger.warning(
                "Security Alert: Untrusted user_metadata attempted privilege escalation to '%s' for subject '%s'. Enforcing least privilege (VIEWER).",
                untrusted_role.value,
                sub,
            )
        raw_role = Role.VIEWER.value
    else:
        raw_role = Role.VIEWER.value

    role = normalize_role(raw_role)

    return AuthenticatedUser(
        user_id=sub,
        email=email,
        role=role,
        claims=claims,
    )


def create_access_token(
    data: Dict[str, Any],
    expires_delta: Optional[datetime.timedelta] = None,
    secret: Optional[str] = None,
    algorithm: Optional[str] = None,
) -> str:
    """
    Helper to generate signed JWT tokens for testing and development.
    """
    to_encode = data.copy()
    now = datetime.datetime.now(datetime.timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + datetime.timedelta(minutes=60)

    to_encode.setdefault("exp", int(expire.timestamp()))
    to_encode.setdefault("iat", int(now.timestamp()))
    if "sub" not in to_encode:
        to_encode["sub"] = "default-user-uuid"

    signing_secret = secret or get_jwt_secret()
    alg = algorithm or get_jwt_algorithms()[0]
    return jwt.encode(to_encode, signing_secret, algorithm=alg)

