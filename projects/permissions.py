from rest_framework.permissions import SAFE_METHODS, BasePermission

from .models import ProjectMember

Role = ProjectMember.Role


def get_membership(user, project):
    return ProjectMember.objects.filter(project=project, user=user).first()


class ProjectPermission(BasePermission):
    """
    member -> read only
    admin  -> read + edit
    owner  -> everything (including delete)
    """

    def has_object_permission(self, request, view, obj):
        membership = get_membership(request.user, obj)
        if membership is None:
            return False
        if request.method in SAFE_METHODS:
            return True
        if request.method == "DELETE":
            return membership.role == Role.OWNER
        return membership.role in (Role.OWNER, Role.ADMIN)
