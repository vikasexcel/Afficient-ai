from datetime import datetime
from datetime import timedelta

from jose import jwt
from jose import JWTError

from config.settings import settings


def create_token(
    user_id: str,
):

    payload = {
        "sub": user_id,
        "exp": datetime.utcnow()
        + timedelta(
            minutes=settings.JWT_EXPIRE_MINUTES
        ),
    }

    return jwt.encode(
        payload,
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )


def decode_token(
    token: str,
):

    try:

        return jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[
                settings.JWT_ALGORITHM
            ],
        )

    except JWTError:

        return None


def create_refresh_token(
    user_id,
):

    payload = {
        "sub":
        user_id,

        "type":
        "refresh",

        "exp":
        datetime.utcnow()
        + timedelta(
            days=30
        ),
    }

    return jwt.encode(
        payload,
        settings.JWT_SECRET,
        algorithm=
        settings.JWT_ALGORITHM,
    )