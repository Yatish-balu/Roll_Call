"""Multi-factor authentication primitives with authenticated encryption.

MFA secrets are protected with **AES-GCM** (authenticated encryption):

* a fresh 96-bit nonce is generated for every encryption,
* the authentication tag is verified on decryption (a modified ciphertext or a
  wrong key raises),
* the encryption key comes from the environment (``MFA_ENCRYPTION_KEY``) and is
  never stored in the database, logged or returned to a client.

If the key is missing in production the module **fails closed**: enrollment and
every secret-dependent operation raise. There is no XOR or plaintext fallback.

Recovery codes are generated from a CSPRNG, stored as salted hashes and are
single-use.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import secrets
import struct
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Sequence, Tuple

logger = logging.getLogger("rollcall.security.mfa")

#: Environment variable holding the AES-GCM key (base64 or hex, 32 bytes).
MFA_ENCRYPTION_KEY_ENV = "MFA_ENCRYPTION_KEY"

#: Number of recovery codes issued with an enrollment.
RECOVERY_CODE_COUNT = 10

#: Length of a recovery code (human readable, unambiguous alphabet).
_RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class MFAError(Exception):
    """Base error for MFA operations."""


class MFAConfigurationError(MFAError):
    """Raised when MFA is not configured (missing encryption key)."""


class MFADecryptionError(MFAError):
    """Raised when a secret cannot be decrypted or its tag does not verify."""


def _is_production() -> bool:
    return os.getenv("APP_ENV", "development").strip().lower() == "production"


def get_encryption_key() -> bytes:
    """Return the AES-GCM key from the environment.

    Raises :class:`MFAConfigurationError` when the key is missing, too short or
    invalid - in production this fails closed.
    """
    raw = os.getenv(MFA_ENCRYPTION_KEY_ENV, "").strip()
    if not raw:
        raise MFAConfigurationError(
            f"{MFA_ENCRYPTION_KEY_ENV} is not configured; MFA operations are unavailable."
        )
    key: Optional[bytes] = None
    try:
        key = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    except Exception:
        key = None
    if key is None or len(key) not in (16, 24, 32):
        try:
            key = bytes.fromhex(raw)
        except Exception:
            key = None
    if key is None or len(key) not in (16, 24, 32):
        raise MFAConfigurationError(
            f"{MFA_ENCRYPTION_KEY_ENV} must be a base64 or hex encoded 16/24/32 byte key."
        )
    return key


def mfa_configured() -> bool:
    """True when an encryption key is provisioned."""
    try:
        get_encryption_key()
        return True
    except MFAConfigurationError:
        return False


def _aesgcm():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:  # pragma: no cover - dependency missing
        raise MFAConfigurationError(
            "The 'cryptography' package is required for MFA encryption."
        ) from exc
    return AESGCM


def encrypt_secret(plaintext: str, *, key: Optional[bytes] = None) -> str:
    """Encrypt an MFA secret with AES-GCM.

    Returns a self-describing string ``v1:<base64(nonce+ciphertext+tag)>``.
    A fresh nonce is generated for every call.
    """
    if not plaintext:
        raise MFAError("Refusing to encrypt an empty MFA secret.")
    secret_key = key or get_encryption_key()
    aesgcm = _aesgcm()
    nonce = os.urandom(12)
    ciphertext = aesgcm(secret_key).encrypt(nonce, plaintext.encode("utf-8"), None)
    return "v1:" + base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")


def decrypt_secret(payload: str, *, key: Optional[bytes] = None) -> str:
    """Decrypt and verify an AES-GCM protected MFA secret.

    Raises :class:`MFADecryptionError` when the payload is malformed, the key
    is wrong or the authentication tag does not verify.
    """
    if not payload or not payload.startswith("v1:"):
        raise MFADecryptionError("Unsupported MFA secret format.")
    secret_key = key or get_encryption_key()
    aesgcm = _aesgcm()
    try:
        raw = base64.urlsafe_b64decode(payload[3:] + "=" * (-len(payload[3:]) % 4))
    except Exception as exc:
        raise MFADecryptionError("Malformed MFA secret payload.") from exc
    if len(raw) < 13:
        raise MFADecryptionError("Malformed MFA secret payload.")
    nonce, ciphertext = raw[:12], raw[12:]
    try:
        plaintext = aesgcm(secret_key).decrypt(nonce, ciphertext, None)
    except Exception as exc:
        # Wrong key or modified ciphertext: the tag does not verify.
        raise MFADecryptionError("MFA secret could not be decrypted (authentication failed).") from exc
    return plaintext.decode("utf-8")


def generate_mfa_secret() -> str:
    """Generate a new base32 TOTP secret."""
    return base64.b32encode(os.urandom(20)).decode("ascii").rstrip("=")


def generate_recovery_codes(count: int = RECOVERY_CODE_COUNT) -> List[str]:
    """Generate human-readable single-use recovery codes."""
    codes: List[str] = []
    for _ in range(max(1, count)):
        groups = ["".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(5)) for _ in range(2)]
        codes.append("-".join(groups))
    return codes


def hash_recovery_code(code: str, salt: Optional[str] = None) -> str:
    """Hash a recovery code for storage (PBKDF2-HMAC-SHA256)."""
    clean = (code or "").strip().upper().replace("-", "")
    if not clean:
        raise MFAError("Refusing to hash an empty recovery code.")
    salt_bytes = salt.encode("utf-8") if salt else os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", clean.encode("utf-8"), salt_bytes, 120_000)
    return f"pbkdf2_sha256$120000${base64.b64encode(salt_bytes).decode('ascii')}${digest.hex()}"


def verify_recovery_code(code: str, stored: Sequence[str]) -> Optional[str]:
    """Return the stored hash matching the code, or None.

    Every candidate is compared in constant time; the caller consumes the
    returned entry so a recovery code can only be used once.
    """
    clean = (code or "").strip().upper()
    if not clean:
        return None
    for candidate in stored or []:
        try:
            parts = str(candidate).split("$")
            if len(parts) != 4:
                continue
            _, iterations, salt_b64, digest_hex = parts
            salt_bytes = base64.b64decode(salt_b64)
            computed = hashlib.pbkdf2_hmac(
                "sha256", clean.replace("-", "").encode("utf-8"), salt_bytes, int(iterations)
            ).hex()
            if hmac.compare_digest(computed, digest_hex):
                return str(candidate)
        except Exception:
            continue
    return None


def _base32_decode(secret: str) -> bytes:
    padded = secret.strip().upper()
    padded += "=" * (-len(padded) % 8)
    return base64.b32decode(padded)


def totp_code(secret: str, timestamp: Optional[int] = None, time_step: int = 30) -> str:
    """Compute the current TOTP code (RFC 6238, SHA-1, 6 digits)."""
    key = _base32_decode(secret)
    counter = (timestamp if timestamp is not None else int(datetime.now(timezone.utc).timestamp())) // time_step
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[19] & 0x0F
    code = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(code % 1_000_000).zfill(6)


def verify_totp(
    secret: str,
    code: str,
    *,
    last_counter: Optional[int] = None,
    window: int = 1,
    time_step: int = 30,
    allow_same_step: bool = False,
) -> Tuple[bool, Optional[int]]:
    """Verify a TOTP code.

    Returns ``(valid, counter)``. ``counter`` is the time step the code
    belongs to, which the caller stores to prevent replay. ``allow_same_step``
    accepts the current step again, which is only used for explicitly
    password-gated administrative actions (disabling MFA directly after
    activating it with the same code).
    """
    clean = (code or "").strip()
    if not clean.isdigit() or len(clean) != 6:
        return False, None
    now = int(datetime.now(timezone.utc).timestamp())
    current_counter = now // time_step
    for drift in range(-window, window + 1):
        counter = current_counter + drift
        expected = totp_code(secret, timestamp=counter * time_step, time_step=time_step)
        if hmac.compare_digest(expected, clean):
            if last_counter is not None:
                if counter < last_counter:
                    # Replay of an already used time step.
                    return False, None
                if counter == last_counter and not allow_same_step:
                    return False, None
            return True, counter
    return False, None
