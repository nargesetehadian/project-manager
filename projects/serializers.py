from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from accounts.validators import normalize_phone_number

from .models import Project, ProjectMember

User = get_user_model()


class ProjectSerializer(serializers.ModelSerializer):
    my_role = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = ["id", "name", "description", "my_role", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_my_role(self, obj):
        request = self.context.get("request")
        if request is None:
            return None
        member = obj.members.filter(user=request.user).first()
        return member.role if member else None


class ProjectMemberSerializer(serializers.ModelSerializer):
    phone_number = serializers.CharField(source="user.phone_number", read_only=True)

    class Meta:
        model = ProjectMember
        fields = ["id", "user", "phone_number", "role", "joined_at"]
        read_only_fields = fields


class AddMemberSerializer(serializers.Serializer):
    phone_number = serializers.CharField()
    role = serializers.ChoiceField(choices=ProjectMember.Role.choices, default=ProjectMember.Role.MEMBER)

    def validate_phone_number(self, value):
        try:
            value = normalize_phone_number(value)
        except DjangoValidationError as e:
            raise serializers.ValidationError(e.messages)
        try:
            return User.objects.get(phone_number=value)
        except User.DoesNotExist:
            raise serializers.ValidationError("No user with this phone number.")
