from fastapi import Depends, HTTPException

from common.security.roles import Role
from modules.auth.tenant import get_current_tenant


def require_role(allowed):
    """Legacy callable form: require_role([Role.OWNER, Role.ADMIN])(tenant)."""

    allowed_values = {r.value if isinstance(r, Role) else r for r in allowed}

    def check(tenant):
        if str(tenant["role"]) not in allowed_values:
            raise HTTPException(403, "Permission denied")
        return tenant

    return check


def requires(*allowed: Role):
    """FastAPI dependency factory. Usage:

        @router.get(..., dependencies=[Depends(requires(Role.OWNER, Role.ADMIN))])

    or use it to inject the tenant:

        def handler(tenant=Depends(requires(Role.OWNER))): ...
    """

    allowed_values = {r.value for r in allowed}

    def dep(tenant=Depends(get_current_tenant)):
        if str(tenant["role"]) not in allowed_values:
            raise HTTPException(403, "Permission denied")
        return tenant

    return dep
