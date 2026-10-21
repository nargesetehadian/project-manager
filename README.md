# Project Manager API

Small REST API for managing projects and their members (Django 3.2 + DRF + PostgreSQL, JWT auth). Use Python 3.8-3.10..

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Create a PostgreSQL database, then (optional) set env vars:
`DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `SECRET_KEY`.

```bash
python manage.py makemigrations accounts projects
python manage.py migrate
python manage.py runserver
```

## Endpoints

| Method | URL | Description |
|---|---|---|
| POST | /api/auth/register/ | `phone_number`, `password` |
| POST | /api/auth/login/ | returns access + refresh |
| POST | /api/auth/token/refresh/ | refresh the access token |
| GET, POST | /api/projects/ | my projects / create project (creator becomes owner) |
| GET, PUT, PATCH, DELETE | /api/projects/{id}/ | details / edit (owner, admin) / delete (owner) |
| GET, POST | /api/projects/{id}/members/ | list / add member (`phone_number`, `role`) |
| DELETE | /api/projects/{id}/members/{member_id}/ | remove member |

Send the token as `Authorization: Bearer <access>`.

## Phone numbers

Accepted: `09123456789`, `9123456789`, `989123456789`, `+989123456789`, `00989123456789`.
All are stored as `09123456789`.

## Permissions

- Member: view project and members
- Admin: edit project, add/remove regular members
- Owner: everything, including deleting the project

## Roles and the owner rule

| Action | Member | Admin | Owner |
|---|---|---|---|
| View project and members | yes | yes | yes |
| Edit project | no | yes | yes |
| Delete project | no | no | yes |
| Add member | no | role `member` only | any role |
| Remove member | no | role `member` only | any member |

**Invariant: a project always has at least one owner.**

- The creator becomes the first owner automatically.
- Owners may promote others to owner, so several owners can exist.
- An owner may be removed (or leave) only while another owner remains.
  Removing the last owner returns `409 Conflict`.
- Admins can never add or remove admins/owners (no privilege escalation).

### Design decisions

- **Outsiders get 404, not 403.** Querysets are filtered by membership, so a
  project the user does not belong to is indistinguishable from a missing one.
- **Uniqueness is enforced by the database.** `UniqueConstraint(project, user)`
  and the unique phone number are the source of truth. The code catches
  `IntegrityError` and returns `400` instead of relying on check-then-insert,
  which is racy under concurrent requests.
- **Last-owner check is race-free.** Member removal locks the project row
  (`SELECT ... FOR UPDATE`) inside a transaction, so two owners removing each
  other at the same time are serialized.
- **Phone numbers are normalized once** to `09XXXXXXXXX` (serializer, manager
  and `save()`), which is what makes the uniqueness constraint meaningful.

## Tests

```bash
python manage.py test
```

`ConcurrentOwnerRemovalTests` uses real threads and needs PostgreSQL.

## Architecture

```
views.py        HTTP only: parse request, call service, build response
services.py     business rules and transactions (add/remove member, create project)
roles.py        role ranking: one rule, can_manage(actor, target)
permissions.py  project-level access, reads the annotated my_role
```

- **One role rule.** Owner can manage everyone; any other role can manage only
  strictly lower roles. Admin -> member, member -> nobody. No scattered
  `if role in (...)` checks.
- **No N+1.** `projects_for_user` joins only my membership row and annotates
  `my_role`; serializer and permission reuse it with zero extra queries.
  Tests assert the query count does not grow with the number of rows.
- **Authorize before validate.** Non-managers get 403 before any input
  validation, so they cannot probe which phone numbers are registered.
- **Pagination.** List endpoints return `{count, next, previous, results}`
  (page size 20) with a deterministic ordering.
