from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from rest_framework import serializers

from .validators import normalize_phone_number


User = get_user_model()


class PhoneNumberField(serializers.CharField):

    def to_internal_value(self, data):
        value = super().to_internal_value(data)  
        try:
            return normalize_phone_number(value)
        except DjangoValidationError as e:
    
            raise serializers.ValidationError(e.messages)


class RegisterSerializer(serializers.Serializer):
    phone_number = PhoneNumberField()
   
    password = serializers.CharField(write_only=True, min_length=8)

    
    def validate_phone_number(self, value):
       
        if User.objects.filter(phone_number=value).exists():
            raise serializers.ValidationError("A user with this phone number already exists.")
        return value

    def validate_password(self, value):
      
        try:
            validate_password(value)
        except DjangoValidationError as e:
            raise serializers.ValidationError(list(e.messages))
        return value

    def create(self, validated_data):
      
        try:
            with transaction.atomic():

                return User.objects.create_user(
                    phone_number=validated_data["phone_number"],
                    password=validated_data["password"],
                )
        except IntegrityError:
            raise serializers.ValidationError(
                {"phone_number": "A user with this phone number already exists."}
            )


class LoginSerializer(serializers.Serializer):
    phone_number = PhoneNumberField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):

        user = authenticate(
            request=self.context.get("request"),
            username=attrs["phone_number"],
            password=attrs["password"],
        )
        if user is None:

          
            raise serializers.ValidationError("Invalid phone number or password.")
        attrs["user"] = user
        return attrs