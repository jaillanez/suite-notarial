from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.iam.catalog import PERMISSION_DESCRIPTIONS, ROLES, SENSITIVE_PERMISSIONS, Perm
from app.modules.iam.models import Permission, Role


async def test_database_matches_catalog(db_session: AsyncSession) -> None:
    perms = set((await db_session.execute(select(Permission.code))).scalars())
    roles = {r.code: r for r in (await db_session.execute(select(Role))).scalars()}

    assert perms == {p.value for p in Perm}
    assert set(roles) == {r.code for r in ROLES}
    for definition in ROLES:
        role = roles[definition.code]
        assert role.mfa_required == definition.mfa_required
        assert {p.code for p in role.permissions} == {p.value for p in definition.permissions}


def test_every_permission_is_described() -> None:
    assert set(PERMISSION_DESCRIPTIONS) == set(Perm)


def test_roles_with_sensitive_permissions_require_mfa() -> None:
    for role in ROLES:
        if role.permissions & SENSITIVE_PERMISSIONS:
            assert role.mfa_required, role.code
