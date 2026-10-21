from django.db import IntegrityError, transaction
from django.db.models import F, FilteredRelation, Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError

from .models import Project, ProjectMember
from .roles import Role, can_manage


class LastOwnerError(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "A project must always keep at least one owner."
    default_code = "last_owner"


# ---------- reads ----------

def projects_for_user(user):
    # One JOIN limited to my membership; role exposed as `my_role`
    # (no extra query per project, reused by serializer and permission)
    return (
        Project.objects
        .annotate(mine=FilteredRelation("members", condition=Q(members__user=user)))
        .filter(mine__isnull=False)
        .annotate(my_role=F("mine__role"))
        .order_by("-created_at", "-id")
    )


def get_membership(user, project_id):
    # Non-member -> 404 (hides project existence)
    return get_object_or_404(ProjectMember, project_id=project_id, user=user)


def members_of(user, project_id):
    get_membership(user, project_id)
    return (
        ProjectMember.objects.filter(project_id=project_id)
        .select_related("user")
        .order_by("joined_at", "id")
    )


# ---------- writes ----------

@transaction.atomic
def create_project(*, owner, **data):
    project = Project.objects.create(**data)
    ProjectMember.objects.create(project=project, user=owner, role=Role.OWNER)
    project.my_role = Role.OWNER.value
    return project


def add_member(*, actor_role, project_id, user, role):
    if not can_manage(actor_role, role):
        raise PermissionDenied("You can't grant this role.")
    # DB unique constraint is the source of truth (no check-then-insert race)
    try:
        with transaction.atomic():
            return ProjectMember.objects.create(project_id=project_id, user=user, role=role)
    except IntegrityError:
        raise ValidationError({"phone_number": "This user is already a member."})


def remove_member(*, actor, project_id, membership_id):
    get_membership(actor, project_id)  # outsiders: 404 before any lock

    with transaction.atomic():
        # Row lock serializes concurrent removals (last-owner race)
        project = get_object_or_404(Project.objects.select_for_update(), pk=project_id)
        me = get_object_or_404(ProjectMember, project=project, user=actor)
        target = get_object_or_404(ProjectMember, pk=membership_id, project=project)

        if not can_manage(me.role, target.role):
            raise PermissionDenied("You can't remove this member.")
        if target.role == Role.OWNER:
            owners = ProjectMember.objects.filter(project=project, role=Role.OWNER).count()
            if owners <= 1:
                raise LastOwnerError()

        target.delete()
