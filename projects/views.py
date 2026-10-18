from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from .models import Project, ProjectMember
from .permissions import ProjectPermission
from .serializers import AddMemberSerializer, ProjectMemberSerializer, ProjectSerializer

Role = ProjectMember.Role


class ProjectListCreateView(generics.ListCreateAPIView):
    serializer_class = ProjectSerializer

    def get_queryset(self):
        # only projects the user is a member of
        return Project.objects.filter(members__user=self.request.user)

    @transaction.atomic
    def perform_create(self, serializer):
        project = serializer.save()
        ProjectMember.objects.create(project=project, user=self.request.user, role=Role.OWNER)


class ProjectDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ProjectSerializer
    permission_classes = [ProjectPermission]

    def get_queryset(self):
        # non-members get 404 instead of leaking that the project exists
        return Project.objects.filter(members__user=self.request.user)


def get_my_membership(request, project_id):
    return get_object_or_404(ProjectMember, project_id=project_id, user=request.user)


class MemberListCreateView(generics.ListCreateAPIView):
    serializer_class = ProjectMemberSerializer

    def get_queryset(self):
        get_my_membership(self.request, self.kwargs["project_id"])
        return ProjectMember.objects.filter(project_id=self.kwargs["project_id"]).select_related("user")

    def create(self, request, *args, **kwargs):
        me = get_my_membership(request, kwargs["project_id"])
        if me.role not in (Role.OWNER, Role.ADMIN):
            raise PermissionDenied("Only owners and admins can add members.")

        serializer = AddMemberSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["phone_number"]
        role = serializer.validated_data["role"]

        # admins are only allowed to add regular members
        if me.role == Role.ADMIN and role != Role.MEMBER:
            raise PermissionDenied("Admins can only add members with the member role.")

        if ProjectMember.objects.filter(project_id=kwargs["project_id"], user=user).exists():
            raise ValidationError({"phone_number": "This user is already a member."})

        member = ProjectMember.objects.create(project_id=kwargs["project_id"], user=user, role=role)
        return Response(ProjectMemberSerializer(member).data, status=status.HTTP_201_CREATED)


class MemberDeleteView(generics.DestroyAPIView):
    def get_object(self):
        me = get_my_membership(self.request, self.kwargs["project_id"])
        target = get_object_or_404(
            ProjectMember, pk=self.kwargs["pk"], project_id=self.kwargs["project_id"]
        )

        if me.role not in (Role.OWNER, Role.ADMIN):
            raise PermissionDenied("Only owners and admins can remove members.")
        if target.role == Role.OWNER:
            raise PermissionDenied("The owner can't be removed from the project.")
        if me.role == Role.ADMIN and target.role == Role.ADMIN:
            raise PermissionDenied("Admins can't remove other admins.")
        return target
