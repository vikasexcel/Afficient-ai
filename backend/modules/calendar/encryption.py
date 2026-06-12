"""Fernet symmetric encryption for OAuth tokens at rest.

Tokens are stored encrypted in Postgres so a DB dump alone is not enough
to impersonate a user on Google's APIs.

Key management
--------------
``TOKEN_ENCRYPTION_KEY`` must be a URL-safe base64-encoded 32-byte key
(the output of ``Fernet.generate_key()``). Generate once:

    from cryptography.fernet import Fernet
    print(Fernet.generate_key().decode())

Store it as an env var — never commit it.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from config.settings import settings
from modules.calendar.exceptions import CalendarError


def _fernet() -> Fernet:
    key = settings.TOKEN_ENCRYPTION_KEY
    if not key:
        raise CalendarError(
            "TOKEN_ENCRYPTION_KEY is not set — cannot store/retrieve calendar tokens",
            status_code=500,
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_token(plain: str) -> str:
    """Return a Fernet-encrypted, base64-encoded ciphertext string."""
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_token(cipher: str) -> str:
    """Decrypt a token previously encrypted by :func:`encrypt_token`."""
    try:
        return _fernet().decrypt(cipher.encode()).decode()
    except InvalidToken as exc:
        raise CalendarError(
            "Failed to decrypt calendar token — key may have changed",
            status_code=500,
        ) from exc
