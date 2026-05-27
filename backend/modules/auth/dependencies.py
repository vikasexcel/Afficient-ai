from fastapi import Depends
from common.security.dependencies import (
    get_current_user
)


def get_current_org(

    user=
    Depends(
        get_current_user
    ),

):

    return {
        "organization":
        "current"
    }