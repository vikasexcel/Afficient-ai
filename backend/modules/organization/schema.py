from pydantic import BaseModel


class OrganizationOut(BaseModel):
    id: str
    name: str


class RenameInput(BaseModel):
    name: str


class TransferOwnershipInput(BaseModel):
    membership_id: str
