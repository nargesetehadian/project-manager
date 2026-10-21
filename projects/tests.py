import threading
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection
from django.test import SimpleTestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from .models import Project, ProjectMember
from .roles import at_least, can_manage

User = get_user_model()
Role = ProjectMember.Role
PASSWORD = "Test12345!x"


def make_user(phone):
    return User.objects.create_user(phone, PASSWORD)


def make_project(owner, name="Alpha"):
    project = Project.objects.create(name=name)
    ProjectMember.objects.create(project=project, user=owner, role=Role.OWNER)
    return project


def add_member(project, user, role):
    return ProjectMember.objects.create(project=project, user=user, role=role)


def owners_of(project):
    return ProjectMember.objects.filter(project=project, role=Role.OWNER).count()


class BaseProjectTest(APITestCase):
    """One project with an owner, an admin and a member, plus an outsider."""

    def setUp(self):
        self.owner = make_user("09120000001")
        self.admin = make_user("09120000002")
        self.member = make_user("09120000003")
        self.outsider = make_user("09120000004")

        self.project = make_project(self.owner)
        self.owner_m = ProjectMember.objects.get(project=self.project, user=self.owner)
        self.admin_m = add_member(self.project, self.admin, Role.ADMIN)
        self.member_m = add_member(self.project, self.member, Role.MEMBER)

        self.detail_url = reverse("project-detail", args=[self.project.pk])
        self.members_url = reverse("member-list", args=[self.project.pk])

    def login(self, user):
        self.client.force_authenticate(user=user)

    def member_url(self, membership, project=None):
        project = project or self.project
        return reverse("member-detail", args=[project.pk, membership.pk])


