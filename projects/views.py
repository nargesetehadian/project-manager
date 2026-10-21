from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated


from . import services
from .permissions import ProjectPermission
from .roles import Role, at_least
from .serializers import AddMemberSerializer, ProjectMemberSerializer, ProjectSerializer


class ProjectListCreateView(generics.ListCreateAPIView):
    serializer_class = ProjectSerializer

    def get_queryset(self):
        return services.projects_for_user(self.request.user)

    def perform_create(self, serializer):
        # Creator becomes owner (atomic, inside service)
        serializer.instance = services.create_project(
            owner=self.request.user, **serializer.validated_data
        )


class ProjectDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ProjectSerializer
    permission_classes = [IsAuthenticated, ProjectPermission]

    def get_queryset(self):
        # Members only: outsiders get 404
        return services.projects_for_user(self.request.user)


class MemberListCreateView(generics.ListCreateAPIView):
    serializer_class = ProjectMemberSerializer

    def get_queryset(self):
        return services.members_of(self.request.user, self.kwargs["project_id"])

    def create(self, request, *args, **kwargs):
        project_id = kwargs["project_id"]
        me = services.get_membership(request.user, project_id)

        # Authorize first, validate later (no user enumeration by non-managers)
        if not at_least(me.role, Role.ADMIN):
            raise PermissionDenied("Only owners and admins can add members.")

        serializer = AddMemberSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        member = services.add_member(
            actor_role=me.role,
            project_id=project_id,
            user=serializer.validated_data["phone_number"],  # a User object
            role=serializer.validated_data["role"],
        )
        return Response(ProjectMemberSerializer(member).data, status=status.HTTP_201_CREATED)


class MemberDeleteView(generics.DestroyAPIView):
    def destroy(self, request, *args, **kwargs):
        services.remove_member(
            actor=request.user,
            project_id=kwargs["project_id"],
            membership_id=kwargs["pk"],  # membership id, not user id
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
