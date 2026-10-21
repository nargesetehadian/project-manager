from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .validators import normalize_phone_number

User = get_user_model()
PASSWORD = "Test12345!x"


class PhoneNormalizationTests(TestCase):
    def test_all_valid_formats_collapse_to_one(self):
        formats = [
            "09123456789",
            "9123456789",
            "989123456789",
            "+989123456789",
            "00989123456789",
            "0912 345 6789",
            "0912-345-6789",
        ]
        for raw in formats:
            with self.subTest(raw=raw):
                self.assertEqual(normalize_phone_number(raw), "09123456789")

    def test_invalid_formats_are_rejected(self):
        invalid = [
            "08123456789",      # prefix is not 9
            "0912345",          # too short
            "091234567890",     # too long
            "+98912345678",     # too short with country code
            "+9809123456789",   # country code followed by a leading 0
            "9123456789a",      # trailing garbage
            "abc",
            "",
            None,
        ]
        for raw in invalid:
            with self.subTest(raw=raw):
                with self.assertRaises(ValidationError):
                    normalize_phone_number(raw)


class UserModelTests(TestCase):
    def test_login_field_is_phone_number(self):
        self.assertEqual(User.USERNAME_FIELD, "phone_number")

    def test_create_user_normalizes_phone_and_hashes_password(self):
        user = User.objects.create_user("+989123456789", PASSWORD)
        self.assertEqual(user.phone_number, "09123456789")
        self.assertNotEqual(user.password, PASSWORD)
        self.assertTrue(user.check_password(PASSWORD))
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_create_user_rejects_invalid_phone(self):
        with self.assertRaises(ValidationError):
            User.objects.create_user("12345", PASSWORD)

    def test_create_superuser_sets_flags(self):
        admin = User.objects.create_superuser("09123456789", PASSWORD)
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_superuser)

    def test_save_normalizes_phone(self):
        user = User(phone_number="9123456789")
        user.set_password(PASSWORD)
        user.save()
        user.refresh_from_db()
        self.assertEqual(user.phone_number, "09123456789")

    def test_same_number_in_another_format_violates_uniqueness(self):
        User.objects.create_user("09123456789", PASSWORD)
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                User.objects.create_user("00989123456789", PASSWORD)


class RegisterTests(APITestCase):
    def setUp(self):
        self.url = reverse("register")

    def post(self, phone, password=PASSWORD):
        return self.client.post(
            self.url, {"phone_number": phone, "password": password}, format="json"
        )

    def test_register_returns_tokens_and_normalized_phone(self):
        response = self.post("+989123456789")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["phone_number"], "09123456789")
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)
        self.assertNotIn("password", response.data)
        self.assertTrue(User.objects.get(phone_number="09123456789").check_password(PASSWORD))

    def test_same_number_in_other_format_is_rejected(self):
        self.assertEqual(self.post("09123456789").status_code, 201)
        for other in ["989123456789", "+989123456789", "00989123456789", "9123456789"]:
            with self.subTest(other=other):
                response = self.post(other)
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(User.objects.count(), 1)

    def test_invalid_phone_is_rejected(self):
        for phone in ["08123456789", "0912345", "abc", ""]:
            with self.subTest(phone=phone):
                self.assertEqual(self.post(phone).status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(User.objects.count(), 0)

    def test_weak_passwords_are_rejected(self):
        for password in ["short1", "12345678", "password"]:
            with self.subTest(password=password):
                self.assertEqual(
                    self.post("09123456789", password).status_code, status.HTTP_400_BAD_REQUEST
                )

    def test_missing_fields_are_rejected(self):
        response = self.client.post(self.url, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_concurrent_duplicate_becomes_400_not_500(self):
        # Simulates the race: the pre-check passed, but the database UNIQUE
        # constraint fires at insert time.
        with patch.object(User.objects, "create_user", side_effect=IntegrityError):
            response = self.post("09123456789")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("phone_number", response.data)


class LoginTests(APITestCase):
    def setUp(self):
        self.url = reverse("login")
        self.user = User.objects.create_user("09123456789", PASSWORD)

    def post(self, phone, password=PASSWORD):
        return self.client.post(
            self.url, {"phone_number": phone, "password": password}, format="json"
        )

    def test_login_success(self):
        response = self.post("09123456789")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)

    def test_login_accepts_any_phone_format(self):
        for phone in ["9123456789", "989123456789", "+989123456789", "00989123456789"]:
            with self.subTest(phone=phone):
                self.assertEqual(self.post(phone).status_code, status.HTTP_200_OK)

    def test_wrong_password(self):
        self.assertEqual(self.post("09123456789", "Wrong12345!").status_code, 400)

    def test_unknown_user(self):
        self.assertEqual(self.post("09350000000").status_code, 400)

    def test_inactive_user_cannot_login(self):
        self.user.is_active = False
        self.user.save()
        self.assertEqual(self.post("09123456789").status_code, 400)

    def test_error_message_does_not_reveal_which_part_was_wrong(self):
        wrong_password = self.post("09123456789", "Wrong12345!").data
        unknown_user = self.post("09350000000").data
        self.assertEqual(wrong_password, unknown_user)


class TokenTests(APITestCase):
    def setUp(self):
        User.objects.create_user("09123456789", PASSWORD)
        self.tokens = self.client.post(
            reverse("login"),
            {"phone_number": "09123456789", "password": PASSWORD},
            format="json",
        ).data

    def test_access_token_grants_access(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.tokens['access']}")
        self.assertEqual(self.client.get(reverse("project-list")).status_code, 200)

    def test_no_token_is_401(self):
        self.assertEqual(self.client.get(reverse("project-list")).status_code, 401)

    def test_garbage_token_is_401(self):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer not-a-real-token")
        self.assertEqual(self.client.get(reverse("project-list")).status_code, 401)

    def test_refresh_returns_new_access_token(self):
        response = self.client.post(
            reverse("token-refresh"), {"refresh": self.tokens["refresh"]}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
