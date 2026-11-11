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
import uuid
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


def _now() -> int:
    """Return current time in seconds since epoch (UTC)."""
    return int(datetime.datetime.now(datetime.timezone.utc).timestamp())


def _base32_encode(data: bytes) -> str:
    """Standard base32 encoding (RFC 4648) for TOTP secrets."""
    import base64
    return base64.b32encode(data).decode("utf-8")


def _base32_decode(secret: str) -> bytes:
    """Decode a base32-encoded TOTP secret."""
    import base64
    return base64.b32decode(secret.upper().strip())


#: The development fallback secret. It must never be accepted in production.
DEV_FALLBACK_SECRET = "rollcall-dev-secret-key-change-in-production-32bytes-min"


def validate_jwt_secret_configuration(
    secret: Optional[str], env: Optional[str] = None
) -> str:
    """Validate and clean a JWT secret string.

    * an unset / empty secret is rejected ("missing or empty"),
    * a secret shorter than 32 characters is rejected ("too short"),
    * in production the insecure development fallback is rejected,
    * a valid secret is returned stripped.

    ``env`` is the deployment mode ("production" / "development"); when it is
    not supplied the current ``APP_ENV`` is used.
    """
    mode = (env or os.getenv("APP_ENV", "development")).strip().lower()
    clean_secret = (secret or "").strip()
    if not clean_secret:
        raise ValueError("JWT secret key is missing or empty.")
    if len(clean_secret) < 32:
        raise ValueError("JWT secret key is too short (minimum 32 characters).")
    if mode == "production" and clean_secret == DEV_FALLBACK_SECRET:
        raise ValueError(
            "JWT secret key uses the insecure development fallback and cannot be used in production."
        )
    return clean_secret


#: Internal alias kept for the modules that use the private name.
_validate_jwt_secret = validate_jwt_secret_configuration



def _totp(secret: bytes, time_step: int = 30) -> str:
    """Generate a TOTP code (RFC 6238) from a base32-secret."""
    import hmac, hashlib
    from struct import unpack
    counter = _now() // time_step
    hmac_val = hmac.new(secret, counter.to_bytes(8, "big"), hashlib.sha1).digest()
    # Dynamic truncation (RFC 4226, bytes 4-8 modulo 2^31)
    offset = hmac_val[19] & 0x0f
    code_int = unpack(">I", hmac_val[offset : offset + 4])[0] & 0x7fffffff
    return str(code_int % 1000000).zfill(6)

def get_local_jwt_secret() -> str:
    """
    Retrieve configured secret key specifically for signing local RollCall AI JWT tokens.
    Reads JWT_SECRET from environment (or falls back to JWT_SECRET_KEY).
    In production the development fallback secret is never accepted.
    """
    env = os.getenv("APP_ENV", "development").strip().lower()
    secret = os.getenv("JWT_SECRET") or os.getenv("JWT_SECRET_KEY")
    if secret:
        if env == "production" and secret.strip() == DEV_FALLBACK_SECRET:
            raise RuntimeError(
                "Production security violation: Insecure default development secret key "
                "cannot be used in production."
            )
        try:
            return validate_jwt_secret_configuration(secret, env)
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc

    if env == "production":
        raise RuntimeError("Production security violation: JWT_SECRET must be configured and >= 32 characters.")

    return DEV_FALLBACK_SECRET


