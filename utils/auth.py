"""
User authentication and credential management.

Provides password hashing (bcrypt), Alpaca key encryption (Fernet),
user CRUD, and JWT token handling.
"""

import os
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Tuple

from cryptography.fernet import Fernet
from passlib.hash import bcrypt

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Encryption helpers
# ---------------------------------------------------------------------------

def _get_fernet() -> Fernet:
    """Return a Fernet instance using ENCRYPTION_KEY from env."""
    key = os.getenv("ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("ENCRYPTION_KEY not set — run: python scripts/generate_keys.py")
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_key(plaintext: str) -> bytes:
    """Encrypt an API key string, returning ciphertext bytes."""
    return _get_fernet().encrypt(plaintext.encode())


def decrypt_key(ciphertext: bytes) -> str:
    """Decrypt ciphertext bytes back to a plaintext string."""
    return _get_fernet().decrypt(ciphertext).decode()


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    """Hash a password with bcrypt."""
    return bcrypt.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its bcrypt hash."""
    return bcrypt.verify(password, password_hash)


# ---------------------------------------------------------------------------
# User CRUD
# ---------------------------------------------------------------------------

def _get_pool():
    from utils.db.db_pool import DatabasePool
    return DatabasePool()


def create_user(
    email: str,
    password: Optional[str] = None,
    google_id: Optional[str] = None,
    display_name: Optional[str] = None,
) -> Optional[Dict]:
    """
    Create a new user. Returns user dict or None if email already exists.

    At least one of password or google_id must be provided.
    """
    from sqlalchemy import text

    pw_hash = hash_password(password) if password else None
    pool = _get_pool()
    with pool.get_session() as session:
        result = session.execute(
            text("""
                INSERT INTO alpatrade.users
                    (email, password_hash, google_id, display_name)
                VALUES
                    (:email, :pw_hash, :google_id, :display_name)
                ON CONFLICT (email) DO NOTHING
                RETURNING user_id, email, display_name, is_admin, is_active, created_at
            """),
            {
                "email": email.lower().strip(),
                "pw_hash": pw_hash,
                "google_id": google_id,
                "display_name": display_name or email.split("@")[0],
            },
        )
        row = result.fetchone()
        if not row:
            return None
        return _row_to_user(row, result.keys())


def get_user_by_email(email: str) -> Optional[Dict]:
    """Fetch a user by email address."""
    from sqlalchemy import text
    pool = _get_pool()
    with pool.get_session() as session:
        result = session.execute(
            text("""
                SELECT user_id, email, password_hash, google_id,
                       display_name, is_admin, is_active, created_at
                FROM alpatrade.users
                WHERE email = :email AND is_active = TRUE
            """),
            {"email": email.lower().strip()},
        )
        row = result.fetchone()
        if not row:
            return None
        return _row_to_user(row, result.keys())


def get_user_by_id(user_id: str) -> Optional[Dict]:
    """Fetch a user by user_id (UUID)."""
    from sqlalchemy import text
    pool = _get_pool()
    with pool.get_session() as session:
        result = session.execute(
            text("""
                SELECT user_id, email, password_hash, google_id,
                       display_name, is_admin, is_active, created_at
                FROM alpatrade.users
                WHERE user_id = :user_id AND is_active = TRUE
            """),
            {"user_id": user_id},
        )
        row = result.fetchone()
        if not row:
            return None
        return _row_to_user(row, result.keys())


def get_user_by_google_id(google_id: str) -> Optional[Dict]:
    """Fetch a user by Google OAuth ID."""
    from sqlalchemy import text
    pool = _get_pool()
    with pool.get_session() as session:
        result = session.execute(
            text("""
                SELECT user_id, email, password_hash, google_id,
                       display_name, is_admin, is_active, created_at
                FROM alpatrade.users
                WHERE google_id = :google_id AND is_active = TRUE
            """),
            {"google_id": google_id},
        )
        row = result.fetchone()
        if not row:
            return None
        return _row_to_user(row, result.keys())


def authenticate(email: str, password: str) -> Optional[Dict]:
    """
    Authenticate by email + password.
    Returns user dict on success, None on failure.
    """
    user = get_user_by_email(email)
    if not user:
        return None
    if not user.get("password_hash"):
        return None  # Google-only account
    if not verify_password(password, user["password_hash"]):
        return None
    return user


def link_google_id(email: str, google_id: str) -> bool:
    """Link a Google ID to an existing user (for users who registered with email first)."""
    from sqlalchemy import text
    pool = _get_pool()
    with pool.get_session() as session:
        result = session.execute(
            text("""
                UPDATE alpatrade.users
                SET google_id = :google_id, updated_at = :now
                WHERE email = :email AND google_id IS NULL
            """),
            {
                "google_id": google_id,
                "email": email.lower().strip(),
                "now": datetime.now(timezone.utc),
            },
        )
        return result.rowcount > 0


# ---------------------------------------------------------------------------
# Alpaca key management
# ---------------------------------------------------------------------------

def store_alpaca_keys(user_id: str, api_key: str, secret_key: str) -> None:
    """Encrypt and store Alpaca API keys for a user."""
    from sqlalchemy import text
    pool = _get_pool()
    with pool.get_session() as session:
        session.execute(
            text("""
                UPDATE alpatrade.users
                SET alpaca_api_key_enc = :api_enc,
                    alpaca_secret_key_enc = :secret_enc,
                    updated_at = :now
                WHERE user_id = :user_id
            """),
            {
                "user_id": user_id,
                "api_enc": encrypt_key(api_key),
                "secret_enc": encrypt_key(secret_key),
                "now": datetime.now(timezone.utc),
            },
        )
    logger.info(f"Alpaca keys stored for user {user_id}")


def get_alpaca_keys(user_id: str) -> Optional[Tuple[str, str]]:
    """
    Retrieve and decrypt Alpaca keys for a user.
    Returns (api_key, secret_key) or None if not configured.
    """
    from sqlalchemy import text
    pool = _get_pool()
    with pool.get_session() as session:
        result = session.execute(
            text("""
                SELECT alpaca_api_key_enc, alpaca_secret_key_enc
                FROM alpatrade.users
                WHERE user_id = :user_id
            """),
            {"user_id": user_id},
        )
        row = result.fetchone()
        if not row or not row[0] or not row[1]:
            return None
        api_enc, secret_enc = row
        # Handle memoryview from psycopg2
        if isinstance(api_enc, memoryview):
            api_enc = bytes(api_enc)
        if isinstance(secret_enc, memoryview):
            secret_enc = bytes(secret_enc)
        return decrypt_key(api_enc), decrypt_key(secret_enc)


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def create_jwt_token(user_id: str, email: str) -> str:
    """Create a JWT token for API authentication."""
    import jwt
    from datetime import timedelta

    secret = os.getenv("JWT_SECRET")
    if not secret:
        raise RuntimeError("JWT_SECRET not set — run: python scripts/generate_keys.py")
    payload = {
        "user_id": str(user_id),
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(days=7),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_jwt_token(token: str) -> Optional[Dict]:
    """Decode and verify a JWT token. Returns payload dict or None."""
    import jwt

    secret = os.getenv("JWT_SECRET")
    if not secret:
        return None
    try:
        return jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        logger.debug("JWT expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.debug(f"Invalid JWT: {e}")
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_user(row, keys) -> Dict:
    """Convert a DB row to a user dict."""
    d = dict(zip(keys, row))
    # Convert UUID to string for JSON serialization
    if d.get("user_id"):
        d["user_id"] = str(d["user_id"])
    return d
