from fastapi import Depends
from fastapi import HTTPException

from fastapi.security import (
    HTTPBearer,
)

from common.security.jwt import (
    decode_token,
)


bearer = HTTPBearer()


def get_current_user(

    token=Depends(
        bearer
    ),

):

    payload = decode_token(
        token.credentials
    )

    if not payload:

        raise HTTPException(
            401,
            "Unauthorized",
        )

    return payload