def get_jwt_secret() -> str:
    """
    Retrieve configured JWT secret for signature verification.
    Reads JWT_SECRET, JWT_SECRET_KEY, or SUPABASE_JWT_SECRET from environment.
    Enforces strict security checks in production.
    """
    secret = os.getenv("JWT_SECRET") or os.getenv("JWT_SECRET_KEY") or os.getenv("SUPABASE_JWT_SECRET")
    env = os.getenv("APP_ENV", "development").strip().lower()
    is_production = env == "production"

    if not secret:
        if not is_production:
            return DEV_FALLBACK_SECRET
        raise RuntimeError("Production security violation: JWT secret key is not configured. Set JWT_SECRET or SUPABASE_JWT_SECRET.")

    clean_secret = secret.strip()
    if is_production:
        if clean_secret == DEV_FALLBACK_SECRET:
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

    # 2. Select appropriate verification keys (asymmetric vs symmetric with Supabase compatibility)
    if token_alg.upper().startswith(("RS", "ES", "PS")):
        signing_key = public_key or get_jwt_public_key() or secret or get_jwt_secret()
        candidate_keys = [signing_key]
    else:
        if secret:
            candidate_keys = [secret]
        else:
            # When no explicit secret is passed, select from available candidates.
            # In production, the secret must be configured; in development use the fallback.
            env = os.getenv("APP_ENV", "development").lower()
            is_prod = env == "production"
            if is_prod:
                # Production: secret must already be set via JWT_SECRET or JWT_SECRET_KEY;
                # never fall back to the development secret.
                configured = os.getenv("JWT_SECRET") or os.getenv("JWT_SECRET_KEY")
                if not configured or len(configured.strip()) == 0:
                    raise RuntimeError(
                        "Production security violation: JWT secret is not configured. "
                        "Set JWT_SECRET or JWT_SECRET_KEY before running."
                    )
                candidate_keys = [configured.strip()]
            else:
                # Development: use the configured secret or the safe dev fallback.
                local_secret = get_local_jwt_secret()
                supabase_secret = os.getenv("SUPABASE_JWT_SECRET")
                legacy_secret = os.getenv("JWT_SECRET_KEY")
                candidate_keys = [local_secret]
                for extra in (supabase_secret, legacy_secret):
                    if extra and extra.strip() and extra.strip() not in candidate_keys:
                        candidate_keys.append(extra.strip())

    issuer = get_jwt_issuer()
    audience = get_jwt_audience()

    # When running in production, issuer and audience must be configured;
    # otherwise verify_iss/verify_aud will be False and silently skip checks.
    env = os.getenv("APP_ENV", "development").lower()
    if env == "production":
        if not issuer:
            raise RuntimeError(
                "Production security violation: JWT issuer is not configured. "
                "Set JWT_ISSUER before running."
            )
        if not audience:
            raise RuntimeError(
                "Production security violation: JWT audience is not configured. "
                "Set JWT_AUDIENCE before running."
            )

    options = {
        "verify_signature": True,
        "verify_exp": True,
        "verify_iat": True,
        "verify_iss": bool(issuer),
        "verify_aud": bool(audience),
        "require": ["exp", "sub"],
    }

    claims = None
    last_sig_error = None

    for key in candidate_keys:
        try:
            claims = jwt.decode(
                clean_token,
                key,
                algorithms=allowed_algorithms,
                issuer=issuer,
                audience=audience,
                options=options,
            )
            break
        except ExpiredSignatureError:
            raise AuthenticationError("Token has expired.")
        except ImmatureSignatureError:
            raise AuthenticationError("Token not yet valid.")
        except InvalidSignatureError as sig_exc:
            last_sig_error = sig_exc
            continue
        except InvalidIssuerError:
            raise AuthenticationError("Token issuer is invalid.")
        except InvalidAudienceError:
            raise AuthenticationError("Token audience is invalid.")
        except InvalidTokenError as exc:
            raise AuthenticationError(f"Invalid token: {exc}")
        except Exception as exc:
            logger.error("Unexpected error during JWT verification: %s", exc)
            raise AuthenticationError("Could not validate authentication token.")

    if claims is None:
        if last_sig_error:
            raise AuthenticationError("Token signature verification failed.")
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
    Generate signed JWT tokens for local login and development.
    Defaults to 15-minute expiration per N2.1 requirements.
    """
    to_encode = data.copy()
    now = datetime.datetime.now(datetime.timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + datetime.timedelta(minutes=15)

    to_encode.setdefault("exp", int(expire.timestamp()))
    to_encode.setdefault("iat", int(now.timestamp()))
    if "sub" not in to_encode:
        to_encode["sub"] = "default-user-uuid"

    # Unique JWT ID guarantees distinct tokens even when issued within the
    # same second (e.g. login immediately followed by refresh), preventing
    # byte-identical access tokens for distinct authentication events.
    to_encode.setdefault("jti", uuid.uuid4().hex)

    issuer = get_jwt_issuer()
    if issuer:
        to_encode.setdefault("iss", issuer)
    audience = get_jwt_audience()
    if audience:
        to_encode.setdefault("aud", audience)

    signing_secret = secret or get_local_jwt_secret()
    alg = algorithm or get_jwt_algorithms()[0]
    return jwt.encode(to_encode, signing_secret, algorithm=alg)


