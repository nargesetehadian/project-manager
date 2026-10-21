from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError
from rest_framework.response import Response

from .models import Project, ProjectMember
from .permissions import ProjectPermission
from .serializers import AddMemberSerializer, ProjectMemberSerializer, ProjectSerializer

Role = ProjectMember.Role


class LastOwnerError(APIException):

    status_code = status.HTTP_409_CONFLICT
    default_detail = "A project must always keep at least one owner."
    default_code = "last_owner"


class ProjectListCreateView(generics.ListCreateAPIView):
    serializer_class = ProjectSerializer

    def get_queryset(self):

        return Project.objects.filter(members__user=self.request.user)

 
    @transaction.atomic
    def perform_create(self, serializer):
        project = serializer.save()
   
        ProjectMember.objects.create(project=project, user=self.request.user, role=Role.OWNER)


class ProjectDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ProjectSerializer
    permission_classes = [ProjectPermission]

    def get_queryset(self):
 
        return Project.objects.filter(members__user=self.request.user)


def get_my_membership(request, project_id):

    return get_object_or_404(ProjectMember, project_id=project_id, user=request.user)


class MemberListCreateView(generics.ListCreateAPIView):
    serializer_class = ProjectMemberSerializer

    def get_queryset(self):
 
        get_my_membership(self.request, self.kwargs["project_id"])
 
        return ProjectMember.objects.filter(
            project_id=self.kwargs["project_id"]
        ).select_related("user")


    def create(self, request, *args, **kwargs):
        me = get_my_membership(request, kwargs["project_id"])
        if me.role not in (Role.OWNER, Role.ADMIN):
            raise PermissionDenied("Only owners and admins can add members.")

        serializer = AddMemberSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["phone_number"]  
        role = serializer.validated_data["role"]


        if me.role == Role.ADMIN and role != Role.MEMBER:
            raise PermissionDenied("Admins can only add members with the member role.")


        try:
            with transaction.atomic():
                member = ProjectMember.objects.create(
                    project_id=kwargs["project_id"], user=user, role=role
                )
        except IntegrityError:
            raise ValidationError({"phone_number": "This user is already a member."})

        
        return Response(ProjectMemberSerializer(member).data, status=status.HTTP_201_CREATED)


class MemberDeleteView(generics.DestroyAPIView):

    def destroy(self, request, *args, **kwargs):
        project_id = kwargs["project_id"]


        get_my_membership(request, project_id)


        with transaction.atomic():
            project = get_object_or_404(Project.objects.select_for_update(), pk=project_id)
            me = get_object_or_404(ProjectMember, project=project, user=request.user)

            target = get_object_or_404(ProjectMember, pk=kwargs["pk"], project=project)

            if me.role not in (Role.OWNER, Role.ADMIN):
                raise PermissionDenied("Only owners and admins can remove members.")
            if me.role == Role.ADMIN and target.role != Role.MEMBER:
                raise PermissionDenied("Admins can only remove regular members.")
            if target.role == Role.OWNER:
                owners = ProjectMember.objects.filter(project=project, role=Role.OWNER).count()
                if owners <= 1:
                    raise LastOwnerError()

            target.delete()

        return Response(status=status.HTTP_204_NO_CONTENT)