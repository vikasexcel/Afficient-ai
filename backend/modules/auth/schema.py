from pydantic import BaseModel
from pydantic import EmailStr


class RegisterInput(BaseModel):
    full_name: str

    email: EmailStr

    password: str

    organization: str

class LoginInput(
    BaseModel
):

    email: EmailStr

    password: str