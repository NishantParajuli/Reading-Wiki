from __future__ import annotations

import pytest

from novelwiki.kernel.errors import InvalidOperation, NotFound, ValidationFailed
from novelwiki.modules.identity.application import IdentityAdminService
from novelwiki.modules.identity.public import IdentityAdminTransactionApi, Principal


class FakeIdentityAdmin:
    def __init__(self, roles: dict[int, str], other_admins: int = 1):
        self.roles = roles
        self.other_admins = other_admins
        self.updated: list[tuple[int, dict]] = []
        self.revoked: list[int] = []
        self.deleted: list[int] = []

    async def user_role(self, user_id):
        return self.roles.get(user_id)

    async def other_admin_count(self, user_id):
        return self.other_admins

    async def update_user(self, user_id, fields):
        self.updated.append((user_id, dict(fields)))

    async def revoke_sessions(self, user_id):
        self.revoked.append(user_id)

    async def delete_user(self, user_id):
        self.deleted.append(user_id)


class FakeBindings:
    def __init__(self, identity):
        self.identity = identity

    def bind(self, capability):
        assert capability is IdentityAdminTransactionApi
        return self.identity


class FakeUow:
    def __init__(self, identity):
        self.transaction = FakeBindings(identity)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


def principal(user_id=1):
    return Principal(user_id=user_id, role="admin")


@pytest.mark.asyncio
async def test_suspend_updates_user_revokes_sessions_and_ai_jobs():
    identity = FakeIdentityAdmin({2: "user"})
    ai_revocations: list[int] = []

    async def revoke_ai(user_id):
        ai_revocations.append(user_id)

    service = IdentityAdminService(lambda: FakeUow(identity), revoke_ai)
    result = await service.update_user(2, {"status": "suspended"}, principal())
    assert result == "success"
    assert identity.updated == [(2, {"status": "suspended"})]
    assert identity.revoked == [2]
    assert ai_revocations == [2]


@pytest.mark.asyncio
async def test_admin_guards_and_validation_preserve_existing_details():
    identity = FakeIdentityAdmin({1: "admin", 2: "admin"}, other_admins=0)
    service = IdentityAdminService(lambda: FakeUow(identity), lambda _user_id: None)

    with pytest.raises(InvalidOperation, match="own admin account"):
        await service.update_user(1, {"role": "user"}, principal())
    with pytest.raises(ValidationFailed, match="status must be one of"):
        await service.update_user(2, {"status": "unknown"}, principal())
    with pytest.raises(InvalidOperation, match="only admin"):
        await service.update_user(2, {"role": "user"}, principal())
    with pytest.raises(InvalidOperation, match="own account"):
        await service.delete_user(1, principal())
    with pytest.raises(InvalidOperation, match="only admin"):
        await service.delete_user(2, principal())


@pytest.mark.asyncio
async def test_missing_user_and_noop_are_explicit():
    identity = FakeIdentityAdmin({})
    service = IdentityAdminService(lambda: FakeUow(identity), lambda _user_id: None)
    assert await service.update_user(2, {}, principal()) == "noop"
    with pytest.raises(NotFound, match="User not found"):
        await service.update_user(2, {"status": "active"}, principal())
    with pytest.raises(NotFound, match="User not found"):
        await service.delete_user(2, principal())
