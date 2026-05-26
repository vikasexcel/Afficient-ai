from fastapi import APIRouter
from fastapi import Depends
from sqlalchemy.orm import Session
from database.dependencies import get_db
from modules.auth.schema import RegisterInput
from modules.auth.service import AuthService
from modules.auth.schema import (
    LoginInput
)
from common.security.dependencies import (
    get_current_user
)

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
)


@router.post(
    "/register"
)
async def register(
    data: RegisterInput,
    db: Session = Depends(
        get_db
    ),
):

    return AuthService.register(
        db,
        data,
    )

@router.post(
    "/login"
)
async def login(
    data:LoginInput,
    db: Session =Depends(get_db),
):

    return (
        AuthService.login(db,data,)
    )


@router.get(
    "/me"
)
async def me(

    user=
    Depends(
        get_current_user
    ),

):

    return user