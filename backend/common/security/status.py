from enum import Enum


class MembershipStatus(str, Enum):
    ACTIVE = "active"
    PENDING = "pending"
