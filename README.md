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
