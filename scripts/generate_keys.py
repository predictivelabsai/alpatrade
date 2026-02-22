#!/usr/bin/env python3
"""Generate ENCRYPTION_KEY and JWT_SECRET for AlpaTrade user auth.

Usage:
    python scripts/generate_keys.py
    python scripts/generate_keys.py >> .env
"""
import secrets
from cryptography.fernet import Fernet


def main():
    encryption_key = Fernet.generate_key().decode()
    jwt_secret = secrets.token_urlsafe(48)
    print(f"ENCRYPTION_KEY={encryption_key}")
    print(f"JWT_SECRET={jwt_secret}")


if __name__ == "__main__":
    main()
