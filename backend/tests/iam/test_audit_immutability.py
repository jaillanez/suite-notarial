import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditEvent, RequestContext, record_audit

CTX = RequestContext(ip_address="203.0.113.5", user_agent="pytest", correlation_id="t-1")


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_security_logs SET severity = 'INFO'",
        "DELETE FROM audit_security_logs",
        "TRUNCATE audit_security_logs",
    ],
)
async def test_application_role_cannot_rewrite_audit(
    db_session: AsyncSession, statement: str
) -> None:
    record_audit(db_session, CTX, AuditEvent.LOGOUT)
    await db_session.commit()

    with pytest.raises(DBAPIError, match="permission denied"):
        async with db_session.begin_nested():
            await db_session.execute(text(statement))