class ProjectEndpointTests(BaseProjectTest):
    def test_unauthenticated_requests_are_rejected(self):
        self.assertEqual(self.client.get(reverse("project-list")).status_code, 401)
        self.assertEqual(self.client.get(self.detail_url).status_code, 401)
        self.assertEqual(self.client.get(self.members_url).status_code, 401)

    def test_creator_becomes_owner(self):
        self.login(self.outsider)
        response = self.client.post(
            reverse("project-list"), {"name": "New", "description": "d"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["my_role"], Role.OWNER)
        membership = ProjectMember.objects.get(
            project_id=response.data["id"], user=self.outsider
        )
        self.assertEqual(membership.role, Role.OWNER)

    def test_name_is_required(self):
        self.login(self.owner)
        before = Project.objects.count()
        response = self.client.post(reverse("project-list"), {"description": "x"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Project.objects.count(), before)

    def test_list_contains_only_my_projects(self):
        other = make_project(self.outsider, name="Beta")
        self.login(self.owner)
        ids = [p["id"] for p in self.client.get(reverse("project-list")).data["results"]]
        self.assertEqual(ids, [self.project.pk])
        self.login(self.outsider)
        ids = [p["id"] for p in self.client.get(reverse("project-list")).data["results"]]
        self.assertEqual(ids, [other.pk])

    def test_list_is_paginated(self):
        self.login(self.owner)
        data = self.client.get(reverse("project-list")).data
        self.assertEqual(set(data), {"count", "next", "previous", "results"})

    def test_list_query_count_is_constant(self):
        self.login(self.owner)
        url = reverse("project-list")
        with CaptureQueriesContext(connection) as before:
            self.client.get(url)
        for i in range(5):
            make_project(self.owner, name=f"Extra {i}")
        with CaptureQueriesContext(connection) as after:
            self.client.get(url)
        self.assertEqual(len(before), len(after))

    def test_detail_reports_my_role(self):
        for user, role in [(self.owner, Role.OWNER), (self.admin, Role.ADMIN), (self.member, Role.MEMBER)]:
            with self.subTest(role=role):
                self.login(user)
                response = self.client.get(self.detail_url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data["my_role"], role)

    def test_outsider_gets_404_not_403(self):
        self.login(self.outsider)
        self.assertEqual(self.client.get(self.detail_url).status_code, 404)
        self.assertEqual(self.client.patch(self.detail_url, {"name": "x"}, format="json").status_code, 404)
        self.assertEqual(self.client.delete(self.detail_url).status_code, 404)

    def test_update_permissions(self):
        self.login(self.member)
        response = self.client.patch(self.detail_url, {"name": "Hacked"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.project.refresh_from_db()
        self.assertEqual(self.project.name, "Alpha")

        self.login(self.admin)
        response = self.client.patch(self.detail_url, {"name": "By admin"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.login(self.owner)
        response = self.client.put(
            self.detail_url, {"name": "By owner", "description": "full"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.project.refresh_from_db()
        self.assertEqual((self.project.name, self.project.description), ("By owner", "full"))

    def test_delete_permissions(self):
        for user in (self.member, self.admin):
            with self.subTest(user=user.phone_number):
                self.login(user)
                self.assertEqual(self.client.delete(self.detail_url).status_code, 403)
        self.assertTrue(Project.objects.filter(pk=self.project.pk).exists())

        self.login(self.owner)
        self.assertEqual(self.client.delete(self.detail_url).status_code, 204)
        self.assertFalse(Project.objects.filter(pk=self.project.pk).exists())
        self.assertFalse(ProjectMember.objects.filter(project_id=self.project.pk).exists())


class MemberListTests(BaseProjectTest):
    def test_any_member_can_list(self):
        for user in (self.owner, self.admin, self.member):
            with self.subTest(user=user.phone_number):
                self.login(user)
                response = self.client.get(self.members_url)
                self.assertEqual(response.status_code, 200)
                phones = sorted(m["phone_number"] for m in response.data["results"])
                self.assertEqual(phones, ["09120000001", "09120000002", "09120000003"])

    def test_outsider_gets_404(self):
        self.login(self.outsider)
        self.assertEqual(self.client.get(self.members_url).status_code, 404)

    def test_query_count_is_constant(self):
        self.login(self.owner)
        with CaptureQueriesContext(connection) as before:
            self.client.get(self.members_url)
        for i in range(5):
            add_member(self.project, make_user(f"0912999100{i}"), Role.MEMBER)
        with CaptureQueriesContext(connection) as after:
            self.client.get(self.members_url)
        self.assertEqual(len(before), len(after))


class MemberAddTests(BaseProjectTest):
    def setUp(self):
        super().setUp()
        self.newcomer = make_user("09125550000")

    def add(self, phone="09125550000", role=None):
        data = {"phone_number": phone}
        if role is not None:
            data["role"] = role
        return self.client.post(self.members_url, data, format="json")

    def test_owner_can_add_every_role(self):
        self.login(self.owner)
        for index, role in enumerate([Role.MEMBER, Role.ADMIN, Role.OWNER]):
            with self.subTest(role=role):
                user = make_user(f"0912666000{index}")
                response = self.add(user.phone_number, role)
                self.assertEqual(response.status_code, status.HTTP_201_CREATED)
                self.assertEqual(response.data["role"], role)

    def test_role_defaults_to_member(self):
        self.login(self.owner)
        response = self.add()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["role"], Role.MEMBER)

    def test_phone_can_be_sent_in_any_format(self):
        self.login(self.owner)
        response = self.add("+989125550000")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["phone_number"], "09125550000")

    def test_invalid_input_is_rejected(self):
        self.login(self.owner)
        self.assertEqual(self.add("09350000000").status_code, 400)       # unknown user
        self.assertEqual(self.add("0812345").status_code, 400)           # invalid phone
        self.assertEqual(self.add(role="superboss").status_code, 400)    # invalid role
        self.assertEqual(self.client.post(self.members_url, {}, format="json").status_code, 400)

    def test_duplicate_member_is_rejected(self):
        self.login(self.owner)
        self.assertEqual(self.add().status_code, 201)
        self.assertEqual(self.add().status_code, 400)
        self.assertEqual(self.add("+989125550000").status_code, 400)  # same user, other format
        self.assertEqual(self.add(self.member.phone_number).status_code, 400)

    def test_concurrent_duplicate_becomes_400_not_500(self):
        self.login(self.owner)
        with patch.object(ProjectMember.objects, "create", side_effect=IntegrityError):
            response = self.add()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("phone_number", response.data)

    def test_admin_can_add_only_regular_members(self):
        self.login(self.admin)
        before = ProjectMember.objects.count()
        self.assertEqual(self.add(role=Role.ADMIN).status_code, 403)
        self.assertEqual(self.add(role=Role.OWNER).status_code, 403)
        self.assertEqual(ProjectMember.objects.count(), before)
        self.assertEqual(self.add(role=Role.MEMBER).status_code, 201)

    def test_member_cannot_add(self):
        self.login(self.member)
        self.assertEqual(self.add().status_code, 403)

    def test_outsider_gets_404(self):
        self.login(self.outsider)
        self.assertEqual(self.add().status_code, 404)


class MemberRemoveTests(BaseProjectTest):
    def delete(self, membership, project=None):
        return self.client.delete(self.member_url(membership, project))

    def test_owner_can_remove_member_and_admin(self):
        self.login(self.owner)
        self.assertEqual(self.delete(self.member_m).status_code, 204)
        self.assertEqual(self.delete(self.admin_m).status_code, 204)
        self.assertFalse(ProjectMember.objects.filter(pk=self.member_m.pk).exists())

    def test_removed_user_loses_access(self):
        self.login(self.owner)
        self.delete(self.member_m)
        self.login(self.member)
        self.assertEqual(self.client.get(self.detail_url).status_code, 404)

    def test_admin_can_remove_only_regular_members(self):
        other_admin = add_member(self.project, make_user("09127770000"), Role.ADMIN)
        self.login(self.admin)
        self.assertEqual(self.delete(other_admin).status_code, 403)
        self.assertEqual(self.delete(self.owner_m).status_code, 403)
        self.assertEqual(self.delete(self.admin_m).status_code, 403)
        self.assertEqual(self.delete(self.member_m).status_code, 204)

    def test_admin_cannot_remove_owner_even_when_several_owners(self):
        add_member(self.project, make_user("09127770001"), Role.OWNER)
        self.login(self.admin)
        self.assertEqual(self.delete(self.owner_m).status_code, 403)
        self.assertEqual(owners_of(self.project), 2)

    def test_member_cannot_remove_anyone(self):
        self.login(self.member)
        self.assertEqual(self.delete(self.admin_m).status_code, 403)
        self.assertEqual(self.delete(self.member_m).status_code, 403)

    def test_outsider_gets_404(self):
        self.login(self.outsider)
        self.assertEqual(self.delete(self.member_m).status_code, 404)

    def test_membership_of_another_project_is_not_reachable(self):
        other_project = make_project(self.outsider, name="Beta")
        other_m = ProjectMember.objects.get(project=other_project, user=self.outsider)
        self.login(self.owner)
        response = self.client.delete(
            reverse("member-detail", args=[self.project.pk, other_m.pk])
        )
        self.assertEqual(response.status_code, 404)
        self.assertTrue(ProjectMember.objects.filter(pk=other_m.pk).exists())

    def test_unknown_membership_is_404(self):
        self.login(self.owner)
        url = reverse("member-detail", args=[self.project.pk, 999999])
        self.assertEqual(self.client.delete(url).status_code, 404)


class OwnerInvariantTests(BaseProjectTest):
    """A project must always keep at least one owner."""

    def delete(self, membership):
        return self.client.delete(self.member_url(membership))

    def test_last_owner_cannot_be_removed(self):
        self.login(self.owner)
        response = self.delete(self.owner_m)
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(owners_of(self.project), 1)

    def test_owner_can_leave_when_another_owner_exists(self):
        add_member(self.project, make_user("09127770001"), Role.OWNER)
        self.login(self.owner)
        self.assertEqual(self.delete(self.owner_m).status_code, 204)
        self.assertEqual(owners_of(self.project), 1)

    def test_owner_can_remove_another_owner_but_never_the_last_one(self):
        second = make_user("09127770001")
        second_m = add_member(self.project, second, Role.OWNER)

        self.login(self.owner)
        self.assertEqual(self.delete(second_m).status_code, 204)
        self.assertEqual(owners_of(self.project), 1)
        self.assertEqual(self.delete(self.owner_m).status_code, 409)
        self.assertEqual(owners_of(self.project), 1)

    def test_invariant_holds_after_a_chain_of_removals(self):
        extra = [add_member(self.project, make_user(f"0912888000{i}"), Role.OWNER) for i in range(3)]
        self.login(self.owner)
        for membership in extra:
            self.assertEqual(self.delete(membership).status_code, 204)
        self.assertEqual(self.delete(self.owner_m).status_code, 409)
        self.assertEqual(owners_of(self.project), 1)


class ConcurrentOwnerRemovalTests(TransactionTestCase):
    """
    Real threads and real transactions (needs PostgreSQL row locks).
    Two owners try to remove each other at the same moment. Without the row
    lock both requests see "2 owners" and the project ends up with none.
    With the lock exactly one of them succeeds.
    """

    def test_two_owners_cannot_remove_each_other(self):
        first = make_user("09129990001")
        second = make_user("09129990002")
        project = make_project(first)
        first_m = ProjectMember.objects.get(project=project, user=first)
        second_m = add_member(project, second, Role.OWNER)

        barrier = threading.Barrier(2)
        results, errors = [], []

        def worker(actor, target):
            try:
                client = APIClient()
                client.force_authenticate(user=actor)
                url = reverse("member-detail", args=[project.pk, target.pk])
                barrier.wait(timeout=10)
                results.append(client.delete(url).status_code)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                connection.close()

        threads = [
            threading.Thread(target=worker, args=(first, second_m)),
            threading.Thread(target=worker, args=(second, first_m)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        self.assertEqual(errors, [])
        self.assertEqual(owners_of(project), 1)
        self.assertEqual(results.count(204), 1)


class RoleRuleTests(SimpleTestCase):
    def test_can_manage_matrix(self):
        o, a, m = Role.OWNER, Role.ADMIN, Role.MEMBER
        expected = {
            (o, o): True, (o, a): True, (o, m): True,
            (a, o): False, (a, a): False, (a, m): True,
            (m, o): False, (m, a): False, (m, m): False,
        }
        for (actor, target), allowed in expected.items():
            with self.subTest(actor=actor, target=target):
                self.assertEqual(can_manage(actor, target), allowed)

    def test_at_least(self):
        self.assertTrue(at_least("owner", "admin"))
        self.assertTrue(at_least("admin", "admin"))
        self.assertFalse(at_least("member", "admin"))
