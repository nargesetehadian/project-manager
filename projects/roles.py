from .models import ProjectMember

Role = ProjectMember.Role

# Higher number = more power
_RANK = {Role.MEMBER.value: 1, Role.ADMIN.value: 2, Role.OWNER.value: 3}


def at_least(role, minimum):
    return _RANK[str(role)] >= _RANK[str(minimum)]


def can_manage(actor_role, target_role):
    # Owner manages everyone; others only strictly lower roles.
    # So admin -> member only, member -> nobody.
    return str(actor_role) == Role.OWNER.value or _RANK[str(actor_role)] > _RANK[str(target_role)]
