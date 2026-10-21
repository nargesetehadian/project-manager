from rest_framework.permissions import SAFE_METHODS, BasePermission

from .roles import Role, at_least


class ProjectPermission(BasePermission):
    # member: read | admin: read + edit | owner: everything
    # obj.my_role is annotated by services.projects_for_user (no extra query)
    def has_object_permission(self, request, view, obj):
        role = obj.my_role
        if request.method in SAFE_METHODS:
            return True
        if request.method == "DELETE":
            return role == Role.OWNER
        return at_least(role, Role.ADMIN)
