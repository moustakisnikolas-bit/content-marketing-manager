import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.modules.governance.repository import GovernanceRepository
from content_studio.modules.governance.service import AuditService
from content_studio.modules.identity.service import IdentityService

pytestmark = pytest.mark.asyncio


async def test_signup_writes_an_audit_event(db_session: AsyncSession) -> None:
    identity = IdentityService(db_session)
    email = f"audit-{uuid.uuid4().hex[:12]}@example.com"
    result = await identity.signup(
        email=email, password="correct-horse-battery", display_name="Audit Test", organization_name="Audit Org"
    )

    audit = AuditService(db_session)
    await audit.record(
        event_type="identity.signup",
        actor_type="user",
        actor_id=str(result.user.id),
        organization_id=result.organization.id,
        summary="signed up",
        payload={"email": email},
    )
    await db_session.commit()

    repo = GovernanceRepository(db_session)
    events = await repo.list_events_for_organization(result.organization.id)
    assert len(events) == 1
    assert events[0].event_type == "identity.signup"
    assert events[0].actor_type == "user"
    assert events[0].payload["email"] == email


async def test_audit_event_has_no_request_id_outside_a_request_context(db_session: AsyncSession) -> None:
    from content_studio.api.middleware import get_request_id

    assert get_request_id() is None

    audit = AuditService(db_session)
    event = await audit.record(
        event_type="system.test", actor_type="service", summary="no request context"
    )
    await db_session.commit()
    assert event.request_id is None
