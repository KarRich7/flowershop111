from rest_framework.permissions import BasePermission

OWNER, FLORIST, COURIER = "owner", "florist", "courier"


def roles(*allowed):
    class _RolePermission(BasePermission):
        message = "Недостаточно прав для этого раздела"

        def has_permission(self, request, view):
            u = request.user
            return bool(u and u.is_authenticated and not getattr(u, "is_bot", False) and u.is_active
                        and getattr(u, "role", None) in allowed)

    _RolePermission.__name__ = f"Roles_{'_'.join(allowed)}"
    return _RolePermission


AnyStaff = roles(OWNER, FLORIST, COURIER)
FloristOrOwner = roles(OWNER, FLORIST)
OwnerOnly = roles(OWNER)
