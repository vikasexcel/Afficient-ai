from enum import Enum

class Role(str,Enum,):
    OWNER = "owner"
    ADMIN = "admin"
    AGENT = "agent"
    MEMBER = "member